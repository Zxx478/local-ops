# local-ops（Windows）

把常用项目服务 / 批处理脚本集中到**本地网页**里统一管理：启停、重启、实时状态、日志、进程溯源。
后端 FastAPI **同源托管**前端，前端零构建（原生 HTML/CSS/ES Modules，无框架、无 CDN）。

> 移植自 macOS 项目 [`laogou717/local-ops`](https://github.com/laogou717/local-ops)，
> Windows 原生实现，**无需 WSL / Cygwin**。

## 快速开始

```bat
start.bat                        :: 启动后端（同源托管前端）并自动打开浏览器
start.bat --no-browser           :: 不自动打开浏览器
start.bat --preferred-port 9731  :: 指定首选端口（被占用则自动回退空闲端口）
start.bat --data-dir D:/x        :: 指定数据目录
```

环境要求：Windows 10/11、Python 3.10+。首次运行建议先建虚拟环境：

```bat
cd backend
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

也可直接 `python backend\run.py`。

## 目录结构

```
├── start.bat          # 一体化启动入口
├── backend/           # FastAPI 服务
│   ├── run.py         # 启动入口（单实例锁、端口回退、同源托管 frontend/）
│   ├── app.py         # API 路由聚合
│   ├── processes.py   # 启停/重启、runToken 三重校验、进程树终止、日志轮转
│   ├── config.py      # config.json 原子写 + 备份 + 字段迁移 + 只读保护
│   ├── state.py       # 运行态与指标采样（CPU/内存/mini 图数据）
│   ├── files.py       # 目录浏览与图标上传
│   ├── security.py    # 会话 token、本地访问校验
│   └── venv/          # 虚拟环境（已 gitignore）
└── frontend/          # 零构建前端
    ├── index.html
    ├── css/           # base.css + themes/ops.css
    └── js/            # api / app / cards / logCenter / commandPalette / settings ...
```

## 主要特性

- **统一启停**：卡片式管理本机服务与脚本，支持批量操作与开机自启配置
- **进程可信判定**：PID 存活 + create_time 一致（防 PID 复用）+ 运行环境 token 校验
- **实时指标**：CPU / 内存采样与迷你趋势图，轮询间隔可配
- **日志中心**：在线查看与轮转，Ctrl+J 唤起
- **命令面板**：Ctrl+K 全局操作
- **数据安全**：配置原子写入 + 修改前备份 + 损坏时降级为只读

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+K`（兼容 ⌘K） | 命令面板 |
| `Ctrl+J`（兼容 ⌘J） | 日志中心 |

## 文档

- [`README_WINDOWS.md`](README_WINDOWS.md)：完整 Windows 开发指南与移植对照
- [`backend/OVERVIEW.md`](backend/OVERVIEW.md)：后端模块说明
- [`frontend/OVERVIEW.md`](frontend/OVERVIEW.md)：前端模块说明
- 另有 `REVIEW_REPORT.md` / `OPTIMIZATION_REPORT.md` 记录审查与优化过程
