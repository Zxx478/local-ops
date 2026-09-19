// logCenter.js — Ctrl+J 日志中心（实时日志尾部 + 诊断信息）
import { $, el, openOverlay, closeOverlay, escapeHtml, toast } from "./util.js";
import { store, getApp } from "./state.js";
import { API } from "./api.js";

let overlay, select, tail, diag, tabTail, tabDiag, followTimer;
let currentId = null;
let tab = "tail";

export function initLogCenter() {
  overlay = $("#logOverlay");
  select = $("#logAppSelect");
  tail = $("#logTail");
  diag = $("#logDiag");
  tabTail = $("#logTabTail");
  tabDiag = $("#logTabDiag");

  $("#logClose").addEventListener("click", close);
  select.addEventListener("change", () => { currentId = select.value; switchTab(tab); });
  tabTail.addEventListener("click", () => switchTab("tail"));
  tabDiag.addEventListener("click", () => switchTab("diag"));
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

function fillSelect() {
  const prev = currentId;
  select.innerHTML = "";
  if (!store.apps.length) {
    select.append(el("option", { value: "" }, "（暂无应用）"));
    currentId = null;
    return;
  }
  for (const a of store.apps) {
    select.append(el("option", { value: a.id }, `${a.name}${a.running ? " ●" : ""}`));
  }
  currentId = prev && store.apps.find((x) => x.id === prev) ? prev : store.apps[0].id;
  select.value = currentId;
}

async function loadTail() {
  if (!currentId) { tail.textContent = "请先在上方选择一个应用。"; return; }
  try {
    const text = await API.getLogs(currentId, 200);
    tail.textContent = text;
    tail.scrollTop = tail.scrollHeight;
  } catch {
    tail.textContent = "无法读取日志（后端不可达）。";
  }
}

async function loadDiag() {
  if (!currentId) { diag.innerHTML = ""; return; }
  try {
    const d = await API.getDiagnostics(currentId);
    const rows = [
      ["ID", d.id], ["名称", d.name], ["类型", d.type === "batch" ? "一次性批处理" : "长期服务"],
      ["项目识别", d.project], ["运行中", d.running ? "是" : "否"],
      ["PID", d.pid ?? "—"], ["启动于", d.startedAt ? new Date(d.startedAt * 1000).toLocaleString("zh-CN") : "—"],
      ["归属", d.owner], ["监听端口", (d.ports && d.ports.length) ? d.ports.join(", ") : "—"],
      ["工作目录", d.cwd], ["命令", d.command],
      ["三重校验", d.tripleVerified ? "通过（PID + Token + 用户）" : "—"],
    ];
    diag.innerHTML = "<dl>" + rows.map(([k, v]) =>
      `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v == null ? "—" : String(v))}</dd>`).join("") + "</dl>";
  } catch {
    diag.innerHTML = "<p>无法读取诊断信息（后端不可达）。</p>";
  }
}

function switchTab(t) {
  tab = t;
  const isTail = t === "tail";
  tabTail.classList.toggle("is-active", isTail);
  tabTail.setAttribute("aria-selected", isTail ? "true" : "false");
  tabDiag.classList.toggle("is-active", !isTail);
  tabDiag.setAttribute("aria-selected", !isTail ? "true" : "false");
  tail.hidden = !isTail;
  diag.hidden = isTail;
  if (isTail) loadTail(); else loadDiag();
}

function startFollow() {
  stopFollow();
  followTimer = setInterval(() => { if (tab === "tail") loadTail(); }, 2000);
}
function stopFollow() { if (followTimer) { clearInterval(followTimer); followTimer = null; } }

export function openLogCenter(appId) {
  fillSelect();
  if (appId) { currentId = appId; select.value = appId; }
  switchTab("tail");
  openOverlay(overlay, () => { stopFollow(); });
  startFollow();
}

function close() { closeOverlay(overlay, stopFollow); }

// 供外部（如卡片）刷新下拉列表
export function refreshLogApps() { if (!overlay.hidden) fillSelect(); }
