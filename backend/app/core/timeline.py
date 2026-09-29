"""Таймлайн объекта: статусы этапов цветом, степень завершённости и прогноз задержки.

Факт по этапу — «свидетельства»: снимки, на которых этап подтверждён техникой
(см. ``stage.resolve_phases``, с учётом графика на момент снимка).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .methodology import Methodology
from .stage import rank_phases, resolve_phases
from .types import PhotoObs
from .verdict import planned_phases_at

STATUSES = {
    "planned":      {"label": "Запланировано",             "color": "#A3A9AF"},
    "awaiting":     {"label": "Ожидается начало",          "color": "#CDD2D6"},
    "on_track":     {"label": "Идёт по графику",           "color": "#2F8F5B"},
    "at_risk":      {"label": "Риск отставания",           "color": "#E3A008"},
    "delayed":      {"label": "Отставание",                "color": "#C9372C"},
    "done":         {"label": "Выполнено",                 "color": "#3C6E9F"},
    "ahead":        {"label": "Опережение",                "color": "#1C9A96"},
    "unobservable": {"label": "Идёт по графику (вне камер)", "color": "#7D65A8"},
    "unconfirmed":  {"label": "Не подтверждено камерами",  "color": "#B7791F"},
}


def photo_evidence(photos: list[PhotoObs], tasks: list[dict], m: Methodology) -> list[tuple[PhotoObs, list[str]]]:
    """Для каждого снимка — подтверждённые им этапы."""
    min_conf = m.detection["min_confidence"]
    out = []
    for p in photos:
        present = {d.cls for d in p.detections if d.confidence >= min_conf and d.cls in m.equipment}
        if not present:
            out.append((p, []))
            continue
        planned = set(planned_phases_at(tasks, p.taken_at.date()))
        phases = resolve_phases(rank_phases(present, m), present, planned, m)
        # снимок, загруженный пользователем на конкретный этап, подтверждает его,
        # если на кадре есть хотя бы часть техники этого этапа
        if (p.phase_source == "manual" and p.phase in m.phases and p.phase not in phases
                and present & m.phase(p.phase).expected_classes):
            phases = [*phases, p.phase]
        out.append((p, phases))
    return out


def _status(ph_obs: str, s: dt.date, e: dt.date, at: dt.date, ev: list[dt.date],
            later_evidence: bool, m: Methodology, observed: bool = True,
            since: dt.date | None = None) -> tuple[str, int]:
    """Статус интервала [s, e] на дату ``at`` и задержка в днях.

    ``since`` — дата первого снимка: до неё наблюдений не было, поэтому ни «выполнено»,
    ни «отставание» ставить нельзя — только «не подтверждено».
    """
    cfg = m.analysis
    if not observed:
        return ("planned", 0) if at < s else ("unconfirmed", 0)
    recent = dt.timedelta(days=cfg["recent_days"])
    duration = max(1, (e - s).days)
    grace = dt.timedelta(days=max(cfg["start_grace_days"], round(cfg["start_grace_fraction"] * duration)))
    ev = [d for d in ev if d <= at]

    if ph_obs in ("none", "low"):
        # эти этапы камеры не видят по определению: статус по срокам, как и описано в методике
        if at < s:
            return "planned", 0
        return ("unobservable", 0) if at <= e else ("done", 0)

    if since and e < since and not ev and not later_evidence:
        # этап закончился до первого снимка, и подтверждений более поздних этапов тоже нет:
        # камеры его просто не застали — это не отставание
        return ("planned", 0) if at < s else ("unconfirmed", 0)

    if at < s:
        return ("ahead", 0) if any(at - d <= recent for d in ev) else ("planned", 0)
    if at <= e:
        if any(at - d <= recent for d in ev):
            return "on_track", 0
        if any(d >= s - recent for d in ev):
            return "at_risk", 0
        if at - s <= grace:
            return "awaiting", 0
        if later_evidence:          # следующие этапы идут — этап, вероятно, вне обзора камер
            return "unconfirmed", 0
        started = max(s + grace, since) if since else s + grace
        return ("delayed", (at - started).days) if at > started else ("unconfirmed", 0)
    last = max(ev) if ev else None
    if last and last > e and at - last <= recent:
        return "delayed", (at - e).days
    if last and last >= s - recent:
        return "done", 0
    if later_evidence:
        return "done", 0
    return "unconfirmed", 0


def _progress(status: str, s: dt.date, e: dt.date, at: dt.date) -> float:
    elapsed = min(1.0, max(0.0, (at - s).days / max(1, (e - s).days)))
    if status == "delayed":
        return 0.85 if at > e else 0.0      # после срока работы почти закончены / не начаты вовсе
    return {
        "done": 1.0, "unconfirmed": 0.8, "planned": 0.0, "awaiting": 0.0, "ahead": 0.1,
        "on_track": elapsed, "unobservable": elapsed, "at_risk": 0.8 * elapsed,
    }[status]


def build_timeline(m: Methodology, at: dt.datetime, tasks: list[dict], photos: list[PhotoObs],
                   building_start: str | None = None, building_end: str | None = None) -> dict:
    day = at.date()
    # Без единого снимка оценивать выполнение нечем: статусы ставятся только по плану,
    # а готовность, SPI и риск остаются неизвестными, а не считаются «по срокам».
    seen = [p.taken_at.date() for p in photos if p.taken_at <= at]
    observed = bool(seen)
    # Отставание нельзя вменять за период, когда камеры ещё не снимали
    since = min(seen) if seen else None
    leaves = [t for t in tasks if t.get("phase") and t.get("start_date")]
    evidence = photo_evidence([p for p in photos if p.taken_at <= at], leaves, m)

    ev_dates: dict[str, list[dt.date]] = defaultdict(list)
    ev_points: dict[str, dict[str, dict]] = defaultdict(dict)
    for p, phases in evidence:
        for ph in phases:
            ev_dates[ph].append(p.taken_at.date())
            key = p.taken_at.date().isoformat()
            point = ev_points[ph].setdefault(key, {"date": key, "photos": 0, "photo_id": p.id})
            point["photos"] += 1

    by_phase: dict[str, list[dict]] = defaultdict(list)
    for t in leaves:
        by_phase[t["phase"]].append(t)

    rows = []
    weights = planned_sum = actual_sum = 0.0
    max_delay = 0
    for pid in sorted(by_phase, key=lambda p: m.phase(p).sequence):
        ph = m.phase(pid)
        items = by_phase[pid]
        s = min(dt.date.fromisoformat(t["start_date"]) for t in items)
        e = max(dt.date.fromisoformat(t["end_date"]) for t in items)
        later = any(m.phase(q).sequence > ph.sequence and any(d > s for d in ds) for q, ds in ev_dates.items())
        status, delay = _status(ph.observability, s, e, day, ev_dates.get(pid, []), later, m, observed, since)
        if ph.observability in ("high", "medium"):
            max_delay = max(max_delay, delay)

        task_rows = []
        for t in sorted(items, key=lambda x: (x["start_date"], x.get("sort_order", 0))):
            ts, te = dt.date.fromisoformat(t["start_date"]), dt.date.fromisoformat(t["end_date"])
            st, dl = _status(ph.observability, ts, te, day, ev_dates.get(pid, []), later, m, observed, since)
            if st == "ahead" and status != "ahead":
                st = "planned"      # свидетельства этапа относятся к уже идущим работам этого этапа
            w = max(1, (te - ts).days)
            weights += w
            planned_sum += w * min(1.0, max(0.0, (day - ts).days / w))
            actual_sum += w * _progress(st, ts, te, day)
            task_rows.append({"id": t.get("id"), "code": t["code"], "name": t["name"],
                              "start": t["start_date"], "end": t["end_date"],
                              "status": st, "color": STATUSES[st]["color"], "delay_days": dl})

        ev = sorted(ev_dates.get(pid, []))
        rows.append({
            "phase": pid, "name": ph.name, "observability": ph.observability,
            "start": s.isoformat(), "end": e.isoformat(),
            "status": status, "status_label": STATUSES[status]["label"], "color": STATUSES[status]["color"],
            "delay_days": delay,
            "actual_start": ev[0].isoformat() if ev else None,
            "actual_last": ev[-1].isoformat() if ev else None,
            "evidence": sorted(ev_points[pid].values(), key=lambda x: x["date"]),
            "tasks": task_rows,
        })

    planned_pct = round(100 * planned_sum / weights, 1) if weights else 0.0
    completion = round(100 * actual_sum / weights, 1) if (weights and observed) else None
    spi = round(completion / planned_pct, 2) if (completion is not None and planned_pct > 0) else None

    starts = [r["start"] for r in rows]
    ends = [r["end"] for r in rows]
    b_start = building_start or (min(starts) if starts else None)
    b_end = building_end or (max(ends) if ends else None)
    # Положение полос в процентах от срока объекта (для простых диаграмм в отчёте)
    if b_start and b_end:
        t0, t1 = dt.date.fromisoformat(b_start[:10]), dt.date.fromisoformat(b_end[:10])
        total = max(1, (t1 - t0).days)
        for r in rows:
            left = max(0.0, (dt.date.fromisoformat(r["start"]) - t0).days / total * 100)
            right = min(100.0, (dt.date.fromisoformat(r["end"]) - t0).days / total * 100)
            r["left"], r["width"] = round(left, 2), round(max(0.5, right - left), 2)

    forecast_end = None
    if b_end:
        forecast_end = (dt.date.fromisoformat(b_end) + dt.timedelta(days=max_delay)).isoformat()

    if not observed or not rows:
        risk = "unknown"
    elif max_delay > 14 or (spi is not None and planned_pct >= 5 and spi < 0.8):
        risk = "high"
    elif max_delay > 0 or (spi is not None and planned_pct >= 5 and spi < 0.95):
        risk = "medium"
    else:
        risk = "low"

    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1

    return {
        "at": at.isoformat(timespec="minutes"),
        "start": b_start, "end": b_end,
        "rows": rows,
        "legend": [{"status": k, **v} for k, v in STATUSES.items()],
        "status_counts": dict(counts),
        "observed": observed,
        "completion_percent": completion,
        "planned_percent": planned_pct,
        "spi": spi,
        "max_delay_days": max_delay,
        "forecast_end": forecast_end,
        "delay_risk": risk,
    }
