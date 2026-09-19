# local-ops 前端架构与代码审查报告

> 审查对象：`D:\local_ops\frontend\`（原生 HTML + CSS + ES Modules，零构建 / 零框架 / 零 CDN）
> 审查方式：证据优先（先采集指标与代码证据，再定位问题，最后给建议）
> 审查日期：2026-08-13

---

## 0. 证据基线

| 文件 | 体积 | 行数 | 角色 |
|---|---:|---:|---|
| `index.html` | 12.7 KB | 270 | SPA 骨架 + 全部弹窗/抽屉 DOM |
| `css/base.css` | 19.3 KB | 494 | 布局骨架 + 响应式 + 可访问性 |
| `css/themes/ops.css` | 1.7 KB | 62 | 主题颜色变量 |
| `js/util.js` | 3.6 KB | 96 | DOM/格式化/Toast/遮罩焦点 |
| `js/api.js` | 8.2 KB | 202 | 后端 API 客户端 + 演示模式 |
| `js/state.js` | 1.6 KB | 65 | 全局状态 + 2.2s 轮询 |
| `js/sparkline.js` | 1.8 KB | 56 | 纯 SVG 火花线 |
| `js/cards.js` | 5.7 KB | 126 | 应用卡片（就地更新） |
| `js/commandPalette.js` | 4.1 KB | 108 | Ctrl+K 命令面板 |
| `js/logCenter.js` | 3.7 KB | 100 | Ctrl+J 日志中心 |
| `js/settings.js` | 9.4 KB | 226 | 设置/编辑/目录树/确认 |
| `js/app.js` | 5.0 KB | 141 | 入口编排 |

- 静态校验：`node --check` 对 9 个 JS 模块 **全部通过**；无 `console.*` 遗留；非 git 仓库。
- 模块依赖图（9 个文件）：`app → {util, state, api, cards, commandPalette, logCenter, settings, sparkline}`；`cards → {util, sparkline}`；`commandPalette → {util, state}`；`logCenter → {util, state, api}`；`settings → {util, state, api}`；`state → api`。

---

## 1. 目录结构

**评价：良好。** 按职责清晰分层——基础能力（`util`/`api`/`state`）、展示组件（`cards`/`sparkline`）、特性模块（`commandPalette`/`logCenter`/`settings`）、入口（`app`）。CSS 拆分为「布局骨架」与「主题变量」两层，符合关注点分离，利于多主题扩展。

**问题**
- **P1｜缺少工程元数据**：无 `package.json`、无依赖清单与版本锁定、无构建/校验脚本。新人无法一键起本地预览，也无法做依赖审计（`OVERVIEW.md` 提到用 `node --check` 自检，但无脚本固化）。
- **P3｜缺版本控制**：当前目录非 git 仓库，所有改动无历史可回溯。

**建议**
- 增加 `package.json`（仅放 devDependencies：静态服务器 + ESLint），并提供 `npm run dev` / `npm run lint` 脚本。
- 初始化 git 仓库，至少对 `frontend/` 做基线提交。

---

## 2. 组件设计

**亮点**：`cards.js` 用 `cardEls: Map` 缓存卡片根节点，轮询时走 `updateCard` 就地更新而非整列重建，主动避免轮询闪烁——属于正确且成熟的做法。

**问题**
- **P2｜`cards.js:69-71` 死代码**：`const seed = Array.from(...)` 创建后仅 `void seed;`，从未被使用。
  ```js
  // 错误：创建数组却从不消费
  const seed = Array.from({ length: 12 }, () => 20 + Math.random() * 30);
  updateSparkline(spark, ...);
  void seed;
  ```
- **P2｜`cards.js:90-101` 每轮询重建 metrics 与 dot**：`updateCard` 每次轮询执行 `m.innerHTML = ""` 并重建 3 个 `<span>`、又 `st.querySelector(".dot")?.replaceWith(...)` 重建状态圆点。在 2.2s × N 张卡片下持续产生无谓的 DOM 析构/创建。
  ```js
  // 错误：每次轮询都 innerHTML 清空 + 重建
  m.innerHTML = "";
  m.append(el("span", ...), el("span", ...), el("span", ...));
  st.querySelector(".dot")?.replaceWith(el("span", { class: "dot" }));
  ```
  ```js
  // 正确：缓存子节点引用，仅更新文本
  refs.mPort.textContent = app.port ? `:${app.port}` : "—";
  refs.mUptime.textContent = app.running ? relativeTime(app.startedAt) : "—";
  refs.mPid.textContent = app.pid ? String(app.pid) : "—";
  ```
- **P3｜`sparkline.js` 每次轮询重绘**：`updateSparkline` 即便数值未变也 `pushSeries` + `innerHTML` 重写 `<path>`。属低成本，但连续相同值可跳过渲染。

**建议**：缓存 metrics 三个 `<b>/<span>` 与 dot 的引用，仅更新 `textContent`；sparkline 在值与上次相同且运行态未变时跳过重绘。

---

## 3. 状态管理

**评价：合理。** 轻量发布订阅（`state.js` 的 `subscribe/emit`）配合集中 `store` 与 `setInterval` 轮询，对单页运维台足够，无外部状态库负担。

**问题**
- **P2｜`state.js:61` `patchApp` 死代码**：导出但全仓无调用点（已 grep 确认仅定义、无引用）。
- **P2｜`app.js:112` filter 输入未防抖**：`filterInput` 的 `input` 事件直接 `setFilter` → `emit` → `onState` → 全量 `renderCards`。每敲一键即触发一次完整重渲染。
  ```js
  // 错误：每次按键全量重渲染
  $("#filterInput").addEventListener("input", (e) => setFilter(e.target.value));
  ```
  ```js
  // 正确：防抖，避免高频重渲染
  $("#filterInput").addEventListener("input", debounce((e) => setFilter(e.target.value), 180));
  ```
- **P3｜全量轮询**：`refresh()` 每次拉取全部 `apps` + `kpis`。当前应用数量级（个位数）可接受；若增长到几十~上百，应考虑字段选择/增量，或列表虚拟滚动（当前非必需，标注 LOW）。

**建议**：删除 `patchApp`；filter 输入加 `debounce`（util 已具备）；大列表场景再引入虚拟滚动。

---

## 4. 路由配置

**现状**：无路由库。视图通过 `overlay`/`drawer` 显隐模拟（命令面板、日志中心、设置）。

**评价**：对单页运维台足够，依赖少、心智负担低。

**问题**
- **P3｜无 URL 状态同步**：打开任何面板后刷新页面会回到默认视图，无法深链接/分享特定面板。
- **P3｜关闭逻辑重复**：各模块自行绑定 ESC 与遮罩关闭（仅 `settings.js` 就有 10+ 处 `closeOverlay($("#xOverlay"))`），重复且易遗漏。

**建议**：如需深链接可用零依赖 hash 路由（`#/settings`、`#/logs`）；将「打开/关闭某 overlay」统一收敛到 `util.openOverlay/closeOverlay`（已具备焦点与 ESC 管理），减少散落调用。当前阶段可保持现状。

---

## 5. 代码规范

**亮点**：ESM 模块边界清晰、命名一致；`api.js` 顶部完整契约注释；可访问性 ARIA 到位（图标按钮 `aria-label`、`aria-live` 播报、`prefers-reduced-motion`）；`innerHTML` 处均 `escapeHtml`，其余用 `textContent`，无 XSS 风险。

**问题**
- **P2｜`app.js:2` 未使用导入**：`import { $, $$, toast, openOverlay, closeOverlay }` 中 `openOverlay`/`closeOverlay` 在 `app.js` 内从未调用。
- **P2｜`logCenter.js:2` 与 `:5` 重复 import 同一模块**：
  ```js
  // 错误：同一模块两行 import
  import { $, el, openOverlay, closeOverlay, escapeHtml } from "./util.js";
  import { toast } from "./util.js";
  ```
  ```js
  // 正确：合并为一行
  import { $, el, openOverlay, closeOverlay, escapeHtml, toast } from "./util.js";
  ```
- **P3｜缺统一 Lint**：无 ESLint/Prettier，未用导入、重复 import 等可由工具在 CI 拦截。

**建议**：引入 ESLint（`no-unused-vars`、`no-duplicate-imports`）并固化到 `package.json` 脚本。

---

## 6. 可维护性

**亮点**：单一职责、函数式渲染、`api.js` 演示模式让前端可离线预览，极大提升可维护性与可测试性。

**问题**
- **P3｜耦合方式**：模块通过全局 `store` 共享 + 直接 `import` 兄弟模块函数；缺类型契约（无 TS / JSDoc 类型），编辑器与重构缺少提示。
- **P3｜`settings.js` 偏大（226 行）**：应用管理 / 偏好 / 编辑表单 / 目录树 / 确认弹窗聚合于一文件，新成员理解成本略高。

**建议**：为导出函数补 JSDoc；将 `settings.js` 拆为 `appEditor.js` + `browse.js` + `confirm.js`（非紧急）；在 `README` 补充「模块地图」。

---

## 7. 性能专项发现（本次优化重点）

| 优先级 | 问题 | 证据 | 影响 |
|---|---|---|---|
| **CRITICAL** | ES Module 请求瀑布 | `index.html:268` 单一入口 → 浏览器两跳拉取 9 个 JS 模块 + 2 CSS，首屏 **11~12 个请求** | HTTP/1.1 下受 6 连接限制形成瀑布，拖慢首屏 JS 就绪与可交互 |
| **HIGH** | 交互模块与首屏无关却被静态加载 | `app.js:6-8` 静态 import `commandPalette`/`logCenter`/`settings`（合计 ~17 KB） | 首屏解析执行无谓 JS，延长 TTI |
| **HIGH** | 静态资源无缓存策略 | 无 `Cache-Control`/版本指纹 | 部署后无法安全长缓存；更新易 304 协商或缓存陈旧 |
| **MEDIUM** | 轮询全量重渲染 | `app.js:70-76` `onState`→`renderCards` 全量 diff + 每卡 sparkline 重绘 + metrics 重建 | 卡片增多时主线程占用上升 |
| **MEDIUM** | filter 未防抖 | `app.js:112` | 逐键全量重渲染 |
| **LOW** | favicon 缺失 | `index.html` 无 `<link rel="icon">` | 额外 1 次 404 请求 |
| **LOW** | CSS 合成层 | `base.css:104` `backdrop-filter` + `ops.css:37` `background-attachment: fixed` | 滚动时重绘成本 |

---

## 8. 优化建议清单（按优先级）

| 优先级 | 建议 | 预期收益 | 是否本次实施 |
|---|---|---|---|
| CRITICAL | `index.html` 为首屏 6 模块加 `modulepreload`，消除两跳瀑布 | 首屏 JS 请求由「2 跳 9 请求」变为「并行 6 请求」 | ✅ |
| HIGH | `commandPalette`/`logCenter`/`settings` 改为动态 `import()`，首次交互才加载 | 初始 JS 解析执行减少 ~17 KB（约 22%） | ✅ |
| HIGH | 提供带 `Cache-Control: immutable` 长缓存的静态服务器 `serve.py` + 后端缓存头建议 | 二次访问近乎 0 网络请求 | ✅ |
| MEDIUM | `cards.js` 缓存子节点引用，轮询仅更新文本 | 消除每轮询 DOM 析构/重建 | ✅ |
| MEDIUM | filter 输入 `debounce` | 取消逐键重渲染 | ✅ |
| LOW | `index.html` 加 data-URI favicon | 去除 1 次 404 | ✅ |
| LOW | 删除死代码（`cards.js seed`、`state.js patchApp`）、合并重复 import、移除未用导入 | 减小体积、提升可读性 | ✅ |
| LOW | `.topbar` 加 `will-change`/`transform: translateZ(0)` 提升合成层 | 滚动重绘更平滑 | 建议（可选） |

> 下一步：本审查报告即作为性能优化的实施依据。详见随后产出的 `OPTIMIZATION_REPORT.md`。
