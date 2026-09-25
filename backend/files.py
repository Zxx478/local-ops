"""文件相关：目录浏览、图标上传、favicon SSRF 防护、开机自启。

安全边界：
- 图标上传：magic-byte 嗅探，显式拒绝 SVG（防 SVG XSS），限制 5MB，
  并用 Pillow 重编码为 PNG（剥离元数据/脚本）。
- favicon 抓取：仅允许回环明文 http URL，禁重定向、限大小，防 SSRF。
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from io import BytesIO
from typing import Optional

from PIL import Image

ICON_MAX_BYTES = 5 * 1024 * 1024
ICON_DIRNAME = "assets"

# favicon 仅允许的安全光栅类型（显式排除 SVG/XML，防 SVG XSS）
_SAFE_FAVICON_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "image/x-icon", "image/vnd.microsoft.icon",
}
_ICO_TYPES = ("image/x-icon", "image/vnd.microsoft.icon")

# magic-byte 签名（前若干字节）
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"RIFF", "webp"),  # 形如 RIFF....WEBP，进一步校验
]


def _sniff(data: bytes) -> Optional[str]:
    for sig, ext in _MAGIC:
        if data[: len(sig)] == sig:
            if ext == "webp":
                return "webp" if data[8:12] == b"WEBP" else None
            return ext
    return None


def browse_dir(base: str) -> dict:
    """返回 {path, parent, dirs, files}。"""
    if not base or not os.path.isdir(base):
        # 回退到首个可读盘符
        for d in ("C:\\", "D:\\", "E:\\"):
            if os.path.isdir(d):
                base = d
                break
        else:
            base = os.path.abspath(os.sep)
    base = os.path.realpath(base)
    entries = []
    try:
        entries = sorted(os.listdir(base))
    except (PermissionError, OSError):
        entries = []
    dirs, files = [], []
    for e in entries:
        full = os.path.join(base, e)
        try:
            if os.path.isdir(full):
                dirs.append(e)
            else:
                files.append(e)
        except OSError:
            continue
    # 盘符根目录无上级
    is_drive_root = len(os.path.splitdrive(base)[1]) <= 1
    parent = "" if is_drive_root else os.path.dirname(base)
    return {"path": base, "parent": parent, "dirs": dirs, "files": files}


def save_icon(data_dir: str, app_id: str, filename: str, content: bytes) -> str:
    """校验并保存图标，返回可访问 URL（/assets/<id>.png）。"""
    if len(content) > ICON_MAX_BYTES:
        raise ValueError("图标超过 5MB 限制")
    # 拒绝 SVG（文本特征）
    head = content[:512].lstrip()
    if head[:5].lower() in (b"<?xml", b"<svg ") or b"<svg" in content[:200].lower():
        raise ValueError("不支持 SVG 图标（安全限制）")
    ext = _sniff(content)
    if not ext:
        raise ValueError("不支持的图片格式")
    # 用 Pillow 重编码为 PNG（剥离脚本/元数据，防嵌套载荷）
    try:
        img = Image.open(BytesIO(content))
        img = img.convert("RGBA")
    except Exception:
        raise ValueError("图片解码失败")
    assets_dir = os.path.join(data_dir, ICON_DIRNAME)
    os.makedirs(assets_dir, exist_ok=True)
    out_path = os.path.join(assets_dir, app_id + ".png")
    img.save(out_path, "PNG")
    return f"/{ICON_DIRNAME}/{app_id}.png"


def fetch_favicon(url: str, timeout: float = 3.0, max_bytes: int = 256 * 1024) -> Optional[tuple[bytes, str]]:
    """SSRF 防护的 favicon 抓取：仅回环明文 http，禁重定向、限大小。"""
    from urllib.parse import urlparse

    try:
        p = urlparse(url)
    except Exception:
        return None
    if p.scheme != "http":
        return None
    host = (p.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "local-ops"})
        # 禁止跟随重定向，避免跳转到外部
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            # M3: 仅允许安全光栅类型，拒绝 SVG/XML 等可脚本化载体
            if ctype not in _SAFE_FAVICON_TYPES:
                return None
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            # 二次 magic-byte 嗅探：Content-Type 可被伪造，必须确认实际为光栅图
            ext = _sniff(data)
            if ctype in _ICO_TYPES:
                safe_ctype = "image/x-icon"  # .ico 不在 _MAGIC 中，按类型放行
            elif ext is None:
                return None  # 嗅探不到已知光栅格式（可能是 SVG/XML 伪装）→ 拒绝
            else:
                safe_ctype = {
                    "png": "image/png", "jpg": "image/jpeg",
                    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
                }.get(ext, ctype)
            return data, safe_ctype
    except Exception:
        return None


def ensure_autostart(enabled: bool, target_bat: str) -> bool:
    """在 shell:startup 创建/移除开机自启快捷方式（Windows）。"""
    try:
        import winshell  # 可选，若不可用则降级用 PowerShell
    except ImportError:
        winshell = None
    startup = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )
    if not os.path.isdir(startup):
        return False
    lnk = os.path.join(startup, "local-ops.lnk")
    if not enabled:
        if os.path.exists(lnk):
            try:
                os.remove(lnk)
            except OSError:
                pass
        return True
    if winshell:
        try:
            with winshell.shortcut(lnk) as s:
                s.path = target_bat
                s.description = "local-ops 控制面板"
            return True
        except Exception:
            pass
    # 降级：PowerShell 创建快捷方式
    ps = (
        f'$ws=New-Object -ComObject WScript.Shell;'
        f'$s=$ws.CreateShortcut(\"{lnk}\");'
        f'$s.TargetPath=\"{target_bat}\";'
        f'$s.Description=\"local-ops 控制面板\";'
        f'$s.Save()'
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, check=False, timeout=20)
        return os.path.exists(lnk)
    except Exception:
        return False
