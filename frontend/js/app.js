// app.js — 入口编排：初始化模块、全局快捷键、轮询、KPI、连接状态
import { $, toast, debounce } from "./util.js";
import { store, subscribe, refresh, startPolling, setPollInterval, setFilter, getApp } from "./state.js";
import { API } from "./api.js";
import { initCards, renderCards } from "./cards.js";
import { updateSparkline } from "./sparkline.js";

/* ---------------- 懒加载交互模块 ----------------
   命令面板 / 日志中心 / 设置中心仅在首次交互时动态加载，
   缩减首屏 JS 解析执行体积（约 17KB）。 */
let _command = null, _log = null, _settings = null;

async function ensureCommand() {
  if (!_command) {
    _command = await import("./commandPalette.js");
    _command.initCommandPalette(actions);
  }
  return _command;
}
async function ensureLog() {
  if (!_log) {
    _log = await import("./logCenter.js");
    _log.initLogCenter();
  }
  return _log;
}
async function ensureSettings() {
  if (!_settings) {
    _settings = await import("./settings.js");
    _settings.initSettings();
  }
  return _settings;
}

const actions = {
  onStart: (id) => act(id, "startApp", "已启动"),
  onStop: (id) => act(id, "stopApp", "已停止"),
  onRestart: (id) => act(id, "restartApp", "已重启"),
  onLog: (id) => ensureLog().then((m) => m.openLogCenter(id)),
  onEdit: (id) => ensureSettings().then((m) => m.openAppEditor(id)),
  onAdd: () => ensureSettings().then((m) => m.openAppEditor()),
  onOpenSettings: () => ensureSettings().then((m) => m.openSettings()),
  onOpenLogs: () => ensureLog().then((m) => m.openLogCenter()),
  onRefresh: () => refresh().then(() => toast("已刷新", "ok")),
};

async function act(id, fn, verb) {
  const a = getApp(id);
  const name = a?.name || id;
  try {
    await API[fn](id);
    toast(`${verb} ${name}`, "ok");
    await refresh();
  } catch (e) {
    toast(`操作失败：${e.message || e}`, "err");
  }
}

/* ---------------- 渲染订阅 ---------------- */
function visibleApps() {
  const f = store.filter.trim().toLowerCase();
  if (!f) return store.apps;
  return store.apps.filter((a) => (a.name + " " + a.command).toLowerCase().includes(f));
}

function updateKpis() {
  const running = store.apps.filter((a) => a.running).length;
  const ports = store.apps.reduce((n, a) => n + (a.ports?.length || 0), 0);
  setText("#kpiRunning .kpi__value", running);
  setText("#kpiPorts .kpi__value", ports);
  setText("#kpiCpu .kpi__value", store.kpis.cpu + "%");
  setText("#kpiMem .kpi__value", store.kpis.mem + "%");
  updateSparkline($('[data-spark="cpu"]'), "kpi:cpu", store.kpis.cpu, { color: "#38bdf8" });
  updateSparkline($('[data-spark="mem"]'), "kpi:mem", store.kpis.mem, { color: "#fbbf24" });
}

function setText(sel, v) { const n = $(sel); if (n) n.textContent = v; }

function updateEmptyState(visible) {
  const empty = $("#emptyState");
  const grid = $("#appGrid");
  if (visible.length === 0) {
    grid.hidden = true;
    empty.hidden = false;
    empty.querySelector(".empty-state__text").textContent = store.apps.length
      ? "没有匹配「" + store.filter + "」的应用。"
      : "点击右上角「设置 → + 添加应用」，或按 Ctrl+K 快速添加。";
  } else {
    grid.hidden = false;
    empty.hidden = true;
  }
}

function onState() {
  const visible = visibleApps();
  renderCards(visible, actions);
  updateKpis();
  updateEmptyState(visible);
  if (_log) _log.refreshLogApps();
}

/* ---------------- 连接状态 ---------------- */
function onHealth(e) {
  const h = e.detail || {};
  const dot = $("#serverStatus .dot");
  const text = $("#serverStatus .status-text") || $("#serverStatus").querySelector(".topbar__status-text");
  let state = "down", label = "后端离线";
  if (h.ok) { state = API.mode === "demo" ? "demo" : "ok"; label = API.mode === "demo" ? "演示模式（无后端）" : "已连接"; }
  dot.dataset.state = state;
  text.textContent = label;
}

/* ---------------- 全局快捷键 ---------------- */
function onGlobalKey(e) {
  const k = e.key.toLowerCase();
  const meta = e.ctrlKey || e.metaKey;
  if (meta && k === "k") { e.preventDefault(); ensureCommand().then((m) => m.openCommandPalette()); }
  else if (meta && k === "j") { e.preventDefault(); ensureLog().then((m) => m.openLogCenter()); }
}

/* ---------------- 启动 ---------------- */
async function boot() {
  initCards($("#appGrid"));

  // 顶栏
  $("#btnCommand").addEventListener("click", () => ensureCommand().then((m) => m.openCommandPalette()));
  $("#btnLogs").addEventListener("click", () => ensureLog().then((m) => m.openLogCenter()));
  $("#btnSettings").addEventListener("click", () => ensureSettings().then((m) => m.openSettings()));
  $("#btnAddApp").addEventListener("click", () => ensureSettings().then((m) => m.openAppEditor()));
  $("#btnEmptyAdd").addEventListener("click", () => ensureSettings().then((m) => m.openAppEditor()));

  // 筛选（防抖，避免逐键全量重渲染）
  $("#filterInput").addEventListener("input", debounce((e) => setFilter(e.target.value), 180));

  // 快捷键
  document.addEventListener("keydown", onGlobalKey);
  document.addEventListener("ops:health", onHealth);

  // 初始状态
  subscribe(onState);

  // 读取偏好并应用
  try {
    const s = await API.getSettings().catch(() => ({ theme: "ops", pollInterval: 2200, autostart: false }));
    store.settings = { ...store.settings, ...s };
    document.documentElement.className = "theme-" + (s.theme || "ops");
    if (s.pollInterval) setPollInterval(s.pollInterval);
  } catch { /* 忽略，使用默认 */ }

  refresh().catch((e) => console.error("local-ops: 初始刷新失败", e));
  startPolling();

  if (API.mode === "demo") {
    toast("未检测到后端，已切换演示模式（数据为本机模拟）", "warn", 5000);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
