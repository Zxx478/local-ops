# local-ops 后端架构与代码审查报告

> 审查对象：`D:\local_ops\backend`（FastAPI 本地服务/进程总控台，Windows）
> 审查方式：静态审查 + 真实运行验证（启动 uvicorn + 端到端冒烟 + 运行时句柄检查）
> 审查日期：2026-08-13
> 配套专家：python-backend-reviewer（注：该 skill 引用的 `scripts/*.py` 分析脚本在本机不存在，本次为人工等效分析）

---

## 一、执行摘要

| 维度 | 结论 |
|---|---|
| 编译 | ✅ 8 个模块 `py_compile` 全部通过，无语法/编译错误 |
| 启动与运行 | ✅ 真实服务可启动，端口回退正常，前端同源托管 OK |
| 端到端冒烟 | ✅ **20/20** 通过（health/state/browse/安全中间件/增删改查/启动停止/日志/诊断/图标上传/设置/ConfigManager 单元测试） |
| 资源泄漏 | ✅ 经运行时验证，**未发现**日志文件句柄泄漏（CPython 引用计数在 `launch()` 返回即关闭句柄） |
| 架构设计 | ✅ 模块划分清晰、职责单一，安全边界设计到位（多数项） |
| 需修复缺陷 | 🔴 2 项 → **已于 2026-08-13 全部修复（H1/H2）** |
| 建议修复 | 🟡 4 项 → **M1/M2/M3 已于 2026-08-13 修复；M4（端口探测竞态）待修复** |
| 锦上添花 | 🟢 8 项（代码气味、文档不一致、缺提交测试等，待处理） |

**总体评价**：代码质量高于一般 AI 生成后端，安全中间件、原子写+备份+只读、TTL 缓存、进程三重校验、SVG 拒绝+重编码、favicon SSRF 防护、单实例锁等设计扎实。主要风险集中在**并发启停的逻辑完整性**与**只读接口的身份校验覆盖度**两处。

---

## 二、架构与接口设计评价

**结构（清晰，符合单一职责）**
- `app.py` 应用工厂 + 路由 + 中间件注册 + 静态托管
- `config.py` 配置原子写/备份/迁移/只读
- `processes.py` 进程生命周期（启动/停止/重启/校验/日志）
- `state.py` 状态快照聚合 + TTL 缓存
- `security.py` ASGI 安全中间件
- `files.py` 目录浏览/图标/favicon/自启
- `models.py` Pydantic 入参校验
- `run.py` 启动入口（参数/单实例锁/端口回退）

**数据流转（合理）**
前端每 ~2.2s 轮询 `/api/state` → `state.get_state` 命中 2s TTL 缓存（避免每次 `psutil` 全量枚举）；任何写/启停操作调用 `invalidate()` 立即使缓存失效。进程运行态持久化于 `runtime.json`，服务重启经 `_verify_at_startup()` 重新校验。单进程 + 异步事件循环 + 线程池卸载阻塞调用，模型自洽。

**接口契约（与前端对齐）**
逐接口核对 `frontend/js/api.js`，增删改查/启动停止/日志/诊断/浏览/图标/设置/health 全部对齐，无断点。

**安全边界（大部分到位）**
- 仅绑 `127.0.0.1`；Host 非回环 → **421** 且不发 cookie ✅（已验证）
- 写操作强制同源会话 Cookie（HttpOnly/SameSite=Strict）+ `Sec-Fetch-Site: same-origin` → 否则 **403** ✅（已验证）
- 无 CORS：`OPTIONS` 预检 → **403**，绝不返回 `Access-Control-Allow-Origin` ✅（已验证）
- 安全响应头齐全（CSP/X-Frame-Options/nosniff/Referrer-Policy/CORP/COP）✅
- 图标拒 SVG + magic-byte + Pillow 重编码剥离脚本 ✅（已验证 PNG 落盘、SVG 拒绝）
- favicon 仅限回环明文 http、禁重定向、限大小 ✅

---

## 三、发现的问题（按严重级别）

### 🔴 高优先级（建议立即修复）

#### H1. 已运行应用再次调用 `start` 会"孤儿"前一个进程
- **位置**：`processes.py` `launch()`（L221-255）、`app.py` `start_app`（L100-110）
- **描述**：`launch()` 无条件 `self.runtime[app_id] = rt` 覆盖运行态。若该应用已在运行（例如前端按钮未禁用、或 API 直接调用），旧进程不会被终止，但其 PID 被新 PID 覆盖，控制面板从此**失去对旧进程的追踪**，无法再停止它。
- **影响**：僵尸进程残留、端口/资源泄漏、运行态与真实进程不一致。
- **运行时验证**：逻辑确认（未在冒烟中触发，因前端正常会禁用）。
- **修复建议**：`start_app` 前检查 `pm.is_running(app_id)`，若运行中则返回 `409 Conflict` 或自动改走 `restart`；或 `launch()` 内先 `stop` 旧实例再启新实例。

#### H2. 写接口异常未兜底，可能返回 500 并泄露堆栈
- **位置**：`app.py` `start_app`（L106-108）、`restart_app`（L125-128）
- **描述**：这两处仅 `except RuntimeError`，但 `pm.launch()` 还可能抛 `OSError`/`FileNotFoundError`（解释器缺失）、`subprocess` 错误、`ValueError` 等，均会穿透为未处理 500，且 FastAPI 默认返回含堆栈的 500 响应（信息泄露）。
- **影响**：健壮性与安全性（堆栈泄露内部路径）。
- **修复建议**：捕获 `Exception` 统一映射为 `400/500` 的 JSON 错误体；建议加全局 `Exception` 处理器（`@app.exception_handler`）兜底，避免任何未捕获异常泄露细节。

### 🟡 中优先级（建议修复）

#### M1. 只读接口（GET）无身份认证
- **位置**：`security.py` L94（仅 `POST/PUT/DELETE/PATCH` 要求 cookie）、`app.py` 的 `state`/`logs`/`diagnostics`/`browse`/`favicon` 路由
- **描述**：所有读取接口不需要会话 Cookie。已验证 `/api/browse` 在未带 Cookie 时返回 **200**（可枚举全盘目录），`/api/state`、`/api/apps/:id/logs` 同样无认证。
- **影响**：本地恶意网页（同机另一个回环源）或本地进程可读取：全部应用命令/cwd/端口（可能含密钥）、实时日志（可能含令牌）、以及全盘文件系统浏览。当前靠"仅绑回环 + 无 CORS + Host 校验"构成信任边界，属于本地威胁模型下的**纵深防御不足**。
- **修复建议**：对 `/api/state`、`/api/apps/:id/logs`、`/api/apps/:id/diagnostics`、`/api/browse` 也校验 `Sec-Fetch-Site: same-origin`（至少），敏感接口（logs/browse）进一步要求会话 Cookie。

#### M2. 进程三重校验中 token 校验为 best-effort，且用户归属检查为死代码
- **位置**：`processes.py` `_alive()`（L165-194），尤其 L179-183、L184-191
- **描述**：
  1. 若 `p.environ()` 抛出 `psutil.AccessDenied`（子进程以其他用户/权限运行），代码 `except ...: pass` **静默退化为仅 PID 存活 + create_time 判定**，最强的 token 校验被跳过。
  2. L179-183 计算 `owner` 后仅 `pass`，用户归属"软校验"实际未生效（死代码）。
- **影响**：`tripleVerified: true` 的标签可能高估了校验强度；极端情况下 PID 复用 + create_time 匹配（1s 窗口）可被误判为受管应用。
- **修复建议**：保留 token 校验失败时的明确日志；移除或真正实现用户归属逻辑；文档中注明 token 校验在权限不足时为 best-effort。

#### M3. favicon 响应未限制媒体类型，可能回源 SVG
- **位置**：`files.py` `fetch_favicon()`（L96-125）、`app.py` `favicon`（L206-214）
- **描述**：`fetch_favicon` 仅校验 `Content-Type` 以 `image/` 开头即返回，并以**上游原始 Content-Type** 回传（`media_type=ctype`）。若回环服务返回 `image/svg+xml`，后端会以同源 SVG 形式提供。虽以 `<img>` 加载时 SVG 脚本不执行，但作为同源资源存在被当作文档/对象嵌入而执行脚本的理论风险。
- **影响**：同源 SVG XSS 的理论风险（纵深防御）。
- **修复建议**：仅允许位图类型（`image/png|jpeg|gif|webp|x-icon`），显式拒绝 `svg`/`xml`。

#### M4. 端口探测与绑定存在 TOCTOU 竞态
- **位置**：`run.py` `find_free_port()`（L20-34）
- **描述**：`find_free_port` 探测到空闲端口后关闭 socket，`uvicorn.run` 再绑定——二者之间存在时间窗，另一进程可能抢占该端口导致启动失败。
- **影响**：极低概率启动失败（错误信息不够明确）。
- **修复建议**：让 uvicorn 直接绑定 preferred 端口并在失败时回退/报错；或探测后保持 socket 打开传给 uvicorn。

### 🟢 低优先级（锦上添花 / 文档一致性）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| L1 | `files.py` L85 | `save_icon` 用 `__import__("io").BytesIO()` hack | 改为顶部 `from io import BytesIO` |
| L2 | `processes.py` L179-183 | 用户归属检查为死代码（计算后 `pass`） | 实现或删除 |
| L3 | 仓库根 | OVERVIEW 声称"20/20 通过"但**无提交测试文件** | 已生成 `backend/smoke_test.py`，建议纳入 `tests/` 并提交 |
| L4 | `README_WINDOWS.md` | 称依赖"仅 psutil + pillow"，实际还需 `python-multipart`（UploadFile） | `requirements.txt` 正确，修正 README |
| L5 | OVERVIEW/README | 称"静态资源 realpath 前缀校验防穿越"，实际依赖 Starlette `StaticFiles` 内建 `..` 拒绝 | 文档改为"依赖框架内建防穿越" |
| L6 | `state.py` `get_state` | 检查-重建-写入存在轻微竞态（冗余重建，非错误） | 影响可忽略，仅多一次重建 |
| L7 | python-backend-reviewer skill | `SKILL.md` 引用的 `scripts/*.py` 分析脚本本机不存在 | 无法自动跑脚本，本次为人工等效分析；建议补齐脚本或更新文档 |
| L8 | `run.py` `find_free_port` | 异常分支 socket 关闭逻辑可读性一般 | 收敛为单一 try/finally |

---

## 四、测试与运行验证结论

**编译**：`python -m py_compile app.py config.py models.py security.py state.py processes.py files.py run.py` → 全部通过。

**端到端冒烟（`backend/smoke_test.py`，真实 uvicorn 进程）结果 20/20**：
- 服务启动 / health / state（下发 Cookie）
- Host 非回环 → 421 ✅
- OPTIONS 预检 → 403 ✅
- 无 Cookie 写 → 403 ✅
- 创建应用 → 200；state 含新应用 ✅
- 启动 → running=True；日志接口 200；诊断 running=True 且 tripleVerified=True ✅
- 停止 → running=False ✅
- 图标上传 PNG → 200 落盘 ✅；SVG → 400 拒绝 ✅
- 删除应用 → 200 ✅
- settings GET/POST ✅
- browse（无认证）200 ✅（同时暴露 M1 风险点）
- favicon loopback 探测 ✅
- ConfigManager 单元：原子写/备份存在/迁移补字段/损坏进入只读 ✅

**运行时资源检查（直接调用 `ProcessManager.launch()`）**：
- `LOG_EXISTS=True`，`CURRENT_PROC_OPEN_LOG_HANDLES=[]` → **无父进程文件句柄泄漏**（CPython 引用计数在 `launch()` 返回即关闭局部 `logf`）。原怀疑的"日志句柄泄漏"不成立，降为代码风格建议（传 fd + 显式 `close` 以利 PyPy/可移植性）。

---

## 五、后续行动建议（优先级排序）

1. **修复 H1**：`start_app` 前置 `is_running` 检查（409 或自动 restart）。
2. **修复 H2**：`start/restart` 路由加 `except Exception` 兜底 + 全局异常处理器。
3. **修复 M1**：对 `state/logs/diagnostics/browse` 增加 `Sec-Fetch-Site: same-origin` 校验（敏感项加 Cookie）。
4. **修复 M2**：清理 `_alive` 死代码，明确 token best-effort 语义与日志。
5. **修复 M3**：favicon 仅允许位图类型。
6. **提交测试**：将 `smoke_test.py` 纳入仓库（建议 `backend/tests/`），README 测试章节引用。
7. **文档修正**：L4/L5 一致性；L7 补齐 reviewer skill 脚本或更新说明。

> 注：以上均未做破坏性改动，仅报告发现。如需我直接实施 H1/H2/M1 的修复补丁，可继续指示。

---

## 六、修复记录（2026-08-13 实施 H1/H2/M1/M2/M3）

用户要求直接实施 H1/H2/M1/M2/M3 补丁，已全部落地并通过回归验证（冒烟 **25/25 通过**）。

### H1 修复 — 重复启动不再孤儿进程
- **改动**：`processes.py::launch()` 在启动新进程前，先对同 `app_id` 的既有运行态执行 `kill_tree(prev_pid)` 并移除旧 `runtime` 记录，再覆盖写入新运行态。
- **效果**：已运行应用再次 `start` 时，旧进程树被终止，`runtime.json` 不会残留失联 PID。单元验证（`h1_m3_unit`）确认重复启动后旧 PID 已退出、仅存在新 PID。

### H2 修复 — 写接口异常兜底
- **改动**：`app.py::start_app` / `restart_app` 的 `except RuntimeError` 放宽为 `except Exception`，返回 `400 {"error": "启动失败：…"}` / `重启失败：…`，避免非 `RuntimeError`（如解释器缺失导致的 `OSError`/`FileNotFoundError`、子进程异常）穿透为 500 并泄露堆栈。

### M1 修复 — 只读接口强制会话认证（纵深防御）
- **改动**：`security.py` 新增 `_is_read_protected()`，对 `/api/state`、`/api/browse`、`/api/apps/{id}/logs`、`/api/apps/{id}/diagnostics` 与写操作同样要求有效会话 Cookie（`lo_sid`）+ 同源（`Sec-Fetch-Site: same-origin` 或回环 Origin），否则 403。
- **兼容性**：前端为同源 SPA，浏览器自动携带 Cookie 且 `Sec-Fetch-Site: same-origin`，正常访问不受影响；仅绑 127.0.0.1 + Cookie `SameSite=Strict` 使跨站请求本就不带 Cookie。冒烟中 `m1_*_noauth_403` 四项均确认 403，认证后读接口正常 200。

### M2 修复 — 三重校验语义显式化 + 归属死代码清理
- **改动**：`processes.py` 抽出 `_check_token(pid, token) -> True|False|None`（None=无权限读环境，退化为存活判定）；`_alive()` 仅当 token 确认不匹配才判否，并移除原"用户归属"死代码（仅 `pass`），改在运行态记录 `_owner_mismatch` 软提示。新增 `token_verified(app_id)` / `owner_mismatch(app_id)` 方法；`app.py::app_diag` 的 `tripleVerified` 改为如实上报 `pm.token_verified(...)`（token 未能确认时不再谎报 `True`），并新增 `ownerMismatch` 字段。

### M3 修复 — favicon 仅允许安全位图类型
- **改动**：`files.py::fetch_favicon` 增加 `_SAFE_FAVICON_TYPES` 白名单（png/jpeg/gif/webp/ico），拒绝 `image/svg+xml` 等可脚本化类型；并二次 magic-byte 嗅探（`_sniff`），Content-Type 可伪造时仍以实际字节为准拒绝 SVG/XML。`app.py::favicon` 增加防御性拦截（SVG/XML/HTML 回显 → 502）。
- **效果**：单元验证（`h1_m3_unit`）确认合法 PNG 被接受、SVG 被拒绝（返回 `None`）。

### 验证方式
- 更新 `smoke_test.py`：只读接口改走认证请求；新增 M1 未认证 403 断言、H1 重复启动无孤儿单元、M3 favicon SVG 拒绝单元。
- 运行结果：`COMPILE OK` + 冒烟 **25/25 通过**（含 H1/H2/M1/M2/M3 相关断言）。

### 未在本轮处理（用户未要求）
- M4 端口探测 TOCTOU 竞态（`run.py`）：`find_free_port` 与 uvicorn 绑定之间存在抢占窗口，建议后续用 `import socket` 预绑或 `SO_REUSEADDR` 规避。
- 🟢 低优先级 8 项。

