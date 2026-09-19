// settings.js — 设置中心：应用管理 / 偏好 / 应用编辑 / 目录树浏览
import { $, el, openOverlay, closeOverlay, toast, escapeHtml } from "./util.js";
import { store, refresh, setPollInterval } from "./state.js";
import { API } from "./api.js";

let handlers = {};
let browseCallback = null;
let confirmResolver = null;

export function initSettings(h) {
  handlers = h || {};

  // 设置弹窗
  $("#settingsClose").addEventListener("click", () => closeOverlay($("#settingsOverlay")));
  $("#tabApps").addEventListener("click", () => switchTab("apps"));
  $("#tabPrefs").addEventListener("click", () => switchTab("prefs"));
  $("#btnNewApp").addEventListener("click", () => openAppEditor());
  $("#btnSavePrefs").addEventListener("click", savePrefs);
  $("#settingsOverlay").addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay($("#settingsOverlay")); });

  // 应用编辑弹窗
  $("#appEditorClose").addEventListener("click", () => closeOverlay($("#appEditorOverlay")));
  $("#appEditorForm").addEventListener("submit", (e) => { e.preventDefault(); submitAppEditor(); });
  $("#fBrowse").addEventListener("click", () => openBrowse($("#fCwd").value || "", (p) => { $("#fCwd").value = p; }));
  $("#appEditorOverlay").addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay($("#appEditorOverlay")); });

  // 目录浏览弹窗
  $("#browseClose").addEventListener("click", () => closeOverlay($("#browseOverlay")));
  $("#browseSelect").addEventListener("click", () => {
    if (browseCallback) browseCallback($("#browsePath").textContent);
    closeOverlay($("#browseOverlay"));
  });
  $("#browseOverlay").addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay($("#browseOverlay")); });

  // 确认弹窗
  $("#confirmCancel").addEventListener("click", () => resolveConfirm(false));
  $("#confirmOk").addEventListener("click", () => resolveConfirm(true));
  $("#confirmOverlay").addEventListener("keydown", (e) => { if (e.key === "Enter") resolveConfirm(true); if (e.key === "Escape") resolveConfirm(false); });
}

/* ---------------- 标签切换 ---------------- */
function switchTab(name) {
  const isApps = name === "apps";
  $("#tabApps").classList.toggle("is-active", isApps);
  $("#tabApps").setAttribute("aria-selected", isApps ? "true" : "false");
  $("#tabPrefs").classList.toggle("is-active", !isApps);
  $("#tabPrefs").setAttribute("aria-selected", !isApps ? "true" : "false");
  $('[data-panel="apps"]').hidden = !isApps;
  $('[data-panel="prefs"]').hidden = isApps;
  if (isApps) renderAppEditorList();
  else fillPrefs();
}

/* ---------------- 应用列表（设置内） ---------------- */
function renderAppEditorList() {
  const ul = $("#appListEditor");
  ul.innerHTML = "";
  if (!store.apps.length) {
    ul.append(el("li", { class: "apps-editor__item" }, el("span", { class: "apps-editor__cmd" }, "还没有应用，点下方「+ 添加应用」。")));
    return;
  }
  for (const a of store.apps) {
    const edit = el("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": `编辑 ${a.name}`, onclick: () => openAppEditor(a.id) }, "编辑");
    const del = el("button", { class: "btn btn--ghost", type: "button", "aria-label": `删除 ${a.name}`, onclick: () => removeApp(a) }, "删除");
    ul.append(el("li", { class: "apps-editor__item" }, [
      el("div", { class: "apps-editor__info" }, [
        el("div", { class: "apps-editor__name" }, a.name),
        el("div", { class: "apps-editor__cmd" }, `${a.command}  ·  ${a.cwd || "—"}`),
      ]),
      el("div", { class: "apps-editor__btns" }, [edit, del]),
    ]));
  }
}

async function removeApp(app) {
  const ok = await confirmDialog(`确定删除「${app.name}」？此操作不可撤销。`);
  if (!ok) return;
  await API.deleteApp(app.id);
  await refresh();
  renderAppEditorList();
  toast(`已删除 ${app.name}`, "ok");
}

/* ---------------- 应用编辑表单 ---------------- */
export function openAppEditor(id) {
  const form = $("#appEditorForm");
  form.reset();
  $("#appEditorMsg").textContent = "";
  ["fName", "fCommand"].forEach((fid) => { $(`#${fid}`).nextElementSibling && ($("#appEditorForm").querySelector(`[data-error-for="${fid}"]`).textContent = ""); });
  if (id) {
    const a = store.apps.find((x) => x.id === id);
    if (!a) return;
    $("#appEditorTitle").textContent = "编辑应用";
    $("#fId").value = a.id;
    $("#fName").value = a.name;
    $("#fCommand").value = a.command;
    $("#fCwd").value = a.cwd || "";
    $("#fPort").value = a.port || "";
    $("#fType").value = a.type || "service";
  } else {
    $("#appEditorTitle").textContent = "添加应用";
    $("#fId").value = "";
  }
  openOverlay($("#appEditorOverlay"));
}

function submitAppEditor() {
  const name = $("#fName").value.trim();
  const command = $("#fCommand").value.trim();
  const cwd = $("#fCwd").value.trim();
  const port = $("#fPort").value ? parseInt($("#fPort").value, 10) : null;
  const type = $("#fType").value;
  const id = $("#fId").value;

  let bad = false;
  const setErr = (fid, msg) => { $("#appEditorForm").querySelector(`[data-error-for="${fid}"]`).textContent = msg || ""; if (msg) bad = true; };
  setErr("fName", name ? "" : "请填写名称");
  setErr("fCommand", command ? "" : "请填写启动命令");
  if (bad) { const f = !name ? $("#fName") : $("#fCommand"); f.focus(); return; }

  const payload = { name, command, cwd, port, type };
  const msg = $("#appEditorMsg");

  (id ? API.updateApp(id, payload) : API.createApp(payload))
    .then(async () => {
      await refresh();
      closeOverlay($("#appEditorOverlay"));
      toast(id ? "已保存修改" : `已添加 ${name}`, "ok");
    })
    .catch((e) => { msg.textContent = "保存失败：" + (e.message || e); });
}

/* ---------------- 偏好 ---------------- */
function fillPrefs() {
  $("#prefTheme").value = store.settings.theme || "ops";
  $("#prefPoll").value = store.settings.pollInterval || 2200;
  $("#prefAutostart").checked = !!store.settings.autostart;
}

async function savePrefs() {
  const payload = {
    theme: $("#prefTheme").value,
    pollInterval: Math.max(500, Math.min(10000, parseInt($("#prefPoll").value, 10) || 2200)),
    autostart: $("#prefAutostart").checked,
  };
  try {
    await API.saveSettings(payload);
    setPollInterval(payload.pollInterval);
    document.documentElement.className = "theme-" + payload.theme;
    $("#settingsMsg").textContent = "已保存";
    setTimeout(() => ($("#settingsMsg").textContent = ""), 2000);
    toast("偏好已保存", "ok");
  } catch (e) {
    $("#settingsMsg").textContent = "保存失败：" + (e.message || e);
  }
}

/* ---------------- 目录树浏览 ---------------- */
async function openBrowse(initial, cb) {
  browseCallback = cb;
  const start = initial || "D:\\";
  openOverlay($("#browseOverlay"));
  await renderBrowse(start);
}

async function renderBrowse(path) {
  $("#browsePath").textContent = path;
  const crumb = $("#browseCrumb");
  crumb.innerHTML = "";
  const parts = path.split(/[\\/]/).filter(Boolean);
  let acc = "";
  parts.forEach((p, i) => {
    acc += (i === 0 ? p + "\\" : p + "\\");
    const seg = acc;
    crumb.append(el("button", { class: "breadcrumb__crumb", type: "button", onclick: () => renderBrowse(seg) }, p));
    if (i < parts.length - 1) crumb.append(el("span", { class: "breadcrumb__sep" }, " › "));
  });

  const list = $("#browseList");
  list.innerHTML = "";
  try {
    const data = await API.browse(path);
    const navTo = (p) => () => renderBrowse(p);
    const keyNav = (p) => (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); renderBrowse(p); } };
    if (data.parent) {
      list.append(el("li", { class: "browse-item", role: "option", tabindex: "0", onclick: navTo(data.parent), onkeydown: keyNav(data.parent) }, [
        el("span", { class: "browse-item__icon", "aria-hidden": "true" }, "⤴"),
        el("span", {}, "..（上一级）"),
      ]));
    }
    for (const d of (data.dirs || [])) {
      const child = (data.path.endsWith("\\") ? data.path : data.path + "\\") + d;
      list.append(el("li", { class: "browse-item", role: "option", tabindex: "0", onclick: navTo(child), onkeydown: keyNav(child) }, [
        el("span", { class: "browse-item__icon", "aria-hidden": "true" }, "📁"),
        el("span", {}, d),
      ]));
    }
    for (const f of (data.files || [])) {
      list.append(el("li", { class: "browse-item browse-item--file", role: "option" }, [
        el("span", { "aria-hidden": "true" }, "📄"),
        el("span", {}, f),
      ]));
    }
    if (!data.dirs?.length && !data.files?.length && !data.parent) {
      list.append(el("li", { class: "browse-item" }, "空目录"));
    }
  } catch {
    list.append(el("li", { class: "browse-item" }, "无法读取目录（后端不可达）"));
  }
}

/* ---------------- 确认弹窗 ---------------- */
function confirmDialog(text) {
  $("#confirmText").textContent = text;
  openOverlay($("#confirmOverlay"));
  return new Promise((resolve) => { confirmResolver = resolve; });
}
function resolveConfirm(val) {
  closeOverlay($("#confirmOverlay"));
  if (confirmResolver) { confirmResolver(val); confirmResolver = null; }
}

export function openSettings() {
  switchTab("apps");
  openOverlay($("#settingsOverlay"));
}
