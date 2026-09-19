"""Камеры: ручная загрузка, опрос адресов (HTTP-снимок / RTSP) и эмуляция риалтайм-камеры.

* ``http``     — URL, отдающий JPEG/PNG (snapshot у большинства IP-камер);
* ``rtsp``     — поток; берётся один кадр через OpenCV;
* ``emulator`` — лента заранее загруженных кадров: каждые ``tick_seconds`` реального времени
  выдаётся следующий кадр, а «время съёмки» сдвигается на ``interval_min`` (по умолчанию 30 мин),
  как у настоящей камеры на площадке.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import socket
import urllib.parse
import urllib.request
from pathlib import Path

from .common import (AppContext, ServiceError, now, iso, parse_dt, require_project, require_camera, require_building)
from .photos import ingest_photo, recompute_activity, _safe_name, _validate_image

log = logging.getLogger(__name__)
SOURCE_TYPES = {"upload", "http", "rtsp", "emulator"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def check_camera_host(url: str, allow_local: bool = False) -> None:
    """Защита от SSRF: адрес камеры не должен указывать на сам сервис или служебные сети.

    Приватные сети (10/8, 172.16/12, 192.168/16) разрешены намеренно: камеры на стройке
    обычно стоят именно там. Запрещены loopback, link-local (включая 169.254.169.254 —
    метаданные облака), multicast и неназначенные адреса. Для тестов и демостенда
    loopback открывается переменной окружения ``ALLOW_LOCAL_CAMERAS=1``.
    """
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise ServiceError(422, "В адресе камеры не указан хост")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ServiceError(422, f"Не удалось определить адрес камеры: {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback and allow_local:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ServiceError(422, f"Адрес {ip} недоступен для камеры: это служебный адрес сервера, "
                                    "а не камера на площадке")


def _camera_out(ctx: AppContext, cam: dict) -> dict:
    stats = ctx.db.one("SELECT COUNT(*) AS n, MAX(taken_at) AS last FROM photos WHERE camera_id = ?", (cam["id"],))
    cam = dict(cam)
    cam["active"] = bool(cam["active"])
    cam["photos_count"] = stats["n"]
    cam["last_photo_at"] = stats["last"]
    if cam["source_type"] == "emulator":
        cam["emulator_frames"] = len(emulator_frames(ctx, cam["id"]))
    return cam


def list_cameras(ctx: AppContext, user_id: int, project_id: int) -> list[dict]:
    require_project(ctx, user_id, project_id)
    return [_camera_out(ctx, c) for c in ctx.db.all("SELECT * FROM cameras WHERE project_id = ? ORDER BY id",
                                                     (project_id,))]


def get_camera(ctx: AppContext, user_id: int, camera_id: int) -> dict:
    return _camera_out(ctx, require_camera(ctx, user_id, camera_id))


def _validate(ctx, user_id, project_id, data: dict):
    if data["source_type"] not in SOURCE_TYPES:
        raise ServiceError(422, "Тип источника: upload, http, rtsp или emulator")
    if not (data.get("name") or "").strip():
        raise ServiceError(422, "Укажите название камеры")
    if data["source_type"] in ("http", "rtsp") and not (data.get("url") or "").strip():
        raise ServiceError(422, "Для камеры с опросом укажите адрес")
    if data["source_type"] == "http" and not data["url"].startswith(("http://", "https://")):
        raise ServiceError(422, "Адрес HTTP-камеры должен начинаться с http:// или https://")
    if data["source_type"] == "rtsp" and not data["url"].startswith(("rtsp://", "rtsps://", "http://", "https://")):
        raise ServiceError(422, "Адрес потока должен начинаться с rtsp://")
    if data["source_type"] in ("http", "rtsp"):
        check_camera_host(data["url"], ctx.settings.allow_local_cameras)
    if data["source_type"] != "upload" and not data.get("building_id"):
        raise ServiceError(422, "Привяжите камеру к объекту — снимки будут анализироваться по его плану")
    if data.get("building_id"):
        b = require_building(ctx, user_id, data["building_id"])
        if b["project_id"] != project_id:
            raise ServiceError(422, "Объект относится к другой стройке")
    if not (1 <= int(data.get("interval_min") or 30) <= 1440):
        raise ServiceError(422, "Интервал съёмки — от 1 до 1440 минут")
    if not (1 <= int(data.get("tick_seconds") or 10) <= 3600):
        raise ServiceError(422, "Шаг эмуляции — от 1 до 3600 секунд")


def create_camera(ctx: AppContext, user_id: int, project_id: int, name: str, source_type: str = "upload",
                  zone: str = "", url: str = "", building_id: int | None = None, interval_min: int = 30,
                  tick_seconds: int = 10, active: bool = False, emulator_start: str | None = None) -> dict:
    require_project(ctx, user_id, project_id)
    data = dict(name=name, source_type=source_type, zone=zone or "", url=url or "", building_id=building_id,
                interval_min=interval_min or 30, tick_seconds=tick_seconds or 10)
    _validate(ctx, user_id, project_id, data)
    clock = iso(parse_dt(emulator_start, now())) if source_type == "emulator" else None
    cid = ctx.db.execute(
        "INSERT INTO cameras (project_id, building_id, name, zone, source_type, url, interval_min, tick_seconds, "
        "active, emulator_clock, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, building_id, name.strip(), data["zone"].strip(), source_type, data["url"].strip(),
         int(data["interval_min"]), int(data["tick_seconds"]), int(bool(active) and source_type != "upload"),
         clock, iso(now())))
    return get_camera(ctx, user_id, cid)


def update_camera(ctx: AppContext, user_id: int, camera_id: int, **fields) -> dict:
    cam = require_camera(ctx, user_id, camera_id)
    allowed = ("name", "zone", "url", "building_id", "interval_min", "tick_seconds", "active", "emulator_start")
    data = {**cam, **{k: v for k, v in fields.items() if k in allowed and v is not None}}
    _validate(ctx, user_id, cam["project_id"], data)
    clock = cam["emulator_clock"]
    if fields.get("emulator_start"):
        clock = iso(parse_dt(fields["emulator_start"]))
    active = int(bool(data["active"])) if cam["source_type"] != "upload" else 0
    ctx.db.execute(
        "UPDATE cameras SET name=?, zone=?, url=?, building_id=?, interval_min=?, tick_seconds=?, active=?, "
        "emulator_clock=?, last_error=CASE WHEN ? THEN NULL ELSE last_error END WHERE id=?",
        (data["name"].strip(), (data["zone"] or "").strip(), (data["url"] or "").strip(), data["building_id"],
         int(data["interval_min"]), int(data["tick_seconds"]), active, clock, active, camera_id))
    return get_camera(ctx, user_id, camera_id)


def delete_camera(ctx: AppContext, user_id: int, camera_id: int) -> None:
    require_camera(ctx, user_id, camera_id)
    ctx.db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))


# ------------------------------------------------------------------ эмулятор
def _emulator_dir(ctx: AppContext, camera_id: int) -> Path:
    return ctx.settings.emulator_dir / str(camera_id)


def emulator_frames(ctx: AppContext, camera_id: int) -> list[Path]:
    folder = _emulator_dir(ctx, camera_id)
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT)


def upload_emulator_frames(ctx: AppContext, user_id: int, camera_id: int, files: list[tuple[str, bytes]]) -> dict:
    cam = require_camera(ctx, user_id, camera_id)
    if cam["source_type"] != "emulator":
        raise ServiceError(422, "Кадры можно загружать только в камеру-эмулятор")
    folder = _emulator_dir(ctx, camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    start = len(emulator_frames(ctx, camera_id))
    saved, errors = 0, []
    for i, (name, data) in enumerate(files):
        try:
            _validate_image(data, ctx.settings.max_upload_mb)
        except ServiceError as exc:
            errors.append({"file": name, "error": exc.detail})
            continue
        (folder / f"{start + i:05d}__{_safe_name(name)}").write_bytes(data)
        saved += 1
    return {"saved": saved, "errors": errors, "camera": get_camera(ctx, user_id, camera_id)}


def reset_emulator(ctx: AppContext, user_id: int, camera_id: int, start_at: str | None = None,
                   clear_frames: bool = False) -> dict:
    cam = require_camera(ctx, user_id, camera_id)
    if cam["source_type"] != "emulator":
        raise ServiceError(422, "Это не камера-эмулятор")
    if clear_frames:
        for p in emulator_frames(ctx, camera_id):
            p.unlink(missing_ok=True)
    ctx.db.execute("UPDATE cameras SET emulator_cursor = 0, emulator_clock = ?, last_error = NULL, "
                   "last_polled_at = NULL, active = 0 WHERE id = ?",
                   (iso(parse_dt(start_at, now())), camera_id))
    return get_camera(ctx, user_id, camera_id)


# ------------------------------------------------------------------ опрос
def grab_frame(ctx: AppContext, cam: dict) -> tuple[str, bytes, dt.datetime]:
    """Получить один кадр с камеры: (имя, байты, время съёмки)."""
    stamp = now()
    if cam["source_type"] == "http":
        check_camera_host(cam["url"], ctx.settings.allow_local_cameras)   # повторно: DNS мог измениться
        req = urllib.request.Request(cam["url"], headers={"User-Agent": "StroyKontrol/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(ctx.settings.max_upload_mb * 1024 * 1024 + 1)
        return f"cam{cam['id']}_{stamp:%Y%m%d_%H%M%S}.jpg", data, stamp
    if cam["source_type"] == "rtsp":
        check_camera_host(cam["url"], ctx.settings.allow_local_cameras)
        import cv2

        cap = cv2.VideoCapture(cam["url"])
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok:
            raise ServiceError(502, "Камера не отдала кадр")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return f"cam{cam['id']}_{stamp:%Y%m%d_%H%M%S}.jpg", buf.tobytes(), stamp
    if cam["source_type"] == "emulator":
        frames = emulator_frames(ctx, cam["id"])
        if cam["emulator_cursor"] >= len(frames):
            raise ServiceError(409, "Кадры эмулятора закончились — загрузите новые или сбросьте ленту")
        path = frames[cam["emulator_cursor"]]
        taken = parse_dt(cam["emulator_clock"], stamp)
        return path.name.split("__", 1)[-1], path.read_bytes(), taken
    raise ServiceError(422, "Камера ручной загрузки не опрашивается")


def poll_camera(ctx: AppContext, cam: dict) -> dict:
    building = ctx.db.one("SELECT * FROM buildings WHERE id = ?", (cam["building_id"],))
    if not building:
        raise ServiceError(422, "Камера не привязана к объекту")
    try:
        name, data, taken = grab_frame(ctx, cam)
        photo_id = ingest_photo(ctx, building, cam, name, data, taken)
    except Exception as exc:
        detail = exc.detail if isinstance(exc, ServiceError) else str(exc)
        stop = cam["source_type"] == "emulator"   # эмулятор без кадров останавливаем
        ctx.db.execute("UPDATE cameras SET last_polled_at = ?, last_error = ?, active = CASE WHEN ? THEN 0 "
                       "ELSE active END WHERE id = ?", (iso(now()), detail, int(stop), cam["id"]))
        raise ServiceError(exc.status if isinstance(exc, ServiceError) else 502, detail)
    recompute_activity(ctx, building["id"], cam["id"], taken)
    if cam["source_type"] == "emulator":
        ctx.db.execute("UPDATE cameras SET emulator_cursor = emulator_cursor + 1, emulator_clock = ?, "
                       "last_polled_at = ?, last_error = NULL WHERE id = ?",
                       (iso(taken + dt.timedelta(minutes=cam["interval_min"])), iso(now()), cam["id"]))
    else:
        ctx.db.execute("UPDATE cameras SET last_polled_at = ?, last_error = NULL WHERE id = ?",
                       (iso(now()), cam["id"]))
    return {"photo_id": photo_id, "taken_at": iso(taken)}


def poll_now(ctx: AppContext, user_id: int, camera_id: int) -> dict:
    return poll_camera(ctx, require_camera(ctx, user_id, camera_id))


def due_cameras(ctx: AppContext, moment: dt.datetime | None = None) -> list[dict]:
    moment = moment or now()
    due = []
    for cam in ctx.db.all("SELECT * FROM cameras WHERE active = 1 AND source_type != 'upload'"):
        last = parse_dt(cam["last_polled_at"])
        period = (dt.timedelta(seconds=cam["tick_seconds"]) if cam["source_type"] == "emulator"
                  else dt.timedelta(minutes=cam["interval_min"]))
        if last is None or moment - last >= period:
            due.append(cam)
    return due


def poll_due(ctx: AppContext, moment: dt.datetime | None = None) -> dict:
    """Один проход фонового опроса. Ошибки отдельных камер не останавливают остальные."""
    done, failed = 0, 0
    for cam in due_cameras(ctx, moment):
        try:
            poll_camera(ctx, cam)
            done += 1
        except ServiceError as exc:
            failed += 1
            log.warning("Камера %s: %s", cam["id"], exc.detail)
    return {"polled": done, "failed": failed}
