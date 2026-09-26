"""Контекст приложения и общие помощники сервисного слоя.

Сервисный слой не зависит от веб-фреймворка: FastAPI-роуты только разбирают запрос
и вызывают эти функции. Благодаря этому вся логика API покрыта обычными тестами.
"""
from __future__ import annotations

import datetime as dt
import threading

from app.config import Settings
from app.core.catalog import load_catalog
from app.core.methodology import load_methodology
from app.db import Database
from app.ml.detectors import create_detector


class ServiceError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class AppContext:
    def __init__(self, settings: Settings, detector=None):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.m = load_methodology()
        self.catalog = load_catalog()
        self._detector = detector
        self._init_lock = threading.Lock()
        self.detect_lock = threading.Lock()   # модели YOLO не гарантируют потокобезопасность
        self.login_attempts: dict[str, list[float]] = {}   # защита от перебора пароля

    @property
    def detector(self):
        if self._detector is None:
            with self._init_lock:
                if self._detector is None:
                    self._detector = create_detector(self.settings, self.m)
        return self._detector


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def parse_dt(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=0)
    text = str(value).strip().replace(" ", "T").rstrip("Z")
    try:
        if len(text) == 10:
            return dt.datetime.combine(dt.date.fromisoformat(text), dt.time(12, 0))
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)
    except ValueError:
        raise ServiceError(422, f"Некорректная дата/время: {value}")


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ServiceError(422, f"Некорректная дата: {value}")


def require_project(ctx: AppContext, user_id: int, project_id: int) -> dict:
    project = ctx.db.one("SELECT * FROM projects WHERE id = ? AND owner_id = ?", (project_id, user_id))
    if not project:
        raise ServiceError(404, "Стройка не найдена")
    return project


def require_building(ctx: AppContext, user_id: int, building_id: int) -> dict:
    building = ctx.db.one(
        "SELECT b.* FROM buildings b JOIN projects p ON p.id = b.project_id WHERE b.id = ? AND p.owner_id = ?",
        (building_id, user_id))
    if not building:
        raise ServiceError(404, "Объект не найден")
    return building


def require_camera(ctx: AppContext, user_id: int, camera_id: int) -> dict:
    camera = ctx.db.one(
        "SELECT c.* FROM cameras c JOIN projects p ON p.id = c.project_id WHERE c.id = ? AND p.owner_id = ?",
        (camera_id, user_id))
    if not camera:
        raise ServiceError(404, "Камера не найдена")
    return camera


def require_photo(ctx: AppContext, user_id: int, photo_id: int) -> dict:
    photo = ctx.db.one(
        "SELECT ph.* FROM photos ph JOIN buildings b ON b.id = ph.building_id "
        "JOIN projects p ON p.id = b.project_id WHERE ph.id = ? AND p.owner_id = ?",
        (photo_id, user_id))
    if not photo:
        raise ServiceError(404, "Снимок не найден")
    return photo
