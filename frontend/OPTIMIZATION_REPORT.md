# local-ops 前端性能优化报告

> 依据：`REVIEW_REPORT.md` 第 7、8 节的问题与建议清单
> 实施日期：2026-08-13
> 原则：尊重项目「零构建 / 零框架 / 零 CDN」设计，全部优化为原生 ESM 手段，不引入打包器

---

## 1. 已实施的优化

### 1.1 消除 ES Module 请求瀑布（CRITICAL）
**文件**：`index.html`
- 为首屏必需的 5 个依赖模块（`util / api / state / sparkline / cards`）增加 `<link rel="modulepreload">`，浏览器在 HTML 解析阶段即**并行**预取，消除「app.js → 解析 import → 8 依赖」的两跳瀑布。
- 交互模块（`commandPalette / logCenter / settings`）**故意不预取**，见 1.2。

```html
<link rel="modulepreload" href="js/util.js" />
<link rel="modulepreload" href="js/api.js" />
<link rel="modulepreload" href="js/state.js" />
<link rel="modulepreload" href="js/sparkline.js" />
<link rel="modulepreload" href="js/cards.js" />
```

### 1.2 交互模块懒加载（HIGH）
**文件**：`js/app.js`
- 将 `commandPalette / logCenter / settings` 三个模块由**静态 `import`** 改为**动态 `import()`**，仅在该面板首次被打开（点击 / 快捷键）时才加载并 `init`。
- 新增 `ensureCommand() / ensureLog() / ensureSettings()` 懒加载器，带一次性 `init` 守卫；`actions` 与全局快捷键改为 `ensureX().then(m => m.openX())`。

**收益（实测）**：首屏初始 JS 由全量 9 模块缩减为 6 模块：

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| 首屏初始 JS 字节 | 44530（100%） | 27399（61.5%） |
| 延迟加载 JS 字节 | 0 | 17131（约 16.7 KB，38.5%） |
| 初始 JS 请求数 | 9 | 6（且并行预取） |

> 约 38.5% 的 JS 解析/执行从首屏移除，直接降低 TTI。

### 1.3 卡片渲染效率（MEDIUM）
**文件**：`js/cards.js`
- `buildCard` 中缓存 metrics 三个子节点（`mPort / mUptime / mPid`）与状态圆点（`dot`）的引用，存入 `refs`。
- `updateCard` 改为**仅更新 `textContent`**，删除原每轮询 `m.innerHTML = ""` 重建 3 个 `<span>` 以及 `st.querySelector(".dot")?.replaceWith(...)` 重建圆点的逻辑。
- 增加变更判定（`if (refs.x.textContent !== v)`），相同值不写 DOM，避免无谓重排。
- 火花线增加 `lastSpark` 末值缓存：值未变（如未运行恒为 12）时跳过重绘。
- 删除死代码 `const seed = Array.from(...)`（创建后仅 `void seed`，从未使用）。

**收益**：每 2.2s 轮询对每张卡片的 DOM 析构/创建开销降为 0，仅做文本赋值；停止态卡片的火花线重绘被跳过。

### 1.4 filter 输入防抖（MEDIUM）
**文件**：`js/app.js`
- `$("#filterInput")` 的 `input` 事件改为 `debounce(..., 180)`，复用 `util.debounce`，消除逐键全量重渲染。

### 1.5 favicon（LOW）
**文件**：`index.html`
- 增加内联 `data:` SVG favicon，消除浏览器额外 1 次 `/favicon.ico` 404 请求。

### 1.6 代码规范清理（LOW）
- `js/app.js`：移除未使用的 `openOverlay / closeOverlay / $$` 导入（仅保留 `$ / toast / debounce`）。
- `js/logCenter.js`：合并重复的 `import { toast } from "./util.js"` 到主 import 行。
- `js/state.js`：删除从未被调用的死代码 `patchApp`。

### 1.7 缓存策略落地（HIGH）
**新增文件**：`serve.py`（带缓存头的本地静态服务器）
- `.js / .css / .svg / .json / .ico / .woff2` → `Cache-Control: public, max-age=86400, immutable`（内容不变则浏览器不再发起请求/协商）。
- `index.html` 与根路径 `/` → `Cache-Control: no-cache`（始终重新校验，部署后立即生效）。
- 同时发送 `X-Content-Type-Options: nosniff`。

**后端（server.py）建议**：若由后端托管 `frontend/`，请在响应静态资源时套用相同 `Cache-Control` 头（与生产反向代理/网关的 Brotli/Gzip 压缩一并用）。

---

## 2. 验证结果

| 验证项 | 方法 | 结果 |
|---|---|---|
| JS 语法 | `node --check` 全部 9 个模块 | ✅ 全部通过 |
| 缓存头 | `serve.py` + `curl -I` | ✅ `/`→no-cache；`/js/*.js`、`/css/*.css`→`immutable` |
| 首屏请求集 | 解析 `index.html` + `grep` | ✅ 仅 6 个 JS 进入首屏（5 preload + entry），3 懒加载模块不在 HTML 中 |
| 静态导入消除 | `grep` `app.js` | ✅ 静态 import 交互模块 = 0；动态 `import()` = 3 |
| 初始 JS 体积 | `wc -c` 汇总 | ✅ 44530 → 27399 字节（-38.5%） |

> 说明：动态 `import()` 在浏览器中的实际加载需通过浏览器烟测确认（项目自带演示模式可离线预览）。本次静态校验（语法 + 结构）已通过；建议在浏览器中按 Ctrl+K / Ctrl+J / 设置 各触发一次，确认懒加载模块正常 init 与 open。

---

## 3. 未实施（报告中的可选项，已记录供后续）

- **CSS 合成层**：`.topbar` 的 `backdrop-filter` 与 `body` 固定星空渐变在滚动时重绘成本（LOW）。建议为 `.topbar` 加 `transform: translateZ(0)` 提升为独立合成层，不影响功能，可择机添加。
- **列表虚拟滚动**：当前应用量级无需；若未来应用数增长到几十~上百，再引入。
- **hash 路由 / 深链接**：当前单页运维台可接受；如需分享特定面板再加。

---

## 4. 后续行动清单

1. 在浏览器中烟测：打开命令面板(Ctrl+K)、日志中心(Ctrl+J)、设置中心，确认懒加载模块正常；并用 DevTools Network 观察首屏仅 6 个 JS 请求。
2. 生产部署时由 `server.py` 复用 `serve.py` 的缓存头策略，并启用 Gzip/Brotli。
3. 引入 `package.json` + ESLint（规则 `no-unused-vars` / `no-duplicate-imports`）固化规范检查。
4. 可选：为 `.topbar` 加合成层提示，进一步平滑滚动重绘。
