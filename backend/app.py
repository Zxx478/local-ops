"""FastAPI 应用：API 路由 + 安全中间件 + 前端/资源静态托管。

前后端分离：后端全部代码在本目录；前端（D:/local_ops/frontend）由本服务同源托管，
既满足「前后端分离」的代码组织，又延续 README 的「本地同源信任边界」（无 CORS）。
"""
import os
import secrets
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from models import AppIn, AppPatch, SettingsIn
from config import ConfigManager
from processes import ProcessManager
from state import get_state, invalidate, listening_ports, describe_app
import files as files_mod
from security import SecurityMiddleware

_HERE = Path(__file__).resolve().parent
FRONTEND_DIR = (_HERE.parent / "frontend").resolve()
ROOT = _HERE.parent  # D:/local_ops
START_BAT = str(_HERE / "start.bat")


def create_app(data_dir: str, port: int, open_browser: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if open_browser:
            try:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            except Exception:
                pass
        yield

    app = FastAPI(title="local-ops", version="1.0.0", lifespan=lifespan)
    app.state.session_token = secrets.token_hex(32)
    app.state.port = port
    app.state.data_dir = data_dir

    config = ConfigManager(data_dir)
    pm = ProcessManager(data_dir, config)
    app.state.config = config
    app.state.pm = pm

    # 安全中间件（最外层，包裹全部请求含静态）
    app.add_middleware(SecurityMiddleware, session_token=app.state.session_token)

    router = APIRouter(prefix="/api")

    def _not_found(detail="未找到"):
        return JSONResponse(status_code=404, content={"error": detail})

    @router.get("/health")
    async def health():
        return {"ok": True}

    @router.get("/state")
    async def state():
        return get_state(config, pm)

    @router.post("/apps")
    async def apps_create(req: Request):
        try:
            payload = AppIn(**await req.json())
        except Exception as e:
            return JSONResponse(status_code=422, content={"error": "参数校验失败", "detail": str(e)})
        try:
            app_id = config.add_app(payload.model_dump())
        except RuntimeError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
        invalidate()
        return {"ok": True, "id": app_id}

    @router.put("/apps/{app_id}")
    async def update_app(app_id: str, req: Request):
        app = config.get_app(app_id)
        if not app:
            return _not_found()
        try:
            payload = AppPatch(**await req.json())
        except Exception as e:
            return JSONResponse(status_code=422, content={"error": "参数校验失败", "detail": str(e)})
        # 仅取非 None 字段
        patch = {k: v for k, v in payload.model_dump().items() if v is not None}
        try:
            config.update_app(app_id, patch)
        except RuntimeError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
        invalidate()
        return {"ok": True}

    @router.delete("/apps/{app_id}")
    async def delete_app(app_id: str):
        if not config.get_app(app_id):
            return _not_found()
        try:
            ok = config.delete_app(app_id)
        except RuntimeError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
        if ok:
            pm.stop(app_id)
        invalidate()
        return {"ok": True}

    @router.post("/apps/{app_id}/start")
    async def start_app(app_id: str):
        app = config.get_app(app_id)
        if not app:
            return _not_found()
        try:
            pm.launch(app)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": f"启动失败：{e}"})
        invalidate()
        return {"ok": True}

    @router.post("/apps/{app_id}/stop")
    async def stop_app(app_id: str):
        if not config.get_app(app_id):
            return _not_found()
        pm.stop(app_id)
        invalidate()
        return {"ok": True}

    @router.post("/apps/{app_id}/restart")
    async def restart_app(app_id: str):
        app = config.get_app(app_id)
        if not app:
            return _not_found()
        try:
            pm.restart(app)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": f"重启失败：{e}"})
        invalidate()
        return {"ok": True}

    @router.get("/apps/{app_id}/logs")
    async def app_logs(app_id: str, lines: int = 200):
        if not config.get_app(app_id):
            return _not_found()
        text = pm.read_log_tail(app_id, max(1, min(lines, 2000)))
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    @router.get("/apps/{app_id}/diagnostics")
    async def app_diag(app_id: str):
        app = config.get_app(app_id)
        if not app:
            return _not_found()
        rt = pm.get_runtime(app_id)
        # 与 /api/state 共用同一份快照构造逻辑，另附三重校验等诊断专有字段
        snap = describe_app(app, rt, pm, listening_ports())
        snap["tripleVerified"] = pm.token_verified(app_id) if rt else False
        snap["ownerMismatch"] = pm.owner_mismatch(app_id) if rt else False
        return snap

    @router.get("/browse")
    async def browse(path: str = ""):
        return files_mod.browse_dir(path)

    @router.post("/icon")
    async def upload_icon(appId: str = Form(...), file: UploadFile = File(...)):
        app = config.get_app(appId)
        if not app:
            return _not_found("应用不存在")
        content = await file.read()
        try:
            url = files_mod.save_icon(data_dir, appId, file.filename or "icon", content)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        config.set_icon(appId, url)
        invalidate()
        return {"ok": True, "icon": url}

    @router.get("/settings")
    async def get_settings():
        return config.get_settings()

    @router.post("/settings")
    async def save_settings(req: Request):
        try:
            payload = SettingsIn(**await req.json())
        except Exception as e:
            return JSONResponse(status_code=422, content={"error": "参数校验失败", "detail": str(e)})
        data = payload.model_dump()
        try:
            config.save_settings(data)
        except RuntimeError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
        # 开机自启
        files_mod.ensure_autostart(bool(data.get("autostart")), START_BAT)
        invalidate()
        return {"ok": True}

    @router.get("/favicon")
    async def favicon(url: str = ""):
        if not url:
            return JSONResponse(status_code=400, content={"error": "缺少 url"})
        res = files_mod.fetch_favicon(url)
        if not res:
            return JSONResponse(status_code=502, content={"error": "抓取失败（仅限回环明文 http）"})
        data, ctype = res
        # M3 防御：任何非安全光栅类型（含 SVG/XML）一律拒绝回显
        if ctype.split(";")[0].strip().lower() in (
            "image/svg+xml", "image/svg", "text/xml", "application/xml", "text/html",
        ):
            return JSONResponse(status_code=502, content={"error": "不支持的图标类型"})
        return Response(content=data, media_type=ctype)

    app.include_router(router)

    # 静态资源：上传图标（/assets -> data_dir/assets）
    assets_dir = os.path.join(data_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # 前端静态（同源托管，满足本地信任边界）
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app
