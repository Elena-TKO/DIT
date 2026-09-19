"""Анализ объекта: вердикт, таймлайн, рекомендации, отчёт (шаги 8–10)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json

from app.core.catalog import OBJECT_TYPES
from app.core.economics import summary as economics_summary
from app.core.recommend import recommendations, CAMERA_GUIDELINES
from app.core.timeline import build_timeline, STATUSES
from app.core.verdict import build_verdict
from .common import AppContext, ServiceError, now, iso, parse_dt, require_building, require_project
from .photos import load_obs
from .projects import active_leaf_tasks, cover_photo_id

SEVERITY_LABEL = {"critical": "Критично", "warning": "Предупреждение", "info": "Информация"}


def default_at(ctx: AppContext, building_id: int) -> dt.datetime:
    """Момент анализа по умолчанию — время последнего снимка (у демо-снимков время условное)."""
    row = ctx.db.one("SELECT MAX(taken_at) AS last FROM photos WHERE building_id = ?", (building_id,))
    return parse_dt(row["last"]) if row and row["last"] else now()


def _cameras_for(ctx: AppContext, building: dict) -> list[dict]:
    cams = ctx.db.all(
        "SELECT c.*, (SELECT MAX(taken_at) FROM photos ph WHERE ph.camera_id = c.id) AS last_photo "
        "FROM cameras c WHERE c.project_id = ? AND (c.building_id = ? OR c.building_id IS NULL)",
        (building["project_id"], building["id"]))
    for c in cams:
        c["active"] = bool(c["active"])
        c["last_photo_at"] = parse_dt(c.pop("last_photo"))
    return cams


def _compute(ctx: AppContext, building: dict, at: dt.datetime) -> tuple[dict, dict, list[dict], dict]:
    tasks = active_leaf_tasks(ctx, building["id"])
    photos = load_obs(ctx, building["id"], until=at)
    verdict = build_verdict(ctx.m, at, tasks, photos, _cameras_for(ctx, building))
    timeline = build_timeline(ctx.m, at, tasks, photos, building["start_date"], building["end_date"])
    window = [p for p in photos if p.taken_at >= at - dt.timedelta(hours=ctx.m.analysis["window_hours"])]
    money = economics_summary(ctx.m, timeline, window, photos)
    return verdict, timeline, recommendations(ctx.m, verdict, timeline), money


def analyze(ctx: AppContext, user_id: int, building_id: int, at: str | None = None, save: bool = False) -> dict:
    building = require_building(ctx, user_id, building_id)
    moment = parse_dt(at, default_at(ctx, building_id))
    verdict, timeline, recs, money = _compute(ctx, building, moment)
    if save:
        _save_verdict(ctx, building_id, verdict, timeline, money)
    for d in verdict["deviations"]:
        d["severity_label"] = SEVERITY_LABEL[d["severity"]]
    return {
        "building": {"id": building["id"], "name": building["name"], "object_type": building["object_type"],
                     "start_date": building["start_date"], "end_date": building["end_date"]},
        "at": iso(moment),
        "verdict": verdict,
        "timeline_summary": {k: timeline[k] for k in ("completion_percent", "planned_percent", "spi",
                                                      "max_delay_days", "forecast_end", "delay_risk",
                                                      "status_counts")},
        "recommendations": recs,
        "economics": money,
    }


def _save_verdict(ctx: AppContext, building_id: int, verdict: dict, timeline: dict, money: dict) -> int:
    with ctx.db.connect() as conn:
        vid = conn.execute(
            "INSERT INTO verdicts (building_id, at, status, payload, created_at, completion_percent, "
            "planned_percent, idle_cost) VALUES (?,?,?,?,?,?,?,?)",
            (building_id, verdict["at"], verdict["status"], json.dumps(verdict, ensure_ascii=False), iso(now()),
             timeline["completion_percent"], timeline["planned_percent"], money["idle_total"])).lastrowid
        conn.executemany(
            "INSERT INTO deviations (building_id, verdict_id, at, kind, severity, phase, message, equipment, "
            "photo_ids, zones) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(building_id, vid, verdict["at"], d["kind"], d["severity"], d["phase"], d["message"],
              json.dumps(d["equipment"]), json.dumps(d["photo_ids"]), json.dumps(d["zones"], ensure_ascii=False))
             for d in verdict["deviations"]])
    return vid


def timeline(ctx: AppContext, user_id: int, building_id: int, at: str | None = None) -> dict:
    building = require_building(ctx, user_id, building_id)
    moment = parse_dt(at, default_at(ctx, building_id))
    tasks = active_leaf_tasks(ctx, building_id)
    photos = load_obs(ctx, building_id, until=moment)
    return build_timeline(ctx.m, moment, tasks, photos, building["start_date"], building["end_date"])


def deviation_log(ctx: AppContext, user_id: int, building_id: int, limit: int = 100) -> list[dict]:
    require_building(ctx, user_id, building_id)
    rows = ctx.db.all("SELECT * FROM deviations WHERE building_id = ? ORDER BY at DESC, id DESC LIMIT ?",
                      (building_id, max(1, min(limit, 1000))))
    for r in rows:
        for key in ("equipment", "photo_ids", "zones"):
            r[key] = json.loads(r[key])
        r["phase_name"] = ctx.m.phase(r["phase"]).name if r["phase"] else None
        r["severity_label"] = SEVERITY_LABEL.get(r["severity"], r["severity"])
    return rows


def project_overview(ctx: AppContext, user_id: int, project_id: int) -> dict:
    """Сводка по всем объектам стройки для главного экрана."""
    project = require_project(ctx, user_id, project_id)
    items = []
    for b in ctx.db.all("SELECT * FROM buildings WHERE project_id = ? ORDER BY id", (project_id,)):
        moment = default_at(ctx, b["id"])
        verdict, tl, _, money = _compute(ctx, b, moment)
        items.append({
            "id": b["id"], "name": b["name"], "object_type": b["object_type"],
            "object_type_title": OBJECT_TYPES.get(b["object_type"], b["object_type"]),
            "start_date": b["start_date"], "end_date": b["end_date"], "at": iso(moment),
            "status": verdict["status"], "summary": verdict["summary"],
            "stage": verdict["stage"]["top_name"],
            "stage_closest": verdict["stage"]["closest_name"],
            "stage_note": verdict["stage"]["explanation"],
            "deviations": sum(1 for d in verdict["deviations"] if d["severity"] != "info"),
            "completion_percent": tl["completion_percent"], "planned_percent": tl["planned_percent"],
            "forecast_end": tl["forecast_end"], "max_delay_days": tl["max_delay_days"],
            "delay_risk": tl["delay_risk"],
            "photos": ctx.db.one("SELECT COUNT(*) AS n FROM photos WHERE building_id = ?", (b["id"],))["n"],
            "cover_photo_id": cover_photo_id(ctx, b["id"]),
            "idle_cost": money["idle_total"], "idle_minutes": money["idle_minutes"],
            "currency": money["currency"],
        })
    return {"project": project, "buildings": items}


def project_report(ctx: AppContext, user_id: int, project_id: int, at: str | None = None) -> dict:
    project = require_project(ctx, user_id, project_id)
    buildings = []
    for b in ctx.db.all("SELECT * FROM buildings WHERE project_id = ? ORDER BY id", (project_id,)):
        moment = parse_dt(at, default_at(ctx, b["id"]))
        verdict, tl, recs, money = _compute(ctx, b, moment)
        stats = ctx.db.one("SELECT COUNT(*) AS n, MIN(taken_at) AS first, MAX(taken_at) AS last "
                           "FROM photos WHERE building_id = ?", (b["id"],))
        equipment = ctx.db.all(
            "SELECT d.cls, COUNT(*) AS n, COUNT(DISTINCT d.photo_id) AS photos FROM detections d "
            "JOIN photos ph ON ph.id = d.photo_id WHERE ph.building_id = ? AND d.confidence >= ? "
            "GROUP BY d.cls ORDER BY n DESC", (b["id"], ctx.m.detection["min_confidence"]))
        for e in equipment:
            e["label"] = ctx.m.label(e["cls"])
        for d in verdict["deviations"]:
            d["severity_label"] = SEVERITY_LABEL[d["severity"]]
        history = ctx.db.all("SELECT kind, severity, COUNT(*) AS n FROM deviations WHERE building_id = ? "
                             "GROUP BY kind, severity ORDER BY n DESC", (b["id"],))
        buildings.append({
            "building": {**b, "object_type_title": OBJECT_TYPES.get(b["object_type"], b["object_type"])},
            "at": iso(moment), "verdict": verdict, "timeline": tl, "recommendations": recs, "economics": money,
            "photo_stats": stats, "equipment_totals": equipment, "deviation_history": history,
        })
    return {
        "generated_at": iso(now()), "project": project, "buildings": buildings,
        "legend": [{"status": k, **v} for k, v in STATUSES.items()],
        "camera_guidelines": CAMERA_GUIDELINES,
        "detector": ctx.detector.info(),
    }


# ------------------------------------------------------------------ ссылка и выгрузка
def create_report_link(ctx: AppContext, user_id: int, project_id: int, ttl_hours: int = 72) -> dict:
    """Ссылка на отчёт для заказчика: только чтение, только этот отчёт, ограниченный срок."""
    from app.security import create_scoped_token

    require_project(ctx, user_id, project_id)
    if not (1 <= ttl_hours <= 24 * 30):
        raise ServiceError(422, "Срок действия ссылки — от 1 часа до 30 суток")
    token = create_scoped_token(ctx.settings.secret_key, "report", project_id, ttl_hours)
    return {"token": token, "path": f"/api/public/report/{token}",
            "expires_at": iso(now() + dt.timedelta(hours=ttl_hours)), "ttl_hours": ttl_hours}


def project_by_report_token(ctx: AppContext, token: str) -> tuple[int, int]:
    """(id стройки, id владельца) по ссылке для заказчика."""
    from app.security import decode_scoped_token

    project_id = decode_scoped_token(token or "", ctx.settings.secret_key, "report")
    project = ctx.db.one("SELECT id, owner_id FROM projects WHERE id = ?", (project_id,)) if project_id else None
    if not project:
        raise ServiceError(404, "Ссылка недействительна или истекла")
    return project["id"], project["owner_id"]


DEVIATION_COLUMNS = [("at", "Момент"), ("severity_label", "Важность"), ("kind", "Код"),
                     ("phase_name", "Этап"), ("message", "Отклонение"), ("zones", "Зоны"),
                     ("equipment", "Техника"), ("photo_ids", "Снимки")]


def deviations_csv(ctx: AppContext, user_id: int, building_id: int, limit: int = 1000) -> str:
    """Журнал отклонений для Excel: разделитель «;», BOM — чтобы кириллица открывалась без плясок."""
    rows = deviation_log(ctx, user_id, building_id, limit)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([title for _, title in DEVIATION_COLUMNS])
    for r in rows:
        writer.writerow([", ".join(map(str, r[key])) if isinstance(r[key], list) else (r[key] or "")
                         for key, _ in DEVIATION_COLUMNS])
    return "\ufeff" + buf.getvalue()


def history(ctx: AppContext, user_id: int, building_id: int, limit: int = 60) -> dict:
    """Динамика по записанным вердиктам: готовность, план и потери от простоя во времени."""
    require_building(ctx, user_id, building_id)
    rows = ctx.db.all(
        "SELECT at, status, completion_percent, planned_percent, idle_cost FROM verdicts "
        "WHERE building_id = ? ORDER BY at DESC, id DESC LIMIT ?", (building_id, max(2, min(limit, 500))))
    points = list(reversed(rows))
    delta = None
    done = [p for p in points if p["completion_percent"] is not None]
    if len(done) >= 2:
        delta = round(done[-1]["completion_percent"] - done[0]["completion_percent"], 1)
    return {"points": points, "change_percent": delta,
            "idle_total": sum(p["idle_cost"] or 0 for p in points),
            "currency": ctx.m.economics.get("currency", "₽")}
