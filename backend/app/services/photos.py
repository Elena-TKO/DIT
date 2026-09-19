"""Снимки: приём, детекция техники, пересчёт активности, выдача (шаги 5–7)."""
from __future__ import annotations

import datetime as dt
import io
import re
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from PIL import Image, ImageOps

from app.core.activity import assign_activity
from app.core.stage import detect_stage, observe
from app.core.types import Detection, PhotoObs
from app.core.verdict import planned_phases_at
from .common import (AppContext, ServiceError, now, iso, parse_dt, require_building, require_camera, require_photo)
from .projects import active_leaf_tasks

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
ACTIVITY_LOOKBACK = dt.timedelta(days=7)


def _safe_name(name: str) -> str:
    base = Path(name or "photo").name
    return re.sub(r"[^\w.\-]+", "_", base)[:80] or "photo"


def _validate_image(data: bytes, max_mb: int) -> tuple[str, int, int]:
    if len(data) > max_mb * 1024 * 1024:
        raise ServiceError(413, f"Файл больше {max_mb} МБ")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
    except Exception:
        raise ServiceError(422, "Файл не является изображением")
    if fmt not in ALLOWED_FORMATS:
        raise ServiceError(422, f"Формат {fmt} не поддерживается (нужны JPEG, PNG, WEBP, BMP)")
    return fmt, w, h


def trim_borders(data: bytes, max_share: float = 0.12) -> bytes:
    """Срезает однородные белые/чёрные поля по краям (типично для скриншотов камер).

    Обрезка делается до детекции, поэтому координаты рамок соответствуют сохранённому снимку.
    Если полей нет или они подозрительно широкие, байты возвращаются без изменений."""
    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        gray = np.asarray(img.convert("L"), dtype=np.int16)
        h, w = gray.shape

        def uniform(line: np.ndarray) -> bool:
            return bool(((line > 242).mean() > 0.985) or ((line < 12).mean() > 0.985))

        top = 0
        while top < h * max_share and uniform(gray[top]):
            top += 1
        bottom = h
        while h - bottom < h * max_share and uniform(gray[bottom - 1]):
            bottom -= 1
        left = 0
        while left < w * max_share and uniform(gray[top:bottom, left]):
            left += 1
        right = w
        while w - right < w * max_share and uniform(gray[top:bottom, right - 1]):
            right -= 1
        if (top, left, bottom, right) == (0, 0, h, w):
            return data
        if top >= h * max_share or left >= w * max_share or h - bottom >= h * max_share or w - right >= w * max_share:
            return data          # «поле» слишком широкое — вероятно, это содержимое кадра (снег, небо)
        cropped = img.crop((left, top, right, bottom))
        if cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        buf = io.BytesIO()
        if fmt == "PNG":
            cropped.save(buf, "PNG", optimize=True)
        else:
            cropped.convert("RGB").save(buf, "JPEG", quality=93)
        return buf.getvalue()


def ingest_photo(ctx: AppContext, building: dict, camera: dict | None, original_name: str, data: bytes,
                 taken_at: dt.datetime) -> int:
    """Сохраняет снимок, запускает детекцию и записывает результат. Возвращает id снимка."""
    _validate_image(data, ctx.settings.max_upload_mb)
    data = trim_borders(data)
    _, w, h = _validate_image(data, ctx.settings.max_upload_mb)
    folder = ctx.settings.photos_dir / str(building["id"])
    folder.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex[:12]}__{_safe_name(original_name)}"
    path = folder / file_name
    path.write_bytes(data)

    started = time.perf_counter()
    try:
        with ctx.detect_lock:
            detections = ctx.detector.detect(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ServiceError(500, f"Ошибка детекции: {exc}")
    elapsed = int((time.perf_counter() - started) * 1000)

    with ctx.db.connect() as conn:
        photo_id = conn.execute(
            "INSERT INTO photos (building_id, camera_id, original_name, file_name, width, height, taken_at, "
            "uploaded_at, detector, process_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (building["id"], camera["id"] if camera else None, original_name or file_name, file_name, w, h,
             iso(taken_at), iso(now()), ctx.detector.name, elapsed)).lastrowid
        conn.executemany(
            "INSERT INTO detections (photo_id, cls, label_raw, confidence, x1, y1, x2, y2) VALUES (?,?,?,?,?,?,?,?)",
            [(photo_id, d.cls, d.label_raw, d.confidence, *d.bbox) for d in detections])
    return photo_id


def upload_photos(ctx: AppContext, user_id: int, building_id: int, files: list[tuple[str, bytes]],
                  camera_id: int | None = None, start_at: str | None = None, interval_min: int = 30) -> dict:
    """Пакетная загрузка. Реальных дат у снимков нет — время задаётся от ``start_at`` с шагом ``interval_min``."""
    building = require_building(ctx, user_id, building_id)
    if not files:
        raise ServiceError(422, "Выберите хотя бы один снимок")
    camera = None
    if camera_id:
        camera = require_camera(ctx, user_id, camera_id)
        if camera["project_id"] != building["project_id"]:
            raise ServiceError(422, "Камера относится к другой стройке")
    if interval_min < 0 or interval_min > 24 * 60:
        raise ServiceError(422, "Интервал между снимками — от 0 до 1440 минут")
    base = parse_dt(start_at, now())

    ids, errors = [], []
    for i, (name, data) in enumerate(files):
        try:
            ids.append(ingest_photo(ctx, building, camera, name, data, base + dt.timedelta(minutes=interval_min * i)))
        except ServiceError as exc:
            errors.append({"file": name, "error": exc.detail})
    if ids:
        recompute_activity(ctx, building_id, camera["id"] if camera else None, since=base)
    return {"uploaded": len(ids), "photo_ids": ids, "errors": errors,
            "photos": [photo_summary(ctx, pid) for pid in ids]}


def load_obs(ctx: AppContext, building_id: int, since: dt.datetime | None = None,
             until: dt.datetime | None = None, camera_id: int | None | str = "any") -> list[PhotoObs]:
    sql = ("SELECT ph.id, ph.taken_at, ph.camera_id, c.name AS camera_name, c.zone FROM photos ph "
           "LEFT JOIN cameras c ON c.id = ph.camera_id WHERE ph.building_id = ?")
    params: list = [building_id]
    if since:
        sql += " AND ph.taken_at >= ?"
        params.append(iso(since))
    if until:
        sql += " AND ph.taken_at <= ?"
        params.append(iso(until))
    if camera_id != "any":
        sql += " AND ph.camera_id IS NULL" if camera_id is None else " AND ph.camera_id = ?"
        if camera_id is not None:
            params.append(camera_id)
    rows = ctx.db.all(sql + " ORDER BY ph.taken_at, ph.id", params)
    if not rows:
        return []
    by_id = {r["id"]: PhotoObs(id=r["id"], taken_at=dt.datetime.fromisoformat(r["taken_at"]),
                               camera_id=r["camera_id"], camera_name=r["camera_name"] or "",
                               zone=r["zone"] or "") for r in rows}
    placeholders = ",".join("?" * len(by_id))
    for d in ctx.db.all(f"SELECT * FROM detections WHERE photo_id IN ({placeholders}) ORDER BY id", list(by_id)):
        by_id[d["photo_id"]].detections.append(Detection(
            id=d["id"], cls=d["cls"], confidence=d["confidence"], bbox=(d["x1"], d["y1"], d["x2"], d["y2"]),
            label_raw=d["label_raw"], activity=d["activity"], idle_minutes=d["idle_minutes"]))
    return list(by_id.values())


def recompute_activity(ctx: AppContext, building_id: int, camera_id: int | None, since: dt.datetime | None = None):
    """Пересчёт «работает/стоит» для цепочки кадров камеры (с запасом назад)."""
    start = (since - ACTIVITY_LOOKBACK) if since else None
    frames = load_obs(ctx, building_id, since=start, camera_id=camera_id)
    assign_activity(frames, ctx.m)
    with ctx.db.connect() as conn:
        conn.executemany("UPDATE detections SET activity = ?, idle_minutes = ? WHERE id = ?",
                         [(d.activity, d.idle_minutes, d.id) for f in frames for d in f.detections])


def _detection_dict(ctx: AppContext, d: dict) -> dict:
    return {"id": d["id"], "cls": d["cls"], "label": ctx.m.label(d["cls"]), "label_raw": d["label_raw"],
            "confidence": d["confidence"], "bbox": [d["x1"], d["y1"], d["x2"], d["y2"]],
            "activity": d["activity"], "idle_minutes": d["idle_minutes"], "manual": bool(d["manual"])}


def photo_summary(ctx: AppContext, photo_id: int) -> dict:
    p = ctx.db.one("SELECT ph.*, c.name AS camera_name, c.zone FROM photos ph "
                   "LEFT JOIN cameras c ON c.id = ph.camera_id WHERE ph.id = ?", (photo_id,))
    dets = ctx.db.all("SELECT * FROM detections WHERE photo_id = ? ORDER BY confidence DESC", (photo_id,))
    min_conf = ctx.m.detection["min_confidence"]
    counts: dict[str, int] = {}
    for d in dets:
        if d["confidence"] >= min_conf:
            counts[d["cls"]] = counts.get(d["cls"], 0) + 1
    return {**p, "detections_count": sum(counts.values()),
            "equipment": [{"cls": c, "label": ctx.m.label(c), "count": n} for c, n in counts.items()]}


def list_photos(ctx: AppContext, user_id: int, building_id: int, limit: int = 200, offset: int = 0,
                camera_id: int | None = None, taken_from: str | None = None, taken_to: str | None = None,
                cls: str | None = None) -> dict:
    """Список снимков страницей: два запроса на страницу, без обращения к БД на каждый снимок."""
    require_building(ctx, user_id, building_id)
    where, params = "ph.building_id = ?", [building_id]
    if camera_id:
        where += " AND ph.camera_id = ?"
        params.append(camera_id)
    if taken_from:
        where += " AND ph.taken_at >= ?"
        params.append(iso(parse_dt(taken_from)))
    if taken_to:
        where += " AND ph.taken_at <= ?"
        params.append(iso(parse_dt(taken_to)))
    if cls:
        if cls not in ctx.m.equipment:
            raise ServiceError(422, f"Неизвестный класс техники: {cls}")
        where += (" AND EXISTS (SELECT 1 FROM detections d WHERE d.photo_id = ph.id AND d.cls = ? "
                  "AND d.confidence >= ?)")
        params += [cls, ctx.m.detection["min_confidence"]]
    total = ctx.db.one(f"SELECT COUNT(*) AS n FROM photos ph WHERE {where}", params)["n"]
    rows = ctx.db.all(
        f"SELECT ph.*, c.name AS camera_name, c.zone FROM photos ph LEFT JOIN cameras c ON c.id = ph.camera_id "
        f"WHERE {where} ORDER BY ph.taken_at DESC, ph.id DESC LIMIT ? OFFSET ?",
        params + [max(1, min(limit, 1000)), max(0, offset)])
    items = {r["id"]: {**r, "detections_count": 0, "equipment": []} for r in rows}
    if items:
        placeholders = ",".join("?" * len(items))
        counts: dict[int, dict[str, int]] = {i: {} for i in items}
        for d in ctx.db.all(
                f"SELECT photo_id, cls, COUNT(*) AS n FROM detections WHERE photo_id IN ({placeholders}) "
                f"AND confidence >= ? GROUP BY photo_id, cls",
                list(items) + [ctx.m.detection["min_confidence"]]):
            counts[d["photo_id"]][d["cls"]] = d["n"]
        for pid, by_cls in counts.items():
            items[pid]["detections_count"] = sum(by_cls.values())
            items[pid]["equipment"] = [{"cls": c, "label": ctx.m.label(c), "count": n} for c, n in by_cls.items()]
    return {"total": total, "items": list(items.values())}


def photo_detail(ctx: AppContext, user_id: int, photo_id: int) -> dict:
    """Снимок + техника + этап, определённый по одному этому кадру."""
    photo = require_photo(ctx, user_id, photo_id)
    summary = photo_summary(ctx, photo_id)
    dets = ctx.db.all("SELECT * FROM detections WHERE photo_id = ? ORDER BY confidence DESC", (photo_id,))
    taken = dt.datetime.fromisoformat(photo["taken_at"])
    tasks = active_leaf_tasks(ctx, photo["building_id"])
    planned = planned_phases_at(tasks, taken.date())
    obs = load_obs(ctx, photo["building_id"], since=taken, until=taken)
    obs = [o for o in obs if o.id == photo_id]
    present = set(observe(obs, ctx.m))
    stage = detect_stage(present, ctx.m, set(planned))
    return {**summary,
            "detections": [_detection_dict(ctx, d) for d in dets],
            "min_confidence": ctx.m.detection["min_confidence"],
            "planned_phases": [{"phase": p, "name": ctx.m.phase(p).name} for p in
                               sorted(planned, key=lambda x: ctx.m.phase(x).sequence)],
            "stage": stage.to_dict()}


def replace_detections(ctx: AppContext, user_id: int, photo_id: int, items: list[dict]) -> dict:
    """Ручная корректировка разметки (если модель ошиблась)."""
    photo = require_photo(ctx, user_id, photo_id)
    rows = []
    for it in items:
        cls = it.get("cls")
        if cls not in ctx.m.equipment:
            raise ServiceError(422, f"Неизвестный класс техники: {cls}")
        x1, y1, x2, y2 = [float(v) for v in it.get("bbox", [])][:4]
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ServiceError(422, "Координаты рамки задаются в долях кадра: 0 ≤ x1 < x2 ≤ 1")
        rows.append((photo_id, cls, it.get("label_raw") or "manual", float(it.get("confidence", 1.0)),
                     x1, y1, x2, y2, int(bool(it.get("manual", True)))))
    with ctx.db.connect() as conn:
        conn.execute("DELETE FROM detections WHERE photo_id = ?", (photo_id,))
        conn.executemany("INSERT INTO detections (photo_id, cls, label_raw, confidence, x1, y1, x2, y2, manual) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    recompute_activity(ctx, photo["building_id"], photo["camera_id"], dt.datetime.fromisoformat(photo["taken_at"]))
    return photo_detail(ctx, user_id, photo_id)


def redetect(ctx: AppContext, user_id: int, photo_id: int) -> dict:
    photo = require_photo(ctx, user_id, photo_id)
    path = image_path(ctx, photo)
    with ctx.detect_lock:
        detections = ctx.detector.detect(path)
    with ctx.db.connect() as conn:
        conn.execute("DELETE FROM detections WHERE photo_id = ?", (photo_id,))
        conn.executemany(
            "INSERT INTO detections (photo_id, cls, label_raw, confidence, x1, y1, x2, y2) VALUES (?,?,?,?,?,?,?,?)",
            [(photo_id, d.cls, d.label_raw, d.confidence, *d.bbox) for d in detections])
        conn.execute("UPDATE photos SET detector = ? WHERE id = ?", (ctx.detector.name, photo_id))
    recompute_activity(ctx, photo["building_id"], photo["camera_id"], dt.datetime.fromisoformat(photo["taken_at"]))
    return photo_detail(ctx, user_id, photo_id)


def drop_thumbs(ctx: AppContext, photo_id: int) -> None:
    for t in (ctx.settings.photos_dir / "thumbs").glob(f"{photo_id}_*.jpg"):
        t.unlink(missing_ok=True)


def purge_building_files(ctx: AppContext, building_id: int) -> None:
    """Удаляет файлы снимков объекта: БД чистится каскадом, диск — здесь."""
    ids = [r["id"] for r in ctx.db.all("SELECT id FROM photos WHERE building_id = ?", (building_id,))]
    for pid in ids:
        drop_thumbs(ctx, pid)
    shutil.rmtree(ctx.settings.photos_dir / str(building_id), ignore_errors=True)


def delete_photo(ctx: AppContext, user_id: int, photo_id: int) -> None:
    photo = require_photo(ctx, user_id, photo_id)
    image_path(ctx, photo).unlink(missing_ok=True)
    drop_thumbs(ctx, photo_id)
    ctx.db.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    recompute_activity(ctx, photo["building_id"], photo["camera_id"], dt.datetime.fromisoformat(photo["taken_at"]))


def image_path(ctx: AppContext, photo: dict) -> Path:
    return ctx.settings.photos_dir / str(photo["building_id"]) / photo["file_name"]


def image_file(ctx: AppContext, user_id: int, photo_id: int, width: int | None = None) -> tuple[Path, str]:
    """Путь к изображению (или к кешированной миниатюре) и MIME-тип."""
    photo = require_photo(ctx, user_id, photo_id)
    path = image_path(ctx, photo)
    if not path.exists():
        raise ServiceError(404, "Файл снимка отсутствует")
    if not width:
        suffix = path.suffix.lower()
        mime = {".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp"}.get(suffix, "image/jpeg")
        return path, mime
    width = max(64, min(int(width), 1600))
    thumb = ctx.settings.photos_dir / "thumbs" / f"{photo_id}_{width}.jpg"
    if not thumb.exists():
        thumb.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((width, width * 4))
            img.save(thumb, "JPEG", quality=82)
    return thumb, "image/jpeg"
