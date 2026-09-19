// commandPalette.js — Ctrl+K 命令面板
import { $, el, openOverlay, closeOverlay } from "./util.js";
import { store } from "./state.js";

let overlay, input, list, actions = {};
let items = [];
let activeIdx = 0;

export function initCommandPalette(handlers) {
  actions = handlers;
  overlay = $("#commandOverlay");
  input = $("#commandInput");
  list = $("#commandList");

  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", "commandList");
  input.setAttribute("aria-autocomplete", "list");

  input.addEventListener("input", () => { activeIdx = 0; buildList(); });
  input.addEventListener("keydown", onKey);
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

function globalCommands() {
  return [
    { key: "add", label: "添加应用", sub: "打开应用编辑表单", run: () => actions.onAdd() },
    { key: "settings", label: "打开设置中心", sub: "管理应用与偏好", run: () => actions.onOpenSettings() },
    { key: "logs", label: "打开日志中心", sub: "查看实时日志与诊断", run: () => actions.onOpenLogs() },
    { key: "refresh", label: "立即刷新状态", sub: "重新拉取一次快照", run: () => actions.onRefresh() },
  ];
}

function buildItems(query) {
  const q = query.trim().toLowerCase();
  const appCmds = store.apps.flatMap((a) => {
    const cmds = [];
    if (!a.running) cmds.push({ key: "start:" + a.id, label: `启动 · ${a.name}`, sub: a.command, run: () => actions.onStart(a.id) });
    else {
      cmds.push({ key: "stop:" + a.id, label: `停止 · ${a.name}`, sub: a.command, run: () => actions.onStop(a.id) });
      cmds.push({ key: "restart:" + a.id, label: `重启 · ${a.name}`, sub: a.command, run: () => actions.onRestart(a.id) });
    }
    cmds.push({ key: "log:" + a.id, label: `日志 · ${a.name}`, sub: "查看实时日志与诊断", run: () => actions.onLog(a.id) });
    cmds.push({ key: "edit:" + a.id, label: `编辑 · ${a.name}`, sub: "修改配置", run: () => actions.onEdit(a.id) });
    return cmds;
  });
  const all = [...appCmds, ...globalCommands()];
  if (!q) return all;
  return all.filter((c) => (c.label + " " + (c.sub || "")).toLowerCase().includes(q));
}

function buildList() {
  items = buildItems(input.value);
  list.innerHTML = "";
  if (!items.length) {
    list.append(el("li", { class: "palette__item" }, el("span", { class: "palette__item-sub" }, "无匹配结果")));
    return;
  }
  items.forEach((c, i) => {
    const node = el("li", {
      class: "palette__item" + (i === activeIdx ? " is-active" : ""),
      role: "option",
      id: "cmd-" + i,
      "aria-selected": i === activeIdx ? "true" : "false",
      onclick: () => runItem(i),
      onmousemove: () => setActive(i),
    }, [
      el("span", { class: "palette__item-k", "aria-hidden": "true" }, i < 9 ? (i + 1) : "·"),
      el("span", { class: "palette__item-label" }, c.label),
      el("span", { class: "palette__item-sub" }, c.sub || ""),
    ]);
    list.append(node);
  });
  list.setAttribute("aria-activedescendant", "cmd-" + activeIdx);
}

function setActive(i) {
  activeIdx = i;
  [...list.children].forEach((n, idx) => {
    const on = idx === i;
    n.classList.toggle("is-active", on);
    n.setAttribute("aria-selected", on ? "true" : "false");
  });
  list.setAttribute("aria-activedescendant", "cmd-" + activeIdx);
}

function onKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(items.length - 1, activeIdx + 1)); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, activeIdx - 1)); }
  else if (e.key === "Enter") { e.preventDefault(); runItem(activeIdx); }
}

function runItem(i) {
  const c = items[i];
  if (!c) return;
  close();
  c.run();
}

function close() { closeOverlay(overlay); }

export function openCommandPalette() {
  input.value = "";
  activeIdx = 0;
  buildList();
  input.setAttribute("aria-expanded", "true");
  openOverlay(overlay, () => { input.value = ""; input.setAttribute("aria-expanded", "false"); });
}
