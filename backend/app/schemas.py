"""Схемы входных данных API (pydantic). Ответы — словари сервисного слоя."""
from __future__ import annotations

from typing import Annotated

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
    lat: float | None = None      # точка на карте, поставленная вручную
    lon: float | None = None


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
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]
    confidence: float = Field(1.0, ge=0, le=1)
    label_raw: str = ""
    manual: bool = True


class DetectionsIn(BaseModel):
    items: list[DetectionIn] = Field(default_factory=list)


class PhotoPatch(BaseModel):
    phase: str | None = None        # этап работ; пустая строка — вернуть автоопределение по технике


class CalcIn(BaseModel):
    kind: str                       # excavation | concreting | tower_crane
    params: dict = Field(default_factory=dict)


class AssistantIn(BaseModel):
    question: str
    project_id: int | None = None   # стройка, по которой отвечать (для вопроса о текущем этапе)


class CameraIn(BaseModel):
    name: str
    zone: str = ""
    building_id: int | None = None


class CameraPatch(BaseModel):
    name: str | None = None
    zone: str | None = None
    building_id: int | None = None