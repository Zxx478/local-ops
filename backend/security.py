"""安全中间件（ASGI）：本地浏览器信任边界。

- 仅接受回环 Host（DNS 重绑定防护），否则 421 且不发 cookie
- 无 CORS：OPTIONS 预检直接 403，绝不返回 Access-Control-Allow-Origin
- 写操作（POST/PUT/DELETE/PATCH）要求同源会话 Cookie + Sec-Fetch-Site: same-origin
- 齐全安全响应头：CSP / X-Frame-Options / nosniff / Referrer-Policy / CORP / COP
"""
from __future__ import annotations

import urllib.parse

COOKIE_NAME = "lo_sid"

SECURITY_HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
     b"script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
]


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> Optional[str]:
    low = name.lower()
    for k, v in headers:
        if k.lower() == low:
            return v.decode("latin1")
    return None


def _parse_cookies(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    raw = _header(headers, b"cookie")
    if not raw:
        return out
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _is_loopback_host(host: str) -> bool:
    host = (host or "").split(":")[0].lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "[::1]")


def _is_loopback_origin(origin: str) -> bool:
    try:
        p = urllib.parse.urlparse(origin)
        return _is_loopback_host(p.hostname or "") and p.scheme in ("http", "https")
    except Exception:
        return False


# M1: 纵深防御——这些只读接口同样要求有效会话，未带 Cookie 不可枚举
# 全盘目录 / 命令 / 日志 / 诊断信息（防本地其他进程或同机页面越权读取）。
_READ_PROTECTED = ("/api/state", "/api/browse")


def _is_read_protected(path: str) -> bool:
    if path in _READ_PROTECTED:
        return True
    # /api/apps/<id>/logs 与 /api/apps/<id>/diagnostics
    if path.startswith("/api/apps/") and (path.endswith("/logs") or path.endswith("/diagnostics")):
        return True
    return False


async def _send_json(send, status: int, payload: bytes) -> None:
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})


class SecurityMiddleware:
    def __init__(self, app, session_token: str):
        self.app = app
        self.token = session_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        host = _header(headers, b"host") or ""
        method = scope["method"]
        path = scope.get("path", "")

        if not _is_loopback_host(host):
            await _send_json(send, 421, b'{"error":"invalid_host"}')
            return

        if method == "OPTIONS":
            # 明确无 CORS：预检一律拒绝
            await _send_json(send, 403, b'{"error":"cors_disabled"}')
            return

        # 写操作 + M1 受保护只读接口：均需有效会话 Cookie + 同源
        if method in ("POST", "PUT", "DELETE", "PATCH") or _is_read_protected(path):
            cookies = _parse_cookies(headers)
            sid = cookies.get(COOKIE_NAME)
            sfs = _header(headers, b"sec-fetch-site")
            origin = _header(headers, b"origin") or ""
            same_origin = (sfs == "same-origin") or (origin and _is_loopback_origin(origin))
            if sid != self.token or not same_origin:
                await _send_json(send, 403, b'{"error":"forbidden"}')
                return

        cookie = f"{COOKIE_NAME}={self.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400".encode()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                hdrs.extend(SECURITY_HEADERS)
                # 仅在未设置同名 cookie 时下发，减少冗余
                has_cookie = any(k.lower() == b"set-cookie" for k, _ in hdrs)
                if not has_cookie:
                    hdrs.append((b"set-cookie", cookie))
                message["headers"] = hdrs
            await send(message)

        await self.app(scope, receive, send_wrapper)
