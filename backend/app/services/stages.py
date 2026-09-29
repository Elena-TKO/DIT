"""Этапы работ объекта: сводка «план ↔ факт по снимкам» для Ганта и таблицы «Все работы»,
и страница отдельного этапа со всеми его снимками и результатами анализа."""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from app.core.norms import PHASE_CALC, check_counts, requirements, task_equipment
from app.core.stage import observe
from .analysis import default_at
from .common import AppContext, ServiceError, iso, now, require_building
from .photos import check_phase, ensure_photo_phases, list_photos, load_obs
from .projects import get_plan


def _photo_stats(ctx: AppContext, building_id: int) -> dict[str, dict]:
    """Снимки по этапам: число, первая/последняя дата, отметки по дням для таймлайна."""
    stats: dict[str, dict] = {}
    for r in ctx.db.all(
            "SELECT phase, COUNT(*) AS n, MIN(taken_at) AS first, MAX(taken_at) AS last, MAX(id) AS last_id, "
            "SUM(phase_source = 'manual') AS manual FROM photos WHERE building_id = ? AND phase IS NOT NULL "
            "GROUP BY phase", (building_id,)):
        stats[r["phase"]] = {"photos": r["n"], "photo_start": r["first"][:10], "photo_end": r["last"][:10],
                             "cover_photo_id": r["last_id"], "manual_photos": r["manual"] or 0, "photo_days": []}
    for r in ctx.db.all(
            "SELECT phase, substr(taken_at, 1, 10) AS day, COUNT(*) AS n, MAX(id) AS photo_id FROM photos "
            "WHERE building_id = ? AND phase IS NOT NULL GROUP BY phase, day ORDER BY day", (building_id,)):
        stats[r["phase"]]["photo_days"].append({"date": r["day"], "photos": r["n"], "photo_id": r["photo_id"]})
    return stats


def _timeline_rows(ctx: AppContext, building: dict) -> dict:
    from .analysis import _compute
    _, tl, _, _ = _compute(ctx, building, default_at(ctx, building["id"]))
    return tl


def stage_list(ctx: AppContext, user_id: int, building_id: int) -> dict:
    """Все этапы объекта: плановые сроки, факт по снимкам, статус, техника, подпункты работ."""
    building = require_building(ctx, user_id, building_id)
    ensure_photo_phases(ctx, building_id)
    plan = get_plan(ctx, user_id, building_id)
    tl = _timeline_rows(ctx, building)
    tl_rows = {r["phase"]: r for r in tl["rows"]}
    stats = _photo_stats(ctx, building_id)
    otype = building["object_type"]

    by_phase: dict[str, list[dict]] = defaultdict(list)
    for t in plan["tasks"]:
        if t["phase"] and not t["is_summary"] and t["active"]:
            by_phase[t["phase"]].append(t)

    stages = []
    for ph in plan["phases"]:
        pid = ph["phase"]
        row = tl_rows.get(pid, {})
        st = stats.get(pid, {"photos": 0, "photo_start": None, "photo_end": None, "cover_photo_id": None,
                             "manual_photos": 0, "photo_days": []})
        reqs = requirements(ctx.m, ctx.norms, otype, pid)
        tasks = [{"id": t["id"], "code": t["code"], "name": t["name"], "start_date": t["start_date"],
                  "end_date": t["end_date"], "delay_days": next((x["delay_days"] for x in row.get("tasks", [])
                                                                if x["code"] == t["code"]), None),
                  "equipment": [{"cls": c, "label": ctx.m.label(c)} for c in task_equipment(ctx.norms, ctx.m, t["name"], pid)]}
                 for t in sorted(by_phase[pid], key=lambda x: (x["start_date"] or "", x["sort_order"]))]
        stages.append({
            "phase": pid, "name": ph["name"], "observability": ph["observability"],
            "start": ph["start"], "end": ph["end"], "tasks_count": ph["tasks"],
            "status": row.get("status"), "status_label": row.get("status_label"), "color": row.get("color"),
            "delay_days": row.get("delay_days"),
            **st,
            "equipment": [r for r in reqs if r["role"] != "unexpected"],
            "tasks": tasks,
        })
        # у этапов без плановых работ снимков быть не может, но снимки «чужих» этапов тоже показываем ниже
    unplanned = [
        {"phase": p, "name": ctx.m.phase(p).name, "observability": ctx.m.phase(p).observability, **s}
        for p, s in stats.items() if p not in {x["phase"] for x in stages}]
    unassigned = ctx.db.one("SELECT COUNT(*) AS n FROM photos WHERE building_id = ? AND phase IS NULL",
                            (building_id,))["n"]
    return {
        "building_id": building_id, "object_type": otype,
        "start": plan["start_date"], "end": plan["end_date"], "today": dt.date.today().isoformat(),
        "analysis_at": tl["at"], "observed": tl["observed"],
        "stages": stages, "unplanned": unplanned, "unassigned_photos": unassigned,
        "legend": tl["legend"],
    }


def stage_detail(ctx: AppContext, user_id: int, building_id: int, phase: str) -> dict:
    """Страница этапа: сроки, нужная техника с нормами, все снимки этапа и анализ каждого."""
    building = require_building(ctx, user_id, building_id)
    phase = check_phase(ctx, phase)
    if not phase:
        raise ServiceError(422, "Не указан этап")
    ensure_photo_phases(ctx, building_id)
    summary = stage_list(ctx, user_id, building_id)
    info = next((s for s in summary["stages"] if s["phase"] == phase), None)
    ph = ctx.m.phase(phase)
    reqs = requirements(ctx.m, ctx.norms, building["object_type"], phase)
    photos = list_photos(ctx, user_id, building_id, 500, 0, phase=phase)["items"]

    # анализ каждого снимка: техника и её количество против норм этапа
    for p in photos:
        counts = {e["cls"]: e["count"] for e in p["equipment"]}
        p["check"] = check_counts(counts, reqs)
        p["mismatch"] = bool(p.get("auto_phase") and p["auto_phase"] != phase)
    # сводно по этапу: максимум одновременно на одном кадре
    obs = [o for o in load_obs(ctx, building_id) if o.phase == phase]
    seen = observe(obs, ctx.m)
    peak = {cls: o.max_count for cls, o in seen.items()}
    norms = ctx.norms["phase_norms"].get(phase, {})
    return {
        "building": {"id": building["id"], "name": building["name"], "object_type": building["object_type"],
                     "project_id": building["project_id"]},
        "phase": phase, "name": ph.name, "observability": ph.observability, "hint": ph.hint,
        "rule": norms.get("rule", ""), "docs": norms.get("docs", []),
        "stage": info or {"phase": phase, "name": ph.name, "photos": len(photos), "tasks": [], "start": None, "end": None},
        "requirements": reqs,
        "check": check_counts(peak, reqs),
        "observed": [o.to_dict() for o in seen.values()],
        "photos": photos,
        "calc": PHASE_CALC.get(phase),
        "stages": [{"phase": s["phase"], "name": s["name"], "photos": s["photos"]} for s in summary["stages"]],
    }


def norms_matrix(ctx: AppContext, object_type: str | None = None) -> dict:
    """Справочник «тип объекта ↔ этап ↔ техника» из БД — то, что видят судьи и внешние системы."""
    types = ctx.db.all("SELECT key, title FROM object_types ORDER BY rowid")
    if object_type and object_type not in {t["key"] for t in types}:
        raise ServiceError(422, f"Неизвестный тип объекта: {object_type}")
    phases = {r["id"]: {**r, "docs": json.loads(r["docs"])} for r in ctx.db.all("SELECT * FROM work_phases ORDER BY sequence")}
    where, params = ("WHERE otp.object_type = ?", [object_type]) if object_type else ("", [])
    links = ctx.db.all(
        "SELECT otp.object_type, otp.phase_id, otp.tasks FROM object_type_phases otp "
        f"JOIN work_phases wp ON wp.id = otp.phase_id {where} ORDER BY otp.object_type, wp.sequence", params)
    eq = ctx.db.all(
        "SELECT pe.*, et.label, et.shift_rate FROM phase_equipment pe JOIN equipment_types et ON et.cls = pe.cls "
        + ("WHERE pe.object_type = ? " if object_type else "")
        + "ORDER BY pe.object_type, pe.phase_id, CASE pe.role WHEN 'required' THEN 0 WHEN 'typical' THEN 1 ELSE 2 END, "
          "pe.alt_group, pe.cls", params)
    by_link: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in eq:
        by_link[(e["object_type"], e["phase_id"])].append(
            {"cls": e["cls"], "label": e["label"], "role": e["role"], "alt_group": e["alt_group"],
             "min_count": e["min_count"], "max_count": e["max_count"], "shift_rate": e["shift_rate"]})
    out: dict[str, dict] = {t["key"]: {"key": t["key"], "title": t["title"], "phases": []} for t in types
                            if not object_type or t["key"] == object_type}
    for link in links:
        p = phases[link["phase_id"]]
        out[link["object_type"]]["phases"].append({
            "phase": p["id"], "name": p["name"], "observability": p["observability"], "tasks": link["tasks"],
            "rule": p["rule"], "docs": p["docs"], "equipment": by_link[(link["object_type"], link["phase_id"])]})
    return {"generated_at": iso(now()), "object_types": list(out.values())}
