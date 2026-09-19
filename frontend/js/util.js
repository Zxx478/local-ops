// util.js — 通用辅助函数（DOM、格式化、提示）
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** 创建元素的便捷函数 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (k === "aria" && typeof v === "object") {
      for (const [ak, av] of Object.entries(v)) node.setAttribute("aria-" + ak, av);
    } else if (v !== false && v != null) {
      node.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function escapeHtml(s = "") {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/** 相对时间（Intl 风格，中文） */
export function relativeTime(ts) {
  if (!ts) return "—";
  const diff = Date.now() - ts * 1000;
  if (diff < 0) return "刚刚";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s} 秒前`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}

export function debounce(fn, ms = 200) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** 轻提示，aria-live 播报 */
export function toast(message, type = "info", ms = 3200) {
  const host = $("#toastHost");
  if (!host) return;
  const icon = type === "ok" ? "✓" : type === "err" ? "✕" : type === "warn" ? "⚠" : "ℹ";
  const node = el("div", { class: `toast toast--${type}`, role: "status" }, [
    el("span", { "aria-hidden": "true" }, icon),
    el("span", {}, message),
  ]);
  host.append(node);
  setTimeout(() => {
    node.style.transition = "opacity 200ms ease, transform 200ms ease";
    node.style.opacity = "0";
    node.style.transform = "translateY(8px)";
    setTimeout(() => node.remove(), 220);
  }, ms);
}

/** 打开/关闭遮罩的通用逻辑（ESC 关闭 + 点击遮罩关闭 + 焦点管理） */
export function openOverlay(overlay, onClose) {
  overlay.hidden = false;
  document.body.style.overflow = "hidden";
  const focusable = overlay.querySelector("input, button, select, [tabindex]");
  if (focusable) setTimeout(() => focusable.focus(), 30);
  const onKey = (e) => {
    if (e.key === "Escape") closeOverlay(overlay, onClose);
  };
  const onBackdrop = (e) => { if (e.target === overlay) closeOverlay(overlay, onClose); };
  overlay._handlers = { onKey, onBackdrop };
  document.addEventListener("keydown", onKey);
  overlay.addEventListener("mousedown", onBackdrop);
}

export function closeOverlay(overlay, onClose) {
  if (overlay.hidden) return;
  overlay.hidden = true;
  document.body.style.overflow = "";
  if (overlay._handlers) {
    document.removeEventListener("keydown", overlay._handlers.onKey);
    overlay.removeEventListener("mousedown", overlay._handlers.onBackdrop);
  }
  if (typeof onClose === "function") onClose();
}
