#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local-ops 前端静态服务器（带缓存策略）。

用法：
    python serve.py [port]
默认端口 8080。仅用于本地预览；生产环境请由后端 server.py 托管 frontend/
并复用其安全中间件（Host 校验、同源 Cookie、无 CORS）。

缓存策略（按扩展名）：
    .html        → no-cache            （始终重新校验，部署后立即生效）
    .js/.css/.svg/.json/.ico/.woff2
                 → public, max-age=86400, immutable
                                      （内容不变则浏览器不再发起请求/协商）
说明：本项目为「零构建」原生 ES Module，未做内容哈希指纹，故静态资源采用
1 天长缓存 + immutable；更新后只要重新部署（覆盖文件）并刷新一次 HTML 即可
拉取最新资源。若日后引入构建与文件名哈希，可整体改为永久缓存。
"""
import http.server
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROOT = os.path.dirname(os.path.abspath(__file__))

IMMUTABLE = (".js", ".css", ".svg", ".json", ".ico", ".woff2")
NO_CACHE = (".html",)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        ext = os.path.splitext(self.path.split("?")[0])[1].lower()
        if ext in IMMUTABLE:
            self.send_header("Cache-Control", "public, max-age=86400, immutable")
        else:
            # 根路径 / 与 .html 等默认 no-cache，部署后立即生效
            self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"local-ops 前端预览：http://127.0.0.1:{PORT}/  (Ctrl+C 退出)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
