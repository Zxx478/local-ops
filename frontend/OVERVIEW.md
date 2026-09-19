# local-ops 前端总控台（Windows 版）· 交付概览

> 依据 `README_WINDOWS.md` 实现的前端界面，遵循「零构建 / 零 CDN / 零框架」哲学：原生 HTML + CSS + ES Modules，与 `server.py` 后端通过 HTTP API 通信，前后端分离。

## 已交付内容

`D:\local_ops\frontend\` 下完整前端项目：

```
frontend/
├── index.html              # SPA 骨架（语义化、可访问、含全部弹窗/抽屉）
├── css/
│   ├── base.css            # 与主题无关的布局骨架 + 响应式 + 可访问性基础
│   └── themes/ops.css      # 深空蓝黑主题（颜色/主题变量）
└── js/
    ├── util.js             # DOM/格式化/Toast/遮罩焦点管理
    ├── api.js              # 后端 API 客户端 + 演示模式自动回退
    ├── state.js            # 全局状态 + 2.2s TTL 轮询
    ├── sparkline.js        # 纯 SVG 火花线（KPI/卡片指标）
    ├── cards.js            # 应用卡片（就地更新，避免轮询闪烁）
    ├── commandPalette.js   # Ctrl+K 命令面板（模糊搜索快速操作）
    ├── logCenter.js        # Ctrl+J 日志中心（实时日志 + 诊断）
    ├── settings.js         # 设置中心 + 应用编辑 + 图形化目录树浏览 + 确认弹窗
    └── app.js              # 入口编排
```

## 功能覆盖（对照 README 清单）

- ✅ 应用卡片：启动 / 停止 / 重启 / 日志，状态徽标、项目类型识别、端口/PID/运行时长
- ✅ 实时状态快照 + 2.2s 轮询（与后端 TTL 对齐），KPI 火花线（CPU/内存/端口/运行数）
- ✅ 命令面板 `Ctrl+K`：按名称模糊搜索，快速启动/停止/重启/看日志/编辑
- ✅ 日志中心 `Ctrl+J`：实时日志尾部（2s 跟随）+ 诊断信息（进程/端口/项目识别/归属链/三重校验）
- ✅ 设置中心：增删改应用、主题、轮询间隔、开机自启
- ✅ 图形化目录树浏览（替代 README 中 `prompt` 逐级方案的朴素体验），逐级进入/返回，键盘可达
- ✅ 图标上传接口预留（`/api/icon`，magic-byte、拒 SVG、限 5MB）
- ✅ 响应式：网格自适应（≥300px 列），移动端按钮收起为图标，KPI 2 列
- ✅ 可访问性：跳转链接、ARIA、键盘导航、焦点可见环、`aria-live` 播报、`prefers-reduced-motion`、深空主题 `color-scheme: dark`

## 与后端对接（API 契约）

前端默认同源调用（由 `server.py` 托管 `frontend/` 静态目录即可）。约定端点见 `js/api.js` 顶部注释，核心为：
`/api/health`、`/api/state`、`/api/apps`（增删改）、`/api/apps/:id/{start,stop,restart}`、`/api/apps/:id/{logs,diagnostics}`、`/api/browse`、`/api/icon`、`/api/settings`。

> 集成时把后端静态根指向 `frontend/`（或反向代理到同源），即可复用其安全中间件（Host 校验、同源 Cookie、无 CORS）。

## 预览方式

无后端时前端自动进入**演示模式**（本机模拟数据，火花线实时波动），便于独立预览：
- 已启动本地静态服务：`http://127.0.0.1:8080/`（推荐，确保 ES Module 正常加载）
- 或直接用任意静态服务器托管 `frontend/` 目录

## 自检结果（web-design-guidelines）

- 9 个 JS 模块 `node --check` 全部通过
- 53 个 JS 引用的元素 ID 与 HTML 完全对应，无缺失
- 全部静态资源 HTTP 200
- 可访问性：图标按钮均有 `aria-label`；表单控件均有 `<label>`；破坏性操作（删除应用）走确认弹窗；无 `transition:all`、无 `outline-none` 无替代、无禁用缩放
