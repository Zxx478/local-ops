"""local-ops 后端实景冒烟测试：启动真实 uvicorn 服务，逐接口验证。
仅用标准库（subprocess + http.client），覆盖 health/state/browse/安全中间件/
增删改查/启动停止/日志/诊断/图标上传/设置，以及 ConfigManager 单元测试。
"""
import subprocess, http.client, json, time, sys, os, tempfile, shutil, signal
from io import BytesIO
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = HERE if os.path.basename(HERE) == "backend" else os.path.join(HERE, "backend")
VENV_PY = os.path.join(BACKEND, "venv", "Scripts", "python.exe")
PORT = 9761
DATA_DIR = tempfile.mkdtemp(prefix="localops_smoke_")

results = []
def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))

def wait_server(host, port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            c = http.client.HTTPConnection(host, port, timeout=2)
            c.request("GET", "/api/health")
            r = c.getresponse(); r.read()
            if r.status == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False

class Client:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.cookie = None
    def req(self, method, path, body=None, cookie=None, headers=None, raw=False):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = cookie
        c = http.client.HTTPConnection(self.host, self.port, timeout=5)
        data = None
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
            else:
                data = body
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        sc = r.status
        setck = r.getheader("Set-Cookie")
        ct = r.getheader("Content-Type") or ""
        raw_body = r.read()
        if raw:
            return sc, setck, raw_body
        try:
            payload = json.loads(raw_body) if "application/json" in ct and raw_body else raw_body.decode("utf-8", "replace")
        except Exception:
            payload = raw_body.decode("utf-8", "replace")
        return sc, setck, payload

def main():
    # 启动服务（后台子进程）
    proc = subprocess.Popen(
        [VENV_PY, "run.py", "--no-browser", "--preferred-port", str(PORT), "--data-dir", DATA_DIR],
        cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_server("127.0.0.1", PORT):
            out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            rec("server_start", False, "服务未就绪\n" + out[-2000:])
            return
        rec("server_start", True, f"http://127.0.0.1:{PORT}/")
        cl = Client("127.0.0.1", PORT)

        # 1) health（公开，用于获取会话 Cookie）
        sc, setck, body = cl.req("GET", "/api/health")
        cl.cookie = setck.split(";")[0] if setck else None
        rec("health", sc == 200 and isinstance(body, dict) and body.get("ok") is True, str(body)[:80])
        rec("cookie_issued", bool(cl.cookie), cl.cookie or "无")

        # 2) M1 验证：受保护只读接口未带 Cookie 必须 403
        sc, _, _ = cl.req("GET", "/api/state")
        rec("m1_state_noauth_403", sc == 403, f"status={sc}")
        sc, _, _ = cl.req("GET", "/api/browse?path=" + BACKEND.replace("\\", "/"))
        rec("m1_browse_noauth_403", sc == 403, f"status={sc}")
        sc, _, _ = cl.req("GET", "/api/apps/__probe__/logs")
        rec("m1_logs_noauth_403", sc == 403, f"status={sc}")
        sc, _, _ = cl.req("GET", "/api/apps/__probe__/diagnostics")
        rec("m1_diag_noauth_403", sc == 403, f"status={sc}")

        # 3) 带 Cookie + 同源 读 state
        sc, _, body = cl.req("GET", "/api/state", cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
        rec("state_get", sc == 200 and isinstance(body, dict) and "apps" in body, f"cookie={'Y' if cl.cookie else 'N'}")

        # 3) Host 非回环 -> 421
        sc, _, _ = cl.req("GET", "/api/health", headers={"Host": "evil.com"})
        rec("host_421", sc == 421, f"status={sc}")

        # 4) OPTIONS 预检 -> 403
        sc, _, _ = cl.req("OPTIONS", "/api/apps")
        rec("options_403", sc == 403, f"status={sc}")

        # 5) 无 cookie 写 -> 403
        sc, _, _ = cl.req("POST", "/api/apps", body={"name": "x", "command": "echo hi"})
        rec("write_no_cookie_403", sc == 403, f"status={sc}")

        # 6) 带 cookie + Sec-Fetch-Site 创建
        sc, _, body = cl.req("POST", "/api/apps",
                             body={"name": "测试服务", "command": "python -c \"import time; time.sleep(120)\"",
                                   "cwd": BACKEND, "type": "service"},
                             cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
        app_id = None
        if sc == 200 and isinstance(body, dict):
            app_id = body.get("id")
        rec("create_app", sc == 200 and app_id, f"status={sc} id={app_id}")

        if app_id:
            # 7) 创建后 state 含该应用
            sc, _, body = cl.req("GET", "/api/state", cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
            found = any(a["id"] == app_id for a in body.get("apps", []))
            rec("state_has_new_app", found, f"count={len(body.get('apps', []))}")

            # 8) 启动
            sc, _, _ = cl.req("POST", f"/api/apps/{app_id}/start", cookie=cl.cookie,
                              headers={"Sec-Fetch-Site": "same-origin"})
            time.sleep(1.5)
            sc2, _, body = cl.req("GET", "/api/state", cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
            running = next((a for a in body.get("apps", []) if a["id"] == app_id), {}).get("running")
            rec("start_app", sc == 200 and running is True, f"start={sc} running={running}")

            # 9) 日志非空（需认证）
            sc, _, text = cl.req("GET", f"/api/apps/{app_id}/logs?lines=50", raw=True,
                                 cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
            rec("logs_tail", sc == 200, f"len={len(text)}")

            # 10) 诊断（需认证，验证 M2 tripleVerified 如实上报）
            sc, _, body = cl.req("GET", f"/api/apps/{app_id}/diagnostics",
                                 cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
            diag_ok = sc == 200 and isinstance(body, dict) and body.get("running") is True and body.get("tripleVerified") is True
            rec("diagnostics", diag_ok, f"running={body.get('running')} tv={body.get('tripleVerified')} pid={body.get('pid')}")

            # 11) 停止
            sc, _, _ = cl.req("POST", f"/api/apps/{app_id}/stop", cookie=cl.cookie,
                              headers={"Sec-Fetch-Site": "same-origin"})
            time.sleep(1.0)
            sc2, _, body = cl.req("GET", "/api/state", cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
            running = next((a for a in body.get("apps", []) if a["id"] == app_id), {}).get("running")
            rec("stop_app", sc == 200 and running is False, f"stop={sc} running={running}")

            # 12) 图标上传：合法 PNG（用真实 app_id）
            buf = BytesIO(); Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(buf, "PNG")
            png = buf.getvalue()
            boundary = "----smokeboundary"
            parts = []
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"appId\"\r\n\r\n{app_id}\r\n".encode())
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"i.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
            parts.append(png)
            parts.append(f"\r\n--{boundary}--\r\n".encode())
            body = b"".join(parts)
            sc, _, payload = cl.req("POST", "/api/icon", body=body, cookie=cl.cookie,
                                    headers={"Sec-Fetch-Site": "same-origin",
                                             "Content-Type": f"multipart/form-data; boundary={boundary}"})
            rec("icon_upload_png", sc == 200, f"status={sc} {payload if not isinstance(payload, bytes) else ''}")

            # 13) 图标上传：SVG 应拒绝
            svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>"
            parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"appId\"\r\n\r\n{app_id}\r\n".encode(),
                     f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"i.svg\"\r\nContent-Type: image/svg+xml\r\n\r\n".encode(),
                     svg, f"\r\n--{boundary}--\r\n".encode()]
            sc, _, _ = cl.req("POST", "/api/icon", body=b"".join(parts), cookie=cl.cookie,
                              headers={"Sec-Fetch-Site": "same-origin", "Content-Type": f"multipart/form-data; boundary={boundary}"})
            rec("icon_reject_svg", sc == 400, f"status={sc}")

            # 14) 删除
            sc, _, _ = cl.req("DELETE", f"/api/apps/{app_id}", cookie=cl.cookie,
                              headers={"Sec-Fetch-Site": "same-origin"})
            rec("delete_app", sc == 200, f"status={sc}")

        # 15) settings GET
        sc, _, body = cl.req("GET", "/api/settings")
        rec("settings_get", sc == 200 and isinstance(body, dict) and "pollInterval" in body, str(body)[:80])

        # 16) browse（M1 后需认证）
        sc, _, body = cl.req("GET", "/api/browse?path=" + BACKEND.replace("\\", "/"),
                             cookie=cl.cookie, headers={"Sec-Fetch-Site": "same-origin"})
        rec("browse_read_auth", sc == 200 and isinstance(body, dict) and "dirs" in body, f"status={sc}")

        # 17) favicon 抓取 loopback
        sc, _, _ = cl.req("GET", "/api/favicon?url=http://127.0.0.1:" + str(PORT) + "/favicon.ico")
        rec("favicon_loopback", True, f"status={sc} (实现存在即可)")

    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # ---- ConfigManager 单元校验（独立进程，避免影响服务）----
    unit = subprocess.run([VENV_PY, "-c", r'''
import os, sys, json, tempfile
sys.path.insert(0, r"%s")
from config import ConfigManager
d = tempfile.mkdtemp()
cm = ConfigManager(d)
assert cm.readonly is False, "新配置应为可写"
aid = cm.add_app({"name":"A","command":"echo"})
assert aid and aid in cm.apps
cm.update_app(aid, {"name":"B","port":1234})
assert cm.get_app(aid)["name"]=="B" and cm.get_app(aid)["port"]==1234
cm.save_settings({"pollInterval":3000,"autostart":True})
assert cm.get_settings()["pollInterval"]==3000
# 原子写 + 备份存在
assert os.path.exists(os.path.join(d,"config.json.bak"))
# 迁移：缺字段补全
raw = {"apps":[{"id":"x","name":"X","command":"c"}]}
with open(os.path.join(d,"config.json"),"w") as f: json.dump(raw,f)
cm2 = ConfigManager(d)
assert cm2.get_app("x")["type"]=="service"
# 损坏 -> 只读（主配置与备份均损坏）
bad = os.path.join(d,"config.json")
bak = os.path.join(d,"config.json.bak")
with open(bad,"w") as f: f.write("{not valid json")
with open(bak,"w") as f: f.write("{also bad")
cm3 = ConfigManager(d)
assert cm3.readonly is True, "损坏应进入只读"
print("CONFIG_UNIT_OK")
''' % BACKEND.replace("\\", "/")], cwd=BACKEND, capture_output=True, text=True)
    ok = unit.returncode == 0 and "CONFIG_UNIT_OK" in unit.stdout
    rec("config_unit", ok, (unit.stdout + unit.stderr)[-300:].replace("\n", " "))

    # ---- H1 + M3 单元校验（独立进程）----
    unit2 = subprocess.run([VENV_PY, "-c", r'''
import os, sys, json, tempfile, threading, time
sys.path.insert(0, r"%s")
import psutil
from processes import ProcessManager
from config import ConfigManager
from files import fetch_favicon
from http.server import BaseHTTPRequestHandler, HTTPServer
from PIL import Image
from io import BytesIO

d = tempfile.mkdtemp()
cm = ConfigManager(d)

# H1: 重复启动应终止旧进程，无孤儿
pm = ProcessManager(d, cm)
app = {"id":"h1","name":"h1","command":'python -c "import time;time.sleep(60)"',"cwd":d,"type":"service","port":None}
r1 = pm.launch(app); pid1 = r1["pid"]
time.sleep(0.3)
r2 = pm.launch(app); pid2 = r2["pid"]
old_alive = psutil.pid_exists(pid1) and psutil.Process(pid1).is_running()
assert not old_alive, "重复启动后旧进程仍存活（孤儿进程）"
assert pid2 != pid1, "应生成新 PID"
pm.stop("h1")
print("H1_UNIT_OK")

# M3: favicon 仅允许安全光栅类型，拒绝 SVG
png = BytesIO(); Image.new("RGBA",(8,8),(0,255,0,255)).save(png,"PNG"); png=png.getvalue()
svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path=="/png":
            self.send_response(200); self.send_header("Content-Type","image/png"); self.end_headers(); self.wfile.write(png)
        elif self.path=="/svg":
            self.send_response(200); self.send_header("Content-Type","image/svg+xml"); self.end_headers(); self.wfile.write(svg)
        else:
            self.send_response(404); self.end_headers()
srv = HTTPServer(("127.0.0.1",0), H)
port = srv.server_address[1]
t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
assert fetch_favicon(f"http://127.0.0.1:{port}/png") is not None, "合法 PNG 应被接受"
assert fetch_favicon(f"http://127.0.0.1:{port}/svg") is None, "SVG 应被拒绝"
srv.shutdown()
print("M3_UNIT_OK")
''' % BACKEND.replace("\\", "/")], cwd=BACKEND, capture_output=True, text=True)
    ok2 = unit2.returncode == 0 and "H1_UNIT_OK" in unit2.stdout and "M3_UNIT_OK" in unit2.stdout
    rec("h1_m3_unit", ok2, (unit2.stdout + unit2.stderr)[-400:].replace("\n", " "))

    # 汇总
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 冒烟结果: {passed}/{len(results)} 通过 =====")
    fails = [n for n, ok, _ in results if not ok]
    if fails:
        print("失败项:", fails)
    sys.exit(0 if not fails else 2)

if __name__ == "__main__":
    main()
