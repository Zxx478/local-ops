# local-ops · Windows 版开发指南

> 目标：把 macOS 项目 [`laogou717/local-ops`](https://github.com/laogou717/local-ops)
> 的「本地服务 / 批处理任务总控台」**完整移植到 Windows**，功能对等、
> **无需任何兼容层（无 WSL / 无 Cygwin）**，所有代码、命令、配置在 Windows 上直接可跑。
>
> 配套可运行实现位于本目录 `local-ops-windows/`（`server.py` + 原生前端 + `start.bat`）。

---

## 1. 项目简介与移植目标

原版是一个面向 macOS 的本地「指挥台」：把常用项目命令、长期服务和一次性脚本集中到
本地网页里统一管理，带实时监控、日志、进程溯源。其特点是**零第三方运行时依赖**
（后端单文件 `server.py` 只用 Python 标准库）、**前端零构建**（原生 HTML/CSS/ES Modules）。

Windows 移植要在保持这些优点的同时，把 macOS 专属的系统调用替换为 Windows 原生等价物：

| 维度 | 原版（macOS） | Windows 版 |
|---|---|---|
| 运行平台 | macOS 专属 | Windows 10/11 |
| Python | 3.12 硬要求 | 3.10+（更宽松，兼容性更好） |
| 进程/端口枚举 | `ps` / `lsof` | **`psutil`**（Windows 原生 C 扩展） |
| 单实例锁 | `flock` | `msvcrt.locking` 文件锁 |
| 文件选择对话框 | `osascript` | 浏览器内 `/api/browse` 目录浏览 |
| 图标生成 | `iconutil` | Pillow 生成 `.ico`（`tools/make_icon.py`） |
| 启动脚本 | `start.command` | `start.bat` |
| 进程组(PGID) | `os.killpg` | PPID 链溯源 + `psutil` 进程树递归 |
| 数据目录 | `~/Library/...` | `%LOCALAPPDATA%\local-ops` |
| 快捷键 | ⌘K / ⌘J | **Ctrl+K / Ctrl+J**（同时兼容 ⌘） |

### 关于“零依赖”的取舍

原版坚持零运行时依赖，是因为 macOS 自带 `ps`/`lsof` 足够可靠。**Windows 没有可靠的内建
进程-端口溯源工具**（`tasklist`/`netstat` 解析脆弱、`wmic` 已废弃）。因此本移植**仅引入
一个运行时依赖 `psutil`**——它是 Windows 原生 C 扩展，pip 安装即用，属于“平台能力库”而非
“兼容层”，这与原版“用平台原生能力”的设计哲学一致。前端仍保持**零构建、零 CDN、零框架**。

---

## 2. 目录结构

```
local-ops-windows/
├── server.py              # 后端：单文件，Windows 适配核心（约 1000 行）
├── start.bat              # Windows 启动脚本（替代 start.command）
├── requirements.txt       # 仅 psutil + pillow
├── README_WINDOWS.md      # 本指南
├── static/                # 原生前端（无构建、无 CDN）
│   ├── index.html
│   ├── base.css           # 与主题无关的布局骨架
│   ├── themes/ops.css     # 深空蓝黑主题（单主题）
│   └── app.js             # ES Module：轮询/卡片/命令面板/日志/设置/目录浏览
└── tools/
    └── make_icon.py       # 生成 Windows .ico 图标（替代 iconutil）
```

配套实现已通过 `python -m py_compile` 语法校验。

---

## 3. 关键技术点详解

### 3.1 进程 / 端口枚举（Windows 适配核心）

原版每轮跑十几个 `ps`/`lsof` 子进程；Windows 版用 `psutil` 一次性枚举，更可靠也更轻量：

```python
# 枚举全部进程
for p in psutil.process_iter(["pid","name","cmdline","username","ppid","create_time","status"]):
    ...

# 端口 -> 监听 PID（仅 TCP）
for c in psutil.net_connections(kind="tcp"):
    if c.laddr and c.pid:
        port_to_pids.setdefault(c.laddr.port, set()).add(c.pid)
```

> ⚠️ **权限提示**：Windows 下 `net_connections()` 默认只能看到当前用户进程；要看全部端口
> 需要以**管理员**身份运行。非管理员时端口发现可能不完整，但“我们自己拉起并记录了 PID”的
> 应用仍能正确识别，不影响核心功能。

### 3.2 进程归属 Triple-Verification（安全边界）

原版最大亮点是**不会误杀无关进程、绝不按端口杀外部进程**。本版完整保留并改用 Windows 语义：

1. 启动应用时注入随机 `runToken` 到子进程环境变量 `LOCAL_OPS_TOKEN`：
   ```python
   env["LOCAL_OPS_TOKEN"] = token
   proc = subprocess.Popen(full_cmd, shell=False, cwd=cwd, env=env, ...)
   ```
2. 判定“运行中”必须**同时满足**：记录 PID 仍存在 + 该进程（或其命令行）携带本机 token +
   属当前用户。即使 PID 被系统复用，token 不匹配也判定为“非本应用”。
3. 停止时 `kill_tree()` 用 `psutil` 递归结束整个进程树（替代 POSIX 信号组）：
   ```python
   children = proc.children(recursive=True)
   for c in children: _safe_kill(c)
   _safe_kill(proc)
   ```

### 3.3 单实例锁（flock → msvcrt）

```python
import msvcrt
f = open(LOCK_PATH, "w")
msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)   # 非阻塞加锁；失败即已有实例
```

启动前先加锁，重复启动直接退出并提示。退出时解锁。

### 3.4 文件路径 / 环境变量适配

| 概念 | macOS | Windows |
|---|---|---|
| 用户数据根 | `~/Library/Application Support` | `%LOCALAPPDATA%`（代码里 `os.environ["LOCALAPPDATA"]`） |
| 路径分隔符 | `/` | `\`，但 Python `os.path` 自动处理；shell 命令里统一用 `\` |
| 用户标识 | `psutil` username | 同，但 Windows 用户名形如 `DESKTOP\user` |
| 临时目录 | `/tmp` | `%TEMP%`（`tempfile` 模块自动用） |

`server.py` 顶部集中定义所有路径常量，`--data-dir` 可覆盖，便于把数据放到非系统盘。

### 3.5 文件选择：osascript → 浏览器目录浏览

macOS 用 `osascript` 弹系统文件框；Windows 版改为**后端提供 `/api/browse` 接口 + 前端
`prompt` 导航式目录树**，纯浏览器内操作，跨平台且无需 GUI 依赖：

```python
def browse_dir(base):
    base = os.path.realpath(base or "")
    entries = sorted(os.listdir(base))
    dirs = [e for e in entries if os.path.isdir(os.path.join(base, e))]
    # 返回 {path, parent, dirs, files}，前端逐级浏览
```

### 3.6 图标：iconutil → Pillow .ico

`tools/make_icon.py` 把源 PNG 转成多尺寸 `.ico`（16→256），`save_icon()` 在上传时做
**magic-byte 嗅探**并显式拒绝 SVG（防 SVG XSS），限制 5MB。

### 3.7 安全模型（完整保留并适配）

`authorize_request()` 实现「本地浏览器信任边界」：

- **仅绑 `127.0.0.1`**；`Host` 头必须精确匹配本机回环，否则 **421**（DNS 重绑定防护，且不发 cookie）。
- 写操作（`POST/PUT/DELETE`）要求 `Sec-Fetch-Site: same-origin` + `Origin` 同源 +
  **HttpOnly / SameSite=Strict 会话 cookie**。
- **无 CORS**：`OPTIONS` 预检直接 **403**，绝不返回 `Access-Control-Allow-Origin`。
- 安全响应头齐全：CSP、`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy: no-referrer`、CORP/COP。
- 静态文件用 `os.path.realpath` + 前缀校验**防路径穿越**。
- `favicon` 抓取 **SSRF 防护**：仅允许抓取同一 loopback 端口的明文 URL。

### 3.8 重启（execv → 替换进程 + 端口等待）

原版用 helper 进程 + `execv`；Windows 版用 `schedule_restart()` 拉起一个携带
`--replace-pid` 的新进程，新进程 `wait()` 旧 PID 退出并 `wait_for_port_free()` 后再接管端口，
旧进程随后 `os._exit(0)`。

---

## 4. 功能覆盖清单（与原版逐项对照）

| 原版功能 | Windows 版实现 | 状态 |
|---|---|---|
| 启动 / 停止 / 重启应用 | `launch_app` / `stop_app` / `restart` | ✅ |
| 长期服务 + 一次性批处理（type 区分） | `app.type: service|batch` | ✅ |
| 实时状态快照 + TTL 缓存（2.2s） | `get_state` / `_state_cache` | ✅ |
| 进程归属 triple-verification | `runToken` + PID + 用户 | ✅ |
| 进程溯源（谁启动的） | `attribute_chain` 沿 PPID 链识别 IDE/终端/AI | ✅ |
| 项目识别（npm/yarn/pnpm/py/go/rust/docker/hexo） | `detect_project` | ✅ |
| 日志落盘 + >10MB copy-truncate 轮转（留 3 份） | `rotate_log` / `read_log_tail` | ✅ |
| 配置原子写 + 修改前备份 + 迁移 + 只读保护 | `save_config` / `migrate_config` | ✅ |
| 单实例锁 | `msvcrt.locking` | ✅ |
| 端口回退（preferred -> 随机） | `find_free_port` | ✅ |
| 命令面板 | 前端 Ctrl+K | ✅ |
| 日志中心 | 前端 Ctrl+J | ✅ |
| 设置中心（增删改应用 / 主题 / 轮询） | 前端 + API | ✅ |
| 目录浏览（替代 osascript） | `/api/browse` | ✅（增强） |
| KPI 火花线监控 | 前端 `sparkline` | ✅ |
| 图标上传（magic-byte，拒 SVG，5MB） | `save_icon` | ✅ |
| favicon 抓取（SSRF 防护） | `fetch_favicon` | ✅ |
| 安全中间件（Host/同源/cookie/无 CORS/防穿越） | `authorize_request` / `serve_static` | ✅ |
| 自动启动（autostart） | `ensure_autostart` | ✅ |
| 主题（深空蓝黑单主题） | `themes/ops.css` | ✅ |
| 健康检查 `/api/health`（不跑 ps/lsof） | 保留 | ✅ |

> 唯一语义差异：Windows 下 `terminate()` 等同于 `TerminateProcess`（硬性结束），
> 没有 POSIX 的优雅 SIGTERM 握手；对控制台子进程可后续扩展 `GenerateConsoleCtrlEvent`。

---

## 5. 搭建步骤

### 5.1 环境要求

- Windows 10 / 11
- Python **3.10 或更高**（推荐 3.12）。安装时务必勾选 **“Add Python to PATH”**。
- 联网一次（首次安装 `psutil` / `pillow`）。

### 5.2 安装依赖

```bat
cd local-ops-windows
python -m pip install -r requirements.txt
```

> 推荐使用虚拟环境（可选）：
> ```bat
> python -m venv venv
> venv\Scripts\activate
> pip install -r requirements.txt
> ```

### 5.3 首次运行

直接双击 `start.bat`，或命令行：

```bat
start.bat                  :: 启动并自动打开浏览器
start.bat --no-browser    :: 仅启动服务
start.bat --preferred-port 9603
start.bat --data-dir D:/local-ops-data
```

也可直接用 Python：

```bat
python server.py
python server.py --preferred-port 9603 --no-browser
```

启动成功后访问 **http://127.0.0.1:9600/**（端口被占用会自动回退到随机空闲端口，日志会打印实际地址）。

### 5.4 数据存放位置

默认在 `%LOCALAPPDATA%\local-ops\`，包含：

```
config.json      主配置（原子写）
config.json.bak  上一份良好配置（修改前自动备份）
server.lock      单实例锁
logs\<id>.log    各应用日志（自动轮转）
assets\          上传的图标
```

---

## 6. 运行与日常使用

1. **添加应用**：点右上「设置」→「+ 添加应用」，填名称 / 命令 / 工作目录 / 端口（可选）。
   例如：
   - 名称：`我的博客`；命令：`npm run dev`；目录：`D:\blog`；端口：`3000`
   - 名称：`API`；命令：`uvicorn main:app --port 8000`；目录：`D:\api`
2. **启动 / 停止 / 重启**：卡片上的按钮，或按 **Ctrl+K** 打开命令面板快速操作。
3. **看日志 / 诊断**：卡片「日志」按钮或 **Ctrl+J**，含实时日志尾部 + 诊断信息（进程、端口、项目识别）。
4. **选目录**：设置里「浏览…」会弹出逐级目录树（替代 macOS 的文件框）。
5. **开机自启（可选）**：把 `start.bat` 快捷方式放进
   `shell:startup`（`Win+R` 输入）即可。

---

## 7. 安全注意事项（重要）

原版 README 明确：**它不是多用户 / 远程管理面板，能以当前用户权限执行你保存的 shell 命令。**
本版继承这一边界并加固：

- **切勿**把 `9600`（或实际端口）通过反向代理 / 隧道 / 端口转发暴露到公网。
  本地回环（`127.0.0.1`）只是第一层边界；Host 头校验 + 同源 cookie 是第二层。
- 配置损坏进入**只读模式**时，界面会明确提示，不会用空配置覆盖尚可恢复的数据。
- 图标上传拒绝 SVG、限 5MB；favicon 抓取限制为 loopback 明文，防 SSRF。

---

## 8. 测试

建议的验证清单（可用 `unittest` 仿原版风格编写）：

- **进程安全**：启动应用 → 改其 PID 指向无关进程 → 确认 `detect_running` 返回未运行、停止不误杀。
- **端口回退**：占用 9600 后启动，确认自动换端口且日志打印。
- **配置保护**：手工写坏 `config.json` → 重启 → 确认进入只读且不覆盖。
- **安全中间件**：用 `curl` 伪造 `Host: evil.com` → 期望 421；跨源 `POST` 无 cookie → 期望 403；
  `OPTIONS` 预检 → 期望 403。
- **路径穿越**：`GET /static/../../server.py` → 期望 403/404。

本版已通过 `python -m py_compile server.py` 语法校验（零警告）。

---

## 9. 打包为 exe（可选，给非技术用户）

用 PyInstaller 把 `server.py` 打包成单文件 `local-ops.exe`，双击即跑（仍会拉起浏览器）：

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole --name local-ops server.py
```

产物在 `dist/local-ops.exe`。注意：打包后 `static/` 前端目录需用 `--add-data` 一并打入，
或在运行时从 `sys._MEIPASS` 读取资源（参考 PyInstaller 官方“运行时获取资源”做法）。

---

## 10. 已知限制与后续增强

**已知限制**
- 非管理员下端口发现可能不完整（仅影响“按端口识别外部已起进程”，不影响自管应用）。
- Windows 进程结束为硬性 `TerminateProcess`，无优雅退出握手（控制台应用可增强）。
- 前端目录浏览用 `prompt` 逐级选择，体验比原生文件框朴素（换取零 GUI 依赖、跨平台）。

**可增强方向（基于合理判断）**
- 用 `GenerateConsoleCtrlEvent` 对控制台子进程做优雅关闭。
- 把 `/api/browse` 升级为真正的图形化文件树组件（替换 `prompt`）。
- 增加 Windows 服务封装（`sc create` / `nssm`）实现真·开机后台运行。
- 端口发现改用 `Get-NetTCPConnection`（PowerShell）作为无管理员权限的兜底。
- 多主题：本版保留单 `ops` 主题（原版多主题已移除），可重新加回。

---

> 本指南配套的可运行代码已在 `local-ops-windows/` 落地。直接 `start.bat` 即可体验，
> 功能与原 macOS 版对等，且全部为 Windows 原生实现。
