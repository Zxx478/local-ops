# local-ops 后端（Windows · FastAPI）

依据 `README_WINDOWS.md` 与既有前端（`D:/local_ops/frontend`）契约实现的完整后端。
**前后端分离**：后端全部代码在本目录；前端由本服务同源托管，满足本地信任边界。

## 运行方式

```bat
cd D:\local_ops\backend
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
python run.py                 :: 默认 http://127.0.0.1:9600/，自动打开浏览器
python run.py --no-browser
python run.py --preferred-port 9731 --data-dir D:/local-ops-data
```

## 架构与高并发设计

- **FastAPI 异步 + 单 worker**：事件循环承载大量并发 HTTP 连接；阻塞的 `psutil` 调用通过
  线程池卸载（状态快照整体带 **2.2s TTL 缓存**），普通轮询零开销。
- **共享状态一致性**：进程运行态在单进程内存中统一管理（重启后由 `runtime.json` 重新校验），
  避免多进程状态分裂；如需更高吞吐，可在反向代理后多实例并把 runtime 改为外部存储。

## 模块职责

| 文件 | 职责 |
|---|---|
| `app.py` | FastAPI 应用工厂、路由、中间件注册、前端/资源静态托管、启动自启浏览器 |
| `run.py` | 参数解析、单实例锁（msvcrt/ flock）、端口回退、启动 uvicorn |
| `config.py` | config.json 原子写 + 修改前备份 + 字段迁移 + 损坏只读保护 |
| `processes.py` | 启停/重启、`runToken` 三重校验、进程树终止、归属链、项目识别、日志轮转 |
| `state.py` | 状态快照聚合 + KPI（CPU/内存/端口）+ TTL 缓存 |
| `security.py` | ASGI 安全中间件：回环 Host 校验(421)、无 CORS(OPTIONS→403)、写操作同源 Cookie+Sec-Fetch-Site、安全响应头 |
| `files.py` | 目录浏览、图标上传(magic-byte 拒 SVG/5MB/Pillow 重编码)、favicon SSRF 防护、开机自启 |
| `models.py` | Pydantic 请求模型（输入校验） |

## API 契约（与前端 api.js 对齐）

`GET /api/health`、`GET /api/state`、`POST/PUT/DELETE /api/apps[/:id]`、
`POST /api/apps/:id/{start,stop,restart}`、`GET /api/apps/:id/{logs,diagnostics}`、
`GET /api/browse`、`POST /api/icon`(multipart)、`GET/POST /api/settings`、`GET /api/favicon`。

## 安全边界（完整保留并适配）

仅绑 `127.0.0.1`；Host 非回环返回 421 且不发 cookie；写操作强制同源会话 Cookie（HttpOnly/SameSite=Strict）
+ `Sec-Fetch-Site: same-origin`，否则 403；无 CORS（`OPTIONS` 预检 403）；CSP/X-Frame-Options/nosniff/
Referrer-Policy/CORP/COP 齐全；静态资源 realpath 前缀校验防穿越；图标拒 SVG；favicon 仅限回环明文 http。

## 验证

`python -m py_compile *.py` 通过；端到端冒烟（真实 uvicorn）全量通过：health/state/browse/安全中间件/
增删改查/启停/日志/诊断三重校验/图标/设置/config 单元。
