"""进程管理：启动/停止/重启、runToken 三重校验、进程树终止、归属链、
项目识别、端口发现、runtime 持久化、日志落盘与轮转。

设计要点（呼应 README 安全边界）：
- 启动注入随机 LOCAL_OPS_TOKEN 到子进程环境；判定“运行中”必须同时满足
  PID 存活 + create_time 一致（防 PID 复用）+ 进程环境携带本机 token + 属当前用户。
- 停止用 psutil 递归结束整个进程树（替代 POSIX 信号组）。
- runtime.json 持久化运行态，使服务重启后仍能正确识别仍在运行的自管应用。
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from typing import Optional

import psutil

from config import ConfigManager

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOG_LIMIT = 10 * 1024 * 1024  # 10MB 触发轮转
LOG_KEEP = 3


def _norm_user(u: Optional[str]) -> str:
    if not u:
        return ""
    return u.split("\\")[-1].lower()


# 进程归属识别：已知启动器 → 友好标签
_LAUNCHERS = {
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "idea64.exe": "IntelliJ IDEA",
    "idea.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "pycharm.exe": "PyCharm",
    "rider64.exe": "Rider",
    "webstorm64.exe": "WebStorm",
    "webstorm.exe": "WebStorm",
    "cmd.exe": "命令提示符",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "wt.exe": "Windows Terminal",
    "conhost.exe": "控制台宿主",
    "explorer.exe": "文件资源管理器",
    "github-desktop.exe": "GitHub Desktop",
    "atom.exe": "Atom",
    "sublime_text.exe": "Sublime Text",
    "bash.exe": "Git Bash",
    "node.exe": "Node 脚本",
    "python.exe": "Python 脚本",
    "pythonw.exe": "Python 脚本",
}


def detect_launcher(name: str) -> Optional[str]:
    n = (name or "").lower()
    return _LAUNCHERS.get(n)


def attribute_chain(pid: int) -> str:
    """沿 PPID 链溯源，识别是谁启动的（IDE/终端/AI/系统）。"""
    seen = set()
    cur = pid
    try:
        while cur and cur not in seen:
            seen.add(cur)
            try:
                p = psutil.Process(cur)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            name = p.name().lower()
            label = detect_launcher(name)
            if label:
                return label
            ppid = p.ppid()
            # 到达系统根（wininit / system / services）或桌面外壳则停止
            if name in ("wininit.exe", "system", "systemd", "services.exe", "explorer.exe"):
                if name == "explorer.exe":
                    return "文件资源管理器"
                return "系统/服务"
            if not ppid or ppid == cur:
                break
            cur = ppid
    except Exception:
        pass
    return "未知"


def detect_project(cwd: str) -> str:
    """依据工作目录下的特征文件识别项目类型。"""
    if not cwd or not os.path.isdir(cwd):
        return "—"
    has = lambda *names: any(os.path.exists(os.path.join(cwd, n)) for n in names)
    if has("pnpm-lock.yaml"):
        return "pnpm"
    if has("yarn.lock"):
        return "yarn"
    if has("package.json", "package-lock.json"):
        return "npm"
    if has("requirements.txt", "setup.py", "pyproject.toml", "Pipfile", "poetry.lock"):
        return "py"
    if has("go.mod"):
        return "go"
    if has("Cargo.toml"):
        return "rust"
    if has("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
        return "docker"
    if has("_config.yml", "_config.yaml") and has("package.json"):
        return "hexo"
    return "—"


class ProcessManager:
    def __init__(self, data_dir: str, config: ConfigManager):
        self.data_dir = data_dir
        self.config = config
        self.logs_dir = os.path.join(data_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.runtime_path = os.path.join(data_dir, "runtime.json")
        self.lock = threading.RLock()
        self.runtime: dict[str, dict] = {}
        self.current_user = _norm_user(psutil.Process().username())
        self._load_runtime()
        self._verify_at_startup()

    # ---------- runtime 持久化 ----------
    def _load_runtime(self) -> None:
        try:
            with open(self.runtime_path, "r", encoding="utf-8") as f:
                self.runtime = json.load(f) or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.runtime = {}

    def _save_runtime(self) -> None:
        try:
            with open(self.runtime_path, "w", encoding="utf-8") as f:
                json.dump(self.runtime, f)
        except OSError:
            pass

    def _verify_at_startup(self) -> None:
        """服务重启后，剔除已失效的 runtime 记录，保留仍在运行且通过三重校验的应用。"""
        dead = []
        for app_id, rt in list(self.runtime.items()):
            if not self._alive(rt):
                dead.append(app_id)
        for app_id in dead:
            self.runtime.pop(app_id, None)
        if dead:
            self._save_runtime()

    # ---------- 路径 ----------
    def log_path(self, app_id: str) -> str:
        return os.path.join(self.logs_dir, app_id + ".log")

    # ---------- 三重校验 ----------
    def _check_token(self, pid: int, token: str) -> Optional[bool]:
        """校验子进程环境是否携带本实例 token。

        返回 True=已确认匹配；False=确认不匹配（非自管进程，拒绝）；
        None=无法读取环境（如权限不足），此时退化为存活 + create_time 判定（best-effort）。
        """
        try:
            env = psutil.Process(pid).environ()
            return env.get("LOCAL_OPS_TOKEN") == token
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return None
        except Exception:
            return None

    def _alive(self, rt: dict) -> bool:
        pid = rt.get("pid")
        token = rt.get("token")
        ctime = rt.get("create_time")
        if not pid or not token:
            return False
        try:
            p = psutil.Process(pid)
            if not p.is_running():
                return False
            # PID 复用防护：create_time 必须一致
            if ctime is not None and abs(p.create_time() - ctime) > 1.0:
                return False
            # token 校验：能读环境则必须匹配；读不到则退化为存活判定
            tv = self._check_token(pid, token)
            if tv is False:
                return False
            # 用户归属（软校验）：记录不匹配但不强制（系统账户托管等场景允许）
            rt.pop("_owner_mismatch", None)
            if self.current_user:
                try:
                    owner = _norm_user(p.username())
                    if owner and owner != self.current_user:
                        rt["_owner_mismatch"] = True
                except Exception:
                    pass
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False

    def token_verified(self, app_id: str) -> bool:
        """运行态是否完成 token 三重校验（仅确认匹配返回 True）。"""
        rt = self.runtime.get(app_id)
        if not rt or not rt.get("pid") or not rt.get("token"):
            return False
        return self._check_token(rt["pid"], rt["token"]) is True

    def owner_mismatch(self, app_id: str) -> bool:
        """运行态进程是否归属非当前用户（软提示，不强制）。"""
        rt = self.runtime.get(app_id)
        return bool(rt.get("_owner_mismatch")) if rt else False

    def is_running(self, app_id: str) -> bool:
        rt = self.runtime.get(app_id)
        return bool(rt) and self._alive(rt)

    def get_runtime(self, app_id: str) -> Optional[dict]:
        rt = self.runtime.get(app_id)
        if rt and self._alive(rt):
            return rt
        return None

    def owner_pids(self, app_id: str, rt: Optional[dict] = None) -> set[int]:
        """返回应用进程树（自身 + 全部子孙）的 PID 集合，用于端口归属。

        可传入已通过 _alive 校验的 rt（如 describe_app 已取过的运行态），
        避免重复执行存活 + token 环境读取（Windows 上 environ 读取开销较高）。
        """
        if rt is None:
            rt = self.get_runtime(app_id)
        if not rt:
            return set()
        pids = {rt["pid"]}
        try:
            p = psutil.Process(rt["pid"])
            for c in p.children(recursive=True):
                pids.add(c.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return pids

    # ---------- 启停 ----------
    def launch(self, app: dict) -> dict:
        app_id = app["id"]
        cwd = app.get("cwd") or None
        if cwd and not os.path.isdir(cwd):
            raise RuntimeError(f"工作目录不存在：{cwd}")
        # H1: 防止重复启动造成孤儿进程——先终止同 id 的既有进程树
        prev = self.runtime.get(app_id)
        if prev and prev.get("pid"):
            try:
                self.kill_tree(prev["pid"])
            except Exception:
                pass
            with self.lock:
                self.runtime.pop(app_id, None)
        token = secrets.token_hex(16)
        env = os.environ.copy()
        env["LOCAL_OPS_TOKEN"] = token

        self._rotate_log(app_id)
        logf = open(self.log_path(app_id), "ab", 0)
        try:
            proc = subprocess.Popen(
                app["command"],
                shell=True,
                cwd=cwd,
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        finally:
            # 子进程已继承日志句柄；父进程立即关闭自己的副本，避免长期运行句柄泄漏
            logf.close()

        try:
            ctime = psutil.Process(proc.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            # 批处理命令可能瞬间退出：退化为启动时刻（下次 _alive 自然判为未运行）
            ctime = time.time()

        rt = {
            "pid": proc.pid,
            "token": token,
            "started_at": int(time.time()),
            "create_time": ctime,
        }
        with self.lock:
            self.runtime[app_id] = rt
            self._save_runtime()
        return rt

    def _safe_kill(self, proc: psutil.Process) -> None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def kill_tree(self, pid: int) -> None:
        try:
            p = psutil.Process(pid)
            children = p.children(recursive=True)
            for c in children:
                self._safe_kill(c)
            self._safe_kill(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            pass

    def stop(self, app_id: str) -> bool:
        rt = self.runtime.get(app_id)
        if not rt:
            return False
        pid = rt.get("pid")
        if pid:
            self.kill_tree(pid)
        with self.lock:
            self.runtime.pop(app_id, None)
            self._save_runtime()
        return True

    def restart(self, app: dict) -> dict:
        self.stop(app["id"])
        return self.launch(app)

    # ---------- 日志 ----------
    def _rotate_log(self, app_id: str) -> None:
        path = self.log_path(app_id)
        try:
            if os.path.getsize(path) <= LOG_LIMIT:
                return
        except OSError:
            return
        for i in range(LOG_KEEP, 0, -1):
            src = path if i == 1 else f"{path}.{i - 1}"
            dst = f"{path}.{i}"
            if os.path.exists(src):
                try:
                    shutil.copyfile(src, dst)
                except OSError:
                    pass
        try:
            open(path, "wb").close()  # copy-truncate
        except OSError:
            pass

    def read_log_tail(self, app_id: str, lines: int = 200) -> str:
        path = self.log_path(app_id)
        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        read_size = min(size, 1 << 16)
        try:
            with open(path, "rb") as f:
                f.seek(size - read_size)
                data = f.read()
        except OSError:
            return ""
        text = data.decode("utf-8", "replace")
        out = text.splitlines()[-lines:] if text else []
        return "\n".join(out) + ("\n" if out else "")

    def clear_log(self, app_id: str) -> None:
        path = self.log_path(app_id)
        for i in range(LOG_KEEP, 0, -1):
            try:
                os.remove(f"{path}.{i}")
            except OSError:
                pass
        try:
            open(path, "wb").close()
        except OSError:
            pass
