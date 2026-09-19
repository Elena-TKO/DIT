"""Схемы входных данных API (pydantic). Ответы — словари сервисного слоя."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class ProjectIn(BaseModel):
    name: str
    address: str = ""
    start_date: str
    end_date: str


class ProjectPatch(BaseModel):
    name: str | None = None
    address: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class BuildingIn(BaseModel):
    name: str
    object_type: str
    start_date: str | None = None
    end_date: str | None = None


class BuildingPatch(BaseModel):
    name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    reschedule: bool = False


class TaskPatch(BaseModel):
    enabled: bool | None = None
    start_date: str | None = None
    end_date: str | None = None
    phase: str | None = None


class BulkToggleIn(BaseModel):
    task_ids: list[int] = Field(default_factory=list)
    enabled: bool = True


class DetectionIn(BaseModel):
    cls: str
    bbox: list[float]
    confidence: float = 1.0


class DetectionsIn(BaseModel):
    items: list[DetectionIn] = Field(default_factory=list)


class CameraIn(BaseModel):
    name: str
    source_type: str = "upload"
    zone: str = ""
    url: str = ""
    building_id: int | None = None
    interval_min: int = 30
    tick_seconds: int = 10
    active: bool = False
    emulator_start: str | None = None


class CameraPatch(BaseModel):
    name: str | None = None
    zone: str | None = None
    url: str | None = None
    building_id: int | None = None
    interval_min: int | None = None
    tick_seconds: int | None = None
    active: bool | None = None
    emulator_start: str | None = None


class EmulatorResetIn(BaseModel):
    start_at: str | None = None
    clear_frames: bool = False
