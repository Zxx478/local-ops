// cards.js — 应用卡片渲染（就地更新，避免轮询闪烁）
import { el, escapeHtml, relativeTime } from "./util.js";
import { updateSparkline } from "./sparkline.js";

let grid = null;
const cardEls = new Map(); // id -> { root, refs }

export function initCards(container) {
  grid = container;
}

function statusLabel(app) {
  if (app.type === "batch") return app.running ? "运行中" : "待运行";
  return app.running ? "运行中" : "已停止";
}

function buildCard(app, actions) {
  const iconBox = el("div", { class: "card__icon", "aria-hidden": "true" });
  if (app.icon) {
    const img = el("img", { src: app.icon, alt: "", width: 42, height: 42 });
    iconBox.append(img);
  } else {
    iconBox.textContent = "▣";
  }

  const spark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  spark.setAttribute("class", "card__spark");
  spark.setAttribute("viewBox", "0 0 240 34");
  spark.setAttribute("preserveAspectRatio", "none");
  spark.setAttribute("aria-hidden", "true");

  const name = el("div", { class: "card__name", title: app.name }, app.name);
  const cmd = el("div", { class: "card__cmd", title: app.command }, app.command);
  const typeBadge = el("span", {
    class: `badge badge--${app.type === "batch" ? "batch" : "service"}`,
  }, app.type === "batch" ? "批处理" : "服务");
  const projBadge = el("span", { class: "badge", title: "项目类型识别" }, "◎ " + (app.project || "—"));
  const badges = el("div", { class: "card__badges" }, [typeBadge, projBadge]);

  const status = el("span", { class: "status-pill", dataset: { state: app.running ? "running" : (app.type === "batch" ? "batch" : "stopped") } }, [
    el("span", { class: "dot", "aria-hidden": "true" }),
    statusLabel(app),
  ]);
  const dot = status.querySelector(".dot"); // 缓存，避免轮询时重建

  const meta = el("div", { class: "card__meta" }, [name, cmd, badges]);
  const head = el("div", { class: "card__head" }, [iconBox, meta, status]);

  const portText = app.port ? `:${app.port}` : "—";
  const mPort = el("b", {}, portText);
  const mUptime = el("span", {}, app.running ? relativeTime(app.startedAt) : "—");
  const mPid = el("b", {}, app.pid ? String(app.pid) : "—");
  const metrics = el("div", { class: "card__metrics" }, [
    el("span", { class: "card__metric" }, ["端口 ", mPort]),
    el("span", { class: "card__metric" }, ["运行 ", mUptime]),
    el("span", { class: "card__metric" }, ["PID ", mPid]),
  ]);

  const btnStart = el("button", { class: "btn btn--primary", type: "button", "aria-label": `启动 ${app.name}`, onclick: () => actions.onStart(app.id) }, "启动");
  const btnStop = el("button", { class: "btn btn--ghost", type: "button", "aria-label": `停止 ${app.name}`, onclick: () => actions.onStop(app.id) }, "停止");
  const btnRestart = el("button", { class: "btn btn--ghost", type: "button", "aria-label": `重启 ${app.name}`, onclick: () => actions.onRestart(app.id) }, "重启");
  const btnLog = el("button", { class: "btn btn--ghost", type: "button", "aria-label": `查看 ${app.name} 日志`, onclick: () => actions.onLog(app.id) }, "日志");
  const actionsRow = el("div", { class: "card__actions" }, [btnStart, btnStop, btnRestart, btnLog]);

  const root = el("article", {
    class: "card" + (app.running ? " is-running" : ""),
    dataset: { id: app.id },
    "aria-label": `${app.name}，${statusLabel(app)}`,
  }, [head, metrics, spark, actionsRow]);

  // 初始化火花线历史（缓存末值，轮询时值未变则跳过重绘）
  const seedVal = app.running ? 60 + Math.random() * 30 : 12;
  updateSparkline(spark, "card:" + app.id, seedVal, { color: app.running ? "#34d399" : "#64748b" });

  return {
    root,
    refs: { root, status, dot, name, cmd, projBadge, typeBadge, metrics, mPort, mUptime, mPid, spark, lastSpark: seedVal, btnStart, btnStop, btnRestart, btnLog, iconBox },
  };
}

function updateCard(refs, app) {
  refs.root.classList.toggle("is-running", !!app.running);
  refs.root.setAttribute("aria-label", `${app.name}，${statusLabel(app)}`);
  if (refs.name.textContent !== app.name) { refs.name.textContent = app.name; refs.name.title = app.name; }
  if (refs.cmd.textContent !== app.command) { refs.cmd.textContent = app.command; refs.cmd.title = app.command; }
  const proj = "◎ " + (app.project || "—");
  if (refs.projBadge.textContent !== proj) refs.projBadge.textContent = proj;
  const typeCls = `badge badge--${app.type === "batch" ? "batch" : "service"}`;
  if (refs.typeBadge.className !== typeCls) refs.typeBadge.className = typeCls;
  const typeTxt = app.type === "batch" ? "批处理" : "服务";
  if (refs.typeBadge.textContent !== typeTxt) refs.typeBadge.textContent = typeTxt;

  const st = refs.status;
  const stState = app.running ? "running" : (app.type === "batch" ? "batch" : "stopped");
  if (st.dataset.state !== stState) st.dataset.state = stState;
  // dot 节点已在 buildCard 缓存（refs.dot），无需每轮询重建
  const stLabel = statusLabel(app);
  if (st.lastChild.textContent !== stLabel) st.lastChild.textContent = stLabel;

  // 仅更新文本，避免每轮询 innerHTML 清空 + 重建 DOM
  const port = app.port ? `:${app.port}` : "—";
  if (refs.mPort.textContent !== port) refs.mPort.textContent = port;
  const uptime = app.running ? relativeTime(app.startedAt) : "—";
  if (refs.mUptime.textContent !== uptime) refs.mUptime.textContent = uptime;
  const pid = app.pid ? String(app.pid) : "—";
  if (refs.mPid.textContent !== pid) refs.mPid.textContent = pid;

  // 火花线：值未变（如未运行恒为 12）时跳过重绘
  const sp = app.running ? 60 + Math.random() * 30 : 12;
  if (refs.lastSpark !== sp) {
    updateSparkline(refs.spark, "card:" + app.id, sp, { color: app.running ? "#34d399" : "#64748b" });
    refs.lastSpark = sp;
  }
}

export function renderCards(apps, actions) {
  if (!grid) return;
  const visible = apps;
  // 移除已删除
  for (const [id, entry] of cardEls) {
    if (!visible.find((a) => a.id === id)) { entry.root.remove(); cardEls.delete(id); }
  }
  // 新增 / 更新
  visible.forEach((app, i) => {
    let entry = cardEls.get(app.id);
    if (!entry) {
      entry = buildCard(app, actions);
      cardEls.set(app.id, entry);
    } else {
      updateCard(entry.refs, app);
    }
    // 顺序插入
    const next = visible[i + 1] ? cardEls.get(visible[i + 1].id)?.root : null;
    grid.insertBefore(entry.root, next);
  });
}
