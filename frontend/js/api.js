// api.js — 与后端 server.py 通信的客户端
// 约定接口（与 README 描述的功能一一对应）：
//   GET    /api/health                  健康检查（不枚举进程）
//   GET    /api/state                   实时状态快照（后端带 2.2s TTL 缓存）
//   POST   /api/apps                    新建应用
//   PUT    /api/apps/:id                更新应用
//   DELETE /api/apps/:id                删除应用
//   POST   /api/apps/:id/start          启动
//   POST   /api/apps/:id/stop           停止
//   POST   /api/apps/:id/restart        重启
//   GET    /api/apps/:id/logs?lines=    实时日志尾部
//   GET    /api/apps/:id/diagnostics    诊断信息（进程/端口/项目识别/归属链）
//   GET    /api/browse?path=            目录浏览
//   POST   /api/icon  (multipart)       图标上传（magic-byte，拒 SVG，限 5MB）
//   GET    /api/settings / POST /api/settings  偏好（主题/轮询/自启）
//
// 后端不可达时自动进入「演示模式」，保证前端可独立预览与交互。

const API_BASE = "";

export const api = {
  mode: "live", // 'live' | 'demo'
  _demoWarned: false,
};

async function request(path, opts = {}) {
  try {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? await res.json() : await res.text();
  } catch (err) {
    if (api.mode !== "demo") {
      api.mode = "demo";
      // 首次降级时由调用方决定是否提示
    }
    throw err;
  }
}

/* ---------------- 演示数据 ---------------- */
function seedDemo() {
  const now = Math.floor(Date.now() / 1000);
  return {
    apps: [
      { id: "blog", name: "我的博客", command: "npm run dev", cwd: "D:\\blog", port: 3000, type: "service",
        icon: null, running: true, pid: 4821, startedAt: now - 320, project: "npm", owner: "VS Code 终端", ports: [3000] },
      { id: "api", name: "API 服务", command: "uvicorn main:app --port 8000", cwd: "D:\\api", port: 8000, type: "service",
        icon: null, running: true, pid: 5190, startedAt: now - 95, project: "py", owner: "PowerShell", ports: [8000] },
      { id: "etl", name: "每日数据同步", command: "python etl.py", cwd: "D:\\jobs\\etl", port: null, type: "batch",
        icon: null, running: false, pid: null, startedAt: null, project: "py", owner: "—", ports: [] },
    ],
    kpis: { cpu: 18, mem: 42, ports: 2 },
    health: { ok: true, demo: true },
  };
}

let _demo = null;
function demo() {
  if (!_demo) _demo = seedDemo();
  return _demo;
}

function jitter(v, amp, min = 0, max = 100) {
  const n = v + (Math.random() - 0.5) * amp;
  return Math.max(min, Math.min(max, Math.round(n)));
}

function demoLogs(app) {
  if (!app.running) return `$ ${app.command}\n[已停止] 该应用当前未在运行。在卡片或命令面板中启动后可查看实时日志。\n`;
  const lines = [
    `[${new Date().toLocaleTimeString("zh-CN")}] INFO  服务启动完成，监听端口 ${app.port || "—"}`,
    `[${new Date().toLocaleTimeString("zh-CN")}] INFO  已连接 ${jitter(3, 4, 1, 12)} 个客户端`,
    `[${new Date().toLocaleTimeString("zh-CN")}] DEBUG 心跳正常 · PID ${app.pid}`,
    `[${new Date().toLocaleTimeString("zh-CN")}] INFO  处理请求 GET /health → 200 (${jitter(12, 8, 3, 40)}ms)`,
  ];
  return lines.join("\n") + "\n";
}

/* ---------------- 公开方法 ---------------- */
export const API = {
  async health() {
    if (api.mode === "demo") return demo().health;
    try { return await request("/api/health"); }
    catch { api.mode = "demo"; return demo().health; }
  },

  async getState() {
    if (api.mode === "demo") {
      const d = demo();
      d.kpis.cpu = jitter(d.kpis.cpu, 10);
      d.kpis.mem = jitter(d.kpis.mem, 6);
      return JSON.parse(JSON.stringify(d));
    }
    try { return await request("/api/state"); }
    catch { api.mode = "demo"; return JSON.parse(JSON.stringify(demo())); }
  },

  async startApp(id) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id);
      if (a) { a.running = true; a.pid = 4000 + Math.floor(Math.random() * 5000); a.startedAt = Math.floor(Date.now() / 1000); a.ports = a.port ? [a.port] : []; }
      return { ok: true };
    }
    return request(`/api/apps/${encodeURIComponent(id)}/start`, { method: "POST" });
  },

  async stopApp(id) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id);
      if (a) { a.running = false; a.pid = null; a.startedAt = null; a.ports = []; }
      return { ok: true };
    }
    return request(`/api/apps/${encodeURIComponent(id)}/stop`, { method: "POST" });
  },

  async restartApp(id) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id);
      if (a) { a.pid = 4000 + Math.floor(Math.random() * 5000); a.startedAt = Math.floor(Date.now() / 1000); a.ports = a.port ? [a.port] : []; }
      return { ok: true };
    }
    return request(`/api/apps/${encodeURIComponent(id)}/restart`, { method: "POST" });
  },

  async getLogs(id, lines = 200) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id) || { command: "", running: false, port: null, pid: null };
      return demoLogs(a);
    }
    return request(`/api/apps/${encodeURIComponent(id)}/logs?lines=${lines}`);
  },

  async getDiagnostics(id) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id);
      if (!a) return {};
      return {
        id: a.id, name: a.name, type: a.type, project: a.project,
        running: a.running, pid: a.pid, startedAt: a.startedAt,
        owner: a.owner, ports: a.ports, cwd: a.cwd, command: a.command,
        tripleVerified: a.running ? true : false,
      };
    }
    return request(`/api/apps/${encodeURIComponent(id)}/diagnostics`);
  },

  async browse(path = "") {
    if (api.mode === "demo") {
      const base = path || "D:\\";
      const dirs = ["projects", "tools", "data", "logs", "docs"].filter((d) => Math.random() > 0.3);
      const files = ["readme.md", "config.json", "server.py", "run.bat"].filter((f) => Math.random() > 0.5);
      return { path: base, parent: base.includes("\\") ? base.replace(/\\?[^\\]+$/, "") : "", dirs, files };
    }
    return request(`/api/browse?path=${encodeURIComponent(path)}`);
  },

  async createApp(payload) {
    if (api.mode === "demo") {
      const d = demo();
      const id = (payload.name || "app").toLowerCase().replace(/\W+/g, "-") + "-" + Math.random().toString(36).slice(2, 6);
      d.apps.push({ id, running: false, pid: null, startedAt: null, icon: null, ports: [], project: "—", owner: "—", ...payload });
      return { ok: true, id };
    }
    return request("/api/apps", { method: "POST", body: JSON.stringify(payload) });
  },

  async updateApp(id, payload) {
    if (api.mode === "demo") {
      const a = demo().apps.find((x) => x.id === id);
      if (a) Object.assign(a, payload);
      return { ok: true };
    }
    return request(`/api/apps/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) });
  },

  async deleteApp(id) {
    if (api.mode === "demo") { demo().apps = demo().apps.filter((x) => x.id !== id); return { ok: true }; }
    return request(`/api/apps/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  async getSettings() {
    if (api.mode === "demo") return { theme: "ops", pollInterval: 2200, autostart: false };
    return request("/api/settings");
  },

  async saveSettings(payload) {
    if (api.mode === "demo") return { ok: true };
    return request("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  },

  async uploadIcon(appId, file) {
    if (api.mode === "demo") { const a = demo().apps.find((x) => x.id === appId); if (a) a.icon = "[demo]"; return { ok: true }; }
    const fd = new FormData();
    fd.append("appId", appId);
    fd.append("file", file);
    return request("/api/icon", { method: "POST", body: fd });
  },
};
