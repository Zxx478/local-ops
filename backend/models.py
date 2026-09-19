"""Pydantic 请求/响应模型（数据校验集中在边界）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AppIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    command: str = Field(..., min_length=1, max_length=2000)
    cwd: str = ""
    port: Optional[int] = Field(None, ge=1, le=65535)
    type: str = Field("service", pattern="^(service|batch)$")


class AppPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    command: Optional[str] = Field(None, min_length=1, max_length=2000)
    cwd: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    type: Optional[str] = Field(None, pattern="^(service|batch)$")


class SettingsIn(BaseModel):
    theme: str = "ops"
    pollInterval: int = Field(2200, ge=500, le=10000)
    autostart: bool = False
