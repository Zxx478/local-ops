"""状态快照：聚合应用运行态 + KPI，带 TTL 缓存（与前端 2.2s 轮询对齐）。

高并发要点：
- psutil 枚举（进程/端口/CPU/内存）是主要开销，整体结果缓存 STATE_TTL 秒；
- 任何会改动运行态的操作（启/停/重启/配置变更）调用 invalidate() 立即使缓存失效，
  用户操作即时可见，普通轮询命中缓存零开销。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import psutil

from config import ConfigManager
from processes import ProcessManager, attribute_chain, detect_project

STATE_TTL = 2.0  # 秒

_cache: dict = {"ts": 0.0, "data": None}
_cache_lock = threading.Lock()


def invalidate() -> None:
    with _cache_lock:
        _cache["ts"] = 0.0


def listening_ports() -> dict[int, set[int]]:
    """端口 -> 监听 PID 集合（仅 TCP）。"""
    mapping: dict[int, set[int]] = {}
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == "LISTEN" and c.laddr and c.pid:
                mapping.setdefault(c.laddr.port, set()).add(c.pid)
    except (psutil.AccessDenied, OSError):
        pass
    return mapping


def _kpis(port_count: int) -> dict:
    try:
        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = 0
    try:
        mem = psutil.virtual_memory().percent
    except Exception:
        mem = 0
    return {"cpu": round(cpu), "mem": round(mem), "ports": port_count}


def describe_app(a: dict, rt: Optional[dict], pm: ProcessManager, port_map: dict[int, set[int]]) -> dict:
    """构造单个应用的运行快照（/api/state 与 /api/apps/:id/diagnostics 共用）。

    rt 为 None 表示未运行；端口归属 = 进程树实际监听端口 + 配置端口兜底展示。
    """
    running = rt is not None
    ports: list = []
    if running:
        pids = pm.owner_pids(a["id"])
        ports = sorted({p for p, pids_ in port_map.items() if pids_ & pids})
        # 配置端口兜底展示（仅在运行时）
        if a.get("port") and a["port"] not in ports:
            ports.append(a["port"])
            ports.sort()
    return {
        "id": a["id"],
        "name": a["name"],
        "command": a["command"],
        "cwd": a.get("cwd", ""),
        "port": a.get("port"),
        "type": a.get("type", "service"),
        "icon": a.get("icon"),
        "running": running,
        "pid": rt["pid"] if running else None,
        "startedAt": rt["started_at"] if running else None,
        "project": detect_project(a.get("cwd", "")),
        "owner": attribute_chain(rt["pid"]) if running else "—",
        "ports": ports,
    }


def build_state(config: ConfigManager, pm: ProcessManager) -> dict:
    apps_cfg = config.list_apps()
    port_map = listening_ports()

    apps = []
    running_count = 0
    for a in apps_cfg:
        # 用户自建应用：运行态来自 runtime.json（三重校验）
        rt = pm.get_runtime(a["id"])
        if rt is not None:
            running_count += 1
        apps.append(describe_app(a, rt, pm, port_map))

    return {
        "apps": apps,
        "kpis": _kpis(len(port_map)),
        "runningCount": running_count,
    }


def get_state(config: ConfigManager, pm: ProcessManager) -> dict:
    now = time.monotonic()
    with _cache_lock:
        if _cache["data"] is not None and (now - _cache["ts"]) < STATE_TTL:
            return _cache["data"]
    data = build_state(config, pm)
    with _cache_lock:
        _cache["ts"] = time.monotonic()
        _cache["data"] = data
    return data
