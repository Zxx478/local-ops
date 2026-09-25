"""启动入口：参数解析、单实例锁、端口回退、运行 uvicorn。

高并发说明：默认单 worker（1 个事件循环进程）。进程管理共享内存状态，
多进程会导致运行态不一致；单进程 + 异步事件循环 + 线程池卸载阻塞的
psutil 调用，即可支撑大量并发 HTTP 连接（控制面板场景足够）。如需更高
吞吐，可在反向代理后多实例部署并把 state runtime 改为外部存储。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

DEFAULT_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "local-ops"
)


def find_free_port(preferred: int) -> int:
    """优先绑定 preferred，被占用则回退随机空闲端口。"""
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("无法绑定任何回环端口")


def acquire_instance_lock(data_dir: str):
    """单实例锁：Windows 用 msvcrt.locking，其他平台用 fcntl.flock。返回锁文件句柄。"""
    os.makedirs(data_dir, exist_ok=True)
    lock_path = os.path.join(data_dir, "server.lock")
    f = open(lock_path, "w")
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("[local-ops] 已有实例在运行（server.lock 被占用）。", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("[local-ops] 已有实例在运行（server.lock 被占用）。", file=sys.stderr)
            sys.exit(1)
    return f  # 保持打开以持有锁


def main() -> None:
    parser = argparse.ArgumentParser(description="local-ops backend")
    parser.add_argument("--preferred-port", type=int, default=9600)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    data_dir = os.path.abspath(os.path.expanduser(args.data_dir))
    lock = acquire_instance_lock(data_dir)
    port = find_free_port(args.preferred_port)

    from app import create_app
    app = create_app(data_dir, port=port, open_browser=not args.no_browser)

    print(f"[local-ops] 数据目录：{data_dir}")
    print(f"[local-ops] 监听：http://{args.host}:{port}/")

    import uvicorn
    uvicorn.run(app, host=args.host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
