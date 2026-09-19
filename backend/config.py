"""配置管理：原子写 + 修改前备份 + 字段迁移 + 只读保护。

config.json 结构：
{
  "version": 2,
  "settings": {
    "theme": "ops", "pollInterval": 2200, "autostart": false
  },
  "apps": [ {id, name, command, cwd, port, type, icon} ]
}
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from typing import Optional

CONFIG_VERSION = 2
DEFAULT_SETTINGS = {
    "theme": "ops",
    "pollInterval": 2200,
    "autostart": False,
}


def _slug(name: str) -> str:
    # 仅保留 ASCII 字母数字与连字符，便于 URL 与前端 encodeURIComponent
    s = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "-" for c in name.strip().lower())
    s = "-".join(filter(None, s.split("-")))
    return s or "app"


class ConfigManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.config_path = os.path.join(data_dir, "config.json")
        self.backup_path = os.path.join(data_dir, "config.json.bak")
        self.lock = threading.RLock()
        self.readonly = False
        self.readonly_reason = ""
        self.apps: dict[str, dict] = {}
        self.settings: dict = dict(DEFAULT_SETTINGS)
        os.makedirs(data_dir, exist_ok=True)
        self.load()

    # ---------- 读取 ----------
    def load(self) -> None:
        with self.lock:
            raw = self._read_safe()
            if raw is None:
                # 主配置损坏：尝试上一份良好备份
                self.readonly = True
                self.readonly_reason = "config.json 损坏"
                if os.path.exists(self.backup_path):
                    try:
                        with open(self.backup_path, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        self.readonly = False
                        self.readonly_reason = ""
                    except Exception:
                        raw = None
                if raw is None:
                    # 备份也不可用 → 进入只读，但不清空（避免覆盖尚可恢复的数据）
                    self.apps = {}
                    return
            self._parse(raw)

    def _read_safe(self) -> Optional[dict]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"version": CONFIG_VERSION, "apps": [], "settings": {}}
        except (json.JSONDecodeError, OSError):
            return None

    def _parse(self, raw: dict) -> None:
        # 迁移：补默认字段
        if not isinstance(raw, dict):
            raw = {}
        s = raw.get("settings") or {}
        if not isinstance(s, dict):
            s = {}
        self.settings = {**DEFAULT_SETTINGS, **s}
        apps = raw.get("apps") or []
        self.apps = {}
        for a in apps:
            if not isinstance(a, dict) or not a.get("id") or not a.get("name"):
                continue
            self.apps[a["id"]] = {
                "id": a["id"],
                "name": a["name"],
                "command": a.get("command", ""),
                "cwd": a.get("cwd", ""),
                "port": a.get("port"),
                "type": a.get("type", "service"),
                "icon": a.get("icon"),
            }

    # ---------- 写入 ----------
    def _atomic_save(self) -> None:
        """原子写：先写临时文件再 os.replace；写前自动备份当前良好配置。"""
        payload = {
            "version": CONFIG_VERSION,
            "settings": self.settings,
            "apps": list(self.apps.values()),
        }
        tmp = self.config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # 备份当前（若存在且合法）为 .bak
        if os.path.exists(self.config_path):
            try:
                shutil.copy2(self.config_path, self.backup_path)
            except OSError:
                pass
        os.replace(tmp, self.config_path)

    # ---------- 查询 ----------
    def list_apps(self) -> list[dict]:
        return list(self.apps.values())

    def get_app(self, app_id: str) -> Optional[dict]:
        return self.apps.get(app_id)

    # ---------- 变更 ----------
    def add_app(self, data: dict) -> str:
        if self.readonly:
            raise RuntimeError("配置处于只读模式，无法修改：" + self.readonly_reason)
        name = data["name"]
        app_id = data.get("id") or (_slug(name) + "-" + os.urandom(3).hex())
        # 避免 ID 冲突
        while app_id in self.apps:
            app_id = _slug(name) + "-" + os.urandom(3).hex()
        self.apps[app_id] = {
            "id": app_id,
            "name": name,
            "command": data["command"],
            "cwd": data.get("cwd", "") or "",
            "port": data.get("port"),
                "type": data.get("type", "service"),
                "icon": data.get("icon"),
            }
        self._atomic_save()
        return app_id

    def update_app(self, app_id: str, data: dict) -> bool:
        if self.readonly:
            raise RuntimeError("配置处于只读模式，无法修改：" + self.readonly_reason)
        app = self.apps.get(app_id)
        if not app:
            return False
        for k in ("name", "command", "cwd", "port", "type"):
            if k in data and data[k] is not None:
                app[k] = data[k]
        if "icon" in data:
            app["icon"] = data["icon"]
        self._atomic_save()
        return True

    def delete_app(self, app_id: str) -> bool:
        if self.readonly:
            raise RuntimeError("配置处于只读模式，无法修改：" + self.readonly_reason)
        if app_id not in self.apps:
            return False
        del self.apps[app_id]
        self._atomic_save()
        return True

    def get_settings(self) -> dict:
        return dict(self.settings)

    def save_settings(self, data: dict) -> None:
        if self.readonly:
            raise RuntimeError("配置处于只读模式，无法修改：" + self.readonly_reason)
        self.settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        self._atomic_save()

    def set_icon(self, app_id: str, icon_url: Optional[str]) -> None:
        app = self.apps.get(app_id)
        if app:
            app["icon"] = icon_url
            if not self.readonly:
                self._atomic_save()
