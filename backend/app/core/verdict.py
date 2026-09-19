"""Вердикт по объекту на момент времени: что есть, чего нет, какие отклонения.

Входы: план (листовые работы с этапами и датами), снимки за окно анализа с детекциями,
список камер. Выход — структура, пригодная и для интерфейса, и для отчёта.

Типы отклонений:
* NO_DATA               — нет снимков за окно анализа;
* NO_ACTIVITY           — этап по графику, а техники на площадке нет вовсе;
* MISSING_EQUIPMENT     — нет обязательной техники этапа (темп работ под угрозой);
* BEHIND_SCHEDULE       — фактически идёт этап, который по графику уже должен был закончиться;
* AHEAD_OF_SCHEDULE     — фактически идёт этап, который по графику ещё не начался;
* NOT_IN_PLAN           — идут работы этапа, которого нет в плане объекта;
* UNEXPECTED_EQUIPMENT  — техника, не соответствующая текущим этапам;
* IDLE_EQUIPMENT        — техника стоит дольше порога;
* CAMERA_SILENT         — камера давно не присылала снимки;
* OUT_OF_VIEW           — часть работ по графику визуально не контролируется.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .methodology import Methodology
from .stage import observe, detect_stage
from .types import PhotoObs

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def planned_phases_at(tasks: list[dict], day: dt.date) -> dict[str, list[dict]]:
    """Этапы, активные по графику в указанный день: phase -> список работ."""
    out: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        if not t.get("phase") or not t.get("start_date"):
            continue
        if dt.date.fromisoformat(t["start_date"]) <= day <= dt.date.fromisoformat(t["end_date"]):
            out[t["phase"]].append(t)
    return dict(out)


def phase_spans(tasks: list[dict]) -> dict[str, tuple[dt.date, dt.date]]:
    spans: dict[str, tuple[dt.date, dt.date]] = {}
    for t in tasks:
        if not t.get("phase") or not t.get("start_date"):
            continue
        s, e = dt.date.fromisoformat(t["start_date"]), dt.date.fromisoformat(t["end_date"])
        if t["phase"] in spans:
            s0, e0 = spans[t["phase"]]
            spans[t["phase"]] = (min(s, s0), max(e, e0))
        else:
            spans[t["phase"]] = (s, e)
    return spans


def _labels(m: Methodology, classes) -> str:
    return ", ".join(m.label(c) for c in classes)


def _fmt(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def build_verdict(m: Methodology, at: dt.datetime, tasks: list[dict], photos: list[PhotoObs],
                  cameras: list[dict] | None = None) -> dict:
    cameras = cameras or []
    cfg = m.analysis
    window_start = at - dt.timedelta(hours=cfg["window_hours"])
    window = [p for p in photos if window_start <= p.taken_at <= at]
    planned = planned_phases_at(tasks, at.date())
    spans = phase_spans(tasks)
    planned_ids = set(planned)

    obs = observe(window, m)
    present = set(obs)
    stage = detect_stage(present, m, planned_ids)
    deviations: list[dict] = []

    def add(kind, severity, title, message, phase=None, classes=(), photo_ids=(), zones=()):
        deviations.append({
            "kind": kind, "severity": severity, "title": title, "message": message,
            "phase": phase, "phase_name": m.phase(phase).name if phase else None,
            "equipment": list(classes), "photo_ids": sorted(set(photo_ids))[-6:],
            "zones": sorted(set(z for z in zones if z)),
        })

    latest_ids = [p.id for p in sorted(window, key=lambda p: p.taken_at)[-3:]]
    all_zones = [p.zone for p in window]

    ever_seen = bool(photos)
    if not window:
        add("NO_DATA", "warning" if ever_seen else "info", "Нет снимков",
            (f"За последние {cfg['window_hours']} ч с объекта не поступило ни одного снимка — "
             "оценить ход работ невозможно.") if ever_seen else
            "С объекта ещё не поступало снимков. Загрузите фото или подключите камеру — "
            "до этого оценить ход работ нельзя.")

    # ---------- чек-лист по этапам графика ----------
    checklist = []
    for pid in sorted(planned_ids, key=lambda p: m.phase(p).sequence):
        ph = m.phase(pid)
        groups = []
        for g in ph.required:
            seen = [c for c in g if c in present]
            groups.append({"classes": list(g), "labels": [m.label(c) for c in g],
                           "present": bool(seen), "seen": seen})
        item = {
            "phase": pid, "name": ph.name, "observability": ph.observability, "hint": ph.hint,
            "tasks": [{"code": t["code"], "name": t["name"]} for t in planned[pid]][:12],
            "tasks_total": len(planned[pid]),
            "required": groups,
            "typical_present": [c for c in ph.typical if c in present],
            "unexpected_present": [c for c in ph.unexpected if c in present],
        }
        checklist.append(item)
        if not window:
            continue

        if ph.observability == "none":
            continue
        missing = [g for g in groups if not g["present"]]
        soft = ph.observability == "low"
        if ph.required and len(missing) == len(groups) and not present and not soft:
            add("NO_ACTIVITY", "critical", "Работы не ведутся",
                f"По графику идёт этап «{ph.name}», но на снимках нет никакой техники "
                f"(ожидается: {'; '.join(' или '.join(g['labels']) for g in missing)}).",
                pid, [], latest_ids, all_zones)
        elif missing:
            have = [c for g in groups if g["present"] for c in g["seen"]]
            need = "; ".join(" или ".join(g["labels"]) for g in missing)
            if have:
                msg = (f"На этапе «{ph.name}» обнаружено: {_labels(m, have)}, но отсутствует: {need}. "
                       "Возможно снижение темпа работ.")
            else:
                msg = f"На этапе «{ph.name}» не обнаружена обязательная техника: {need}."
            evidence = [i for c in have for i in obs[c].photo_ids] or latest_ids
            zones = [z for c in have for z in obs[c].zones] or all_zones
            add("MISSING_EQUIPMENT", "info" if soft else "warning", "Не хватает техники", msg,
                pid, [c for g in missing for c in g["classes"]], evidence, zones)

    # ---------- фактический этап против графика ----------
    reported_classes: set[str] = set()
    min_seq = min((m.phase(p).sequence for p in planned_ids), default=None)
    max_seq = max((m.phase(p).sequence for p in planned_ids), default=None)
    for pid in stage.resolved:
        if pid in planned_ids:
            continue
        ph = m.phase(pid)
        score = next(s for s in stage.ranking if s.phase == pid)
        evidence = [i for c in score.present_required for i in obs[c].photo_ids]
        zones = [z for c in score.present_required for z in obs[c].zones]
        reported_classes |= set(score.present_required)
        span = spans.get(pid)
        if span is None:
            add("NOT_IN_PLAN", "warning", "Работы вне плана",
                f"Техника ({_labels(m, score.present_required)}) указывает на этап «{ph.name}», "
                "которого нет в плане объекта. Проверьте план или назначение техники.",
                pid, score.present_required, evidence, zones)
        elif at.date() > span[1]:
            late = (at.date() - span[1]).days
            add("BEHIND_SCHEDULE", "critical" if late > 7 else "warning", "Отставание от графика",
                f"Фактически ведутся работы этапа «{ph.name}» ({_labels(m, score.present_required)}), "
                f"хотя по графику он завершён {_fmt(span[1])} — отставание {late} дн.",
                pid, score.present_required, evidence, zones)
        elif at.date() < span[0]:
            add("AHEAD_OF_SCHEDULE", "info", "Опережение графика",
                f"Обнаружены работы этапа «{ph.name}», запланированного с {_fmt(span[0])}.",
                pid, score.present_required, evidence, zones)
        elif min_seq is not None and max_seq is not None and not (min_seq <= ph.sequence <= max_seq):
            add("AHEAD_OF_SCHEDULE", "info", "Работы вне окна графика",
                f"Обнаружены работы этапа «{ph.name}».", pid, score.present_required, evidence, zones)

    # ---------- нетипичная техника ----------
    if planned_ids:
        expected_now = set().union(*(m.phase(p).expected_classes for p in planned_ids))
        unexpected_now = set().union(*(m.phase(p).unexpected for p in planned_ids))
        for cls in sorted(present - expected_now - reported_classes):
            where = [ph for ph in m.ordered_phases() if cls in ph.expected_classes]
            earlier = [ph.name for ph in where if min_seq is not None and ph.sequence < min_seq]
            later = [ph.name for ph in where if max_seq is not None and ph.sequence > max_seq]
            context = ""
            if earlier:
                context = f" Такая техника характерна для предыдущих этапов ({', '.join(earlier[-2:])}) — возможно отставание."
            elif later:
                context = f" Такая техника характерна для последующих этапов ({', '.join(later[:2])})."
            add("UNEXPECTED_EQUIPMENT", "warning" if cls in unexpected_now else "info",
                "Нетипичная техника",
                f"{m.label(cls)} не соответствует текущим этапам графика.{context}",
                None, [cls], obs[cls].photo_ids, obs[cls].zones)

    # ---------- простой техники (по последнему кадру каждой камеры) ----------
    idle_limit = m.activity["idle_alert_minutes"]
    required_now = {c for p in planned_ids for g in m.phase(p).required for c in g}
    last_by_camera: dict = {}
    for p in window:
        key = p.camera_id or f"photo-{p.id}"
        if key not in last_by_camera or p.taken_at > last_by_camera[key].taken_at:
            last_by_camera[key] = p
    idle_groups: dict[tuple, dict] = {}
    for p in last_by_camera.values():
        for d in p.detections:
            if d.activity == "idle" and d.idle_minutes >= idle_limit and d.confidence >= m.detection["min_confidence"]:
                g = idle_groups.setdefault((d.cls, p.camera_name or p.zone), {"n": 0, "min": 0, "photo": [], "zone": p.zone})
                g["n"] += 1
                g["min"] = max(g["min"], d.idle_minutes)
                g["photo"].append(p.id)
    for (cls, cam), g in idle_groups.items():
        where = f" (камера «{cam}»)" if cam else ""
        add("IDLE_EQUIPMENT", "warning" if cls in required_now else "info", "Техника простаивает",
            f"{m.label(cls)} ×{g['n']} стоит без перемещения не менее {g['min']} мин{where}.",
            None, [cls], g["photo"], [g["zone"]])

    # ---------- камеры ----------
    factor = cfg["camera_silence_factor"]
    for cam in cameras:
        if not cam.get("active") or cam.get("source_type") == "upload":
            continue
        last = cam.get("last_photo_at")
        limit = dt.timedelta(minutes=factor * int(cam.get("interval_min") or 30))
        if last is None or at - last > limit:
            add("CAMERA_SILENT", "warning", "Камера молчит",
                f"Камера «{cam['name']}» не присылала снимков "
                + (f"с {last.strftime('%d.%m %H:%M')}" if last else "ни разу") + ".",
                None, [], [], [cam.get("zone", "")])

    hidden = [m.phase(p).name for p in planned_ids if m.phase(p).observability == "none"]
    if hidden:
        add("OUT_OF_VIEW", "info", "Вне визуального контроля",
            "По графику идут работы, которые камеры наружного наблюдения не видят: "
            + ", ".join(f"«{h}»" for h in hidden) + ". Статус определяется по срокам.")

    deviations.sort(key=lambda d: SEVERITY_ORDER[d["severity"]])
    if not ever_seen or not tasks:
        status = "unknown"          # нечего оценивать: нет наблюдений или в плане нет активных работ
    elif any(d["severity"] == "critical" for d in deviations):
        status = "critical"
    elif any(d["severity"] == "warning" for d in deviations):
        status = "warning"
    else:
        status = "ok"

    return {
        "at": at.isoformat(timespec="minutes"),
        "window_hours": cfg["window_hours"],
        "photos_in_window": len(window),
        "status": status,
        "observed": ever_seen,
        "summary": _summary(status, deviations, stage.top_name, planned_ids, m, ever_seen, bool(tasks)),
        "planned_phases": [{"phase": p, "name": m.phase(p).name, "observability": m.phase(p).observability}
                           for p in sorted(planned_ids, key=lambda x: m.phase(x).sequence)],
        "stage": stage.to_dict(),
        "equipment": [o.to_dict() for o in sorted(obs.values(), key=lambda o: -o.photos)],
        "checklist": checklist,
        "deviations": deviations,
    }


def _summary(status: str, deviations: list[dict], top: str | None, planned: set[str], m: Methodology,
             ever_seen: bool = True, has_tasks: bool = True) -> str:
    if not has_tasks:
        return ("В плане объекта нет активных работ: включите нужные работы на шаге «План работ», "
                "иначе сверять снимки не с чем.")
    if not ever_seen:
        plan = ", ".join(f"«{m.phase(p).name}»" for p in sorted(planned, key=lambda x: m.phase(x).sequence))
        return (f"Снимков с объекта ещё не было — оценить ход работ нельзя. "
                f"По графику сейчас: {plan or 'нет активных работ'}.")
    plan = ", ".join(f"«{m.phase(p).name}»" for p in sorted(planned, key=lambda x: m.phase(x).sequence))
    fact = f"«{top}»" if top else "не определён"
    head = {"ok": "Работы соответствуют графику", "warning": "Есть отклонения",
            "critical": "Критические отклонения"}[status]
    crit = sum(1 for d in deviations if d["severity"] == "critical")
    warn = sum(1 for d in deviations if d["severity"] == "warning")
    return f"{head}. По графику: {plan or 'нет активных работ'}. Фактический этап: {fact}. " \
           f"Критических: {crit}, предупреждений: {warn}."
