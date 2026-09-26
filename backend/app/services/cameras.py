"""Камеры — метки для группировки загруженных снимков по зонам площадки.

Опроса адресов, RTSP и эмулятора нет: снимки поступают только через ручную загрузку
(``photos.upload_photos``), а камера — это просто именованный ярлык (название + зона),
который можно привязать к фото при загрузке, чтобы аналитика сравнивала кадры одной точки
съёмки между собой (см. ``activity.py``: сопоставление рамок по соседним кадрам камеры).
"""
from __future__ import annotations

from .common import AppContext, ServiceError, now, iso, require_project, require_camera, require_building


def _camera_out(ctx: AppContext, cam: dict) -> dict:
    stats = ctx.db.one("SELECT COUNT(*) AS n, MAX(taken_at) AS last FROM photos WHERE camera_id = ?", (cam["id"],))
    cam = dict(cam)
    cam["photos_count"] = stats["n"]
    cam["last_photo_at"] = stats["last"]
    return cam


def list_cameras(ctx: AppContext, user_id: int, project_id: int) -> list[dict]:
    require_project(ctx, user_id, project_id)
    return [_camera_out(ctx, c) for c in ctx.db.all("SELECT * FROM cameras WHERE project_id = ? ORDER BY id",
                                                     (project_id,))]


def get_camera(ctx: AppContext, user_id: int, camera_id: int) -> dict:
    return _camera_out(ctx, require_camera(ctx, user_id, camera_id))


def _validate(ctx, user_id, project_id, data: dict):
    if not (data.get("name") or "").strip():
        raise ServiceError(422, "Укажите название камеры")
    if data.get("building_id"):
        b = require_building(ctx, user_id, data["building_id"])
        if b["project_id"] != project_id:
            raise ServiceError(422, "Объект относится к другой стройке")


def create_camera(ctx: AppContext, user_id: int, project_id: int, name: str, zone: str = "",
                  building_id: int | None = None) -> dict:
    require_project(ctx, user_id, project_id)
    data = dict(name=name, zone=zone or "", building_id=building_id)
    _validate(ctx, user_id, project_id, data)
    cid = ctx.db.execute(
        "INSERT INTO cameras (project_id, building_id, name, zone, created_at) VALUES (?,?,?,?,?)",
        (project_id, building_id, name.strip(), data["zone"].strip(), iso(now())))
    return get_camera(ctx, user_id, cid)


def update_camera(ctx: AppContext, user_id: int, camera_id: int, **fields) -> dict:
    cam = require_camera(ctx, user_id, camera_id)
    allowed = ("name", "zone", "building_id")
    data = {**cam, **{k: v for k, v in fields.items() if k in allowed and v is not None}}
    _validate(ctx, user_id, cam["project_id"], data)
    ctx.db.execute("UPDATE cameras SET name=?, zone=?, building_id=? WHERE id=?",
                   (data["name"].strip(), (data["zone"] or "").strip(), data["building_id"], camera_id))
    return get_camera(ctx, user_id, camera_id)


def delete_camera(ctx: AppContext, user_id: int, camera_id: int) -> None:
    require_camera(ctx, user_id, camera_id)
    ctx.db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))