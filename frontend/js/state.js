// state.js — 全局状态 + 轮询（2.2s TTL，与后端缓存对齐）
import { API } from "./api.js";

export const store = {
  apps: [],
  kpis: { cpu: 0, mem: 0, ports: 0 },
  settings: { theme: "ops", pollInterval: 2200, autostart: false },
  mode: "live",
  filter: "",
  _timer: null,
  _subs: new Set(),
};

export function subscribe(fn) {
  store._subs.add(fn);
  return () => store._subs.delete(fn);
}

function emit() {
  for (const fn of store._subs) fn(store);
}

export async function refresh() {
  const [state, health] = await Promise.all([
    API.getState().catch(() => ({ apps: [], kpis: { cpu: 0, mem: 0, ports: 0 } })),
    API.health().catch(() => ({ ok: false })),
  ]);
  store.apps = state.apps || [];
  store.kpis = state.kpis || { cpu: 0, mem: 0, ports: 0 };
  store.mode = API.mode;
  document.dispatchEvent(new CustomEvent("ops:health", { detail: health }));
  emit();
  return store;
}

export function startPolling() {
  stopPolling();
  const tick = () => refresh();
  store._timer = setInterval(tick, store.settings.pollInterval || 2200);
}

export function stopPolling() {
  if (store._timer) { clearInterval(store._timer); store._timer = null; }
}

export function setPollInterval(ms) {
  store.settings.pollInterval = ms;
  if (store._timer) startPolling();
}

export function getApp(id) {
  return store.apps.find((a) => a.id === id);
}

export function setFilter(v) {
  store.filter = v;
  emit();
}
