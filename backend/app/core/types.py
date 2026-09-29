"""Структуры данных, общие для модулей анализа (без зависимостей от БД и веб-фреймворка)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class Detection:
    cls: str                                   # класс техники из методики, напр. "excavator"
    confidence: float
    bbox: tuple[float, float, float, float]    # x1, y1, x2, y2 в долях кадра (0..1)
    label_raw: str = ""                        # исходная метка модели
    id: int | None = None
    activity: str = "unknown"                  # working | idle | unknown
    idle_minutes: int = 0


@dataclass
class PhotoObs:
    id: int
    taken_at: dt.datetime
    camera_id: int | None = None
    camera_name: str = ""
    zone: str = ""
    detections: list[Detection] = field(default_factory=list)
    phase: str | None = None                   # этап, к которому относится снимок (авто или вручную)
    phase_source: str | None = None            # auto | manual


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)
