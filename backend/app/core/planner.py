"""Автоматическое формирование плана работ по объекту.

1. Из справочника берём работы, отмеченные галочкой для типа объекта.
2. Каждой работе назначаем технологический этап по правилам методики.
3. Сроки: окна этапов из типового графика (доли длительности стройки) масштабируются
   на даты объекта; работы внутри этапа распределяются последовательно с перекрытием.
Пользователь затем правит план интерактивно (включает/выключает работы, двигает даты).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict

from .catalog import CatalogItem
from .methodology import Methodology


@dataclass
class PlanTask:
    code: str
    parent_code: str | None
    name: str
    level: int
    phase: str | None          # None — для сводных (у них есть дочерние работы)
    is_summary: bool
    enabled: bool
    start_date: str | None
    end_date: str | None
    sort_order: int

    def to_dict(self) -> dict:
        return asdict(self)


def parse_date(value: str | dt.date | dt.datetime) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def _phase_windows(used: list[str], m: Methodology) -> dict[str, tuple[float, float]]:
    """Окна этапов, растянутые на весь срок (если у типа объекта нет части этапов)."""
    lo = min(m.phase(p).window[0] for p in used)
    hi = max(m.phase(p).window[1] for p in used)
    span = (hi - lo) or 1.0
    return {p: ((m.phase(p).window[0] - lo) / span, (m.phase(p).window[1] - lo) / span) for p in used}


def generate_plan(items: tuple[CatalogItem, ...] | list[CatalogItem], object_type: str,
                  start: str | dt.date, end: str | dt.date, m: Methodology) -> list[PlanTask]:
    start_d, end_d = parse_date(start), parse_date(end)
    if end_d <= start_d:
        raise ValueError("Дата окончания должна быть позже даты начала")
    by_code = {i.code: i for i in items}
    selected = [i for i in items if object_type in i.types]
    selected_codes = {i.code for i in selected}
    has_children = {i.parent_code for i in selected if i.parent_code in selected_codes}

    tasks: list[PlanTask] = []
    for it in selected:
        # Родитель мог не попасть в выборку — поднимаемся до ближайшего выбранного предка.
        parent = it.parent_code
        while parent and parent not in selected_codes:
            parent = by_code[parent].parent_code if parent in by_code else None
        summary = it.code in has_children
        tasks.append(PlanTask(
            code=it.code, parent_code=parent, name=it.name, level=it.level,
            phase=None if summary else m.phase_for_item(it, by_code, object_type),
            is_summary=summary, enabled=True, start_date=None, end_date=None, sort_order=it.order,
        ))
    schedule(tasks, start_d, end_d, m)
    return tasks


def schedule(tasks: list[PlanTask], start: dt.date, end: dt.date, m: Methodology) -> None:
    """Проставляет даты листовым работам и пересчитывает сводные."""
    leaves = [t for t in tasks if not t.is_summary]
    used = sorted({t.phase for t in leaves if t.phase}, key=lambda p: m.phase(p).sequence)
    if not used:
        return
    windows = _phase_windows(used, m)
    total_days = (end - start).days

    for phase in used:
        ph_tasks = sorted((t for t in leaves if t.phase == phase), key=lambda t: t.sort_order)
        f0, f1 = windows[phase]
        p_start = start + dt.timedelta(days=round(f0 * total_days))
        p_end = start + dt.timedelta(days=max(round(f1 * total_days), round(f0 * total_days) + 1))
        duration = (p_end - p_start).days
        n = len(ph_tasks)
        # Длительность одной работы — двойная «доля», чтобы соседние работы перекрывались.
        seg = duration if n == 1 else max(1, min(duration, round(2 * duration / n)))
        step = 0 if n == 1 else (duration - seg) / (n - 1)
        for i, t in enumerate(ph_tasks):
            s = p_start + dt.timedelta(days=round(i * step))
            t.start_date = s.isoformat()
            t.end_date = min(p_end, s + dt.timedelta(days=seg)).isoformat()
    recompute_summaries(tasks)


def recompute_summaries(tasks: list) -> None:
    """Сроки сводной работы = охват включённых дочерних работ. Работает с PlanTask и dict."""
    def get(t, k):
        return t[k] if isinstance(t, dict) else getattr(t, k)

    def put(t, k, v):
        if isinstance(t, dict):
            t[k] = v
        else:
            setattr(t, k, v)

    children: dict[str, list] = {}
    for t in tasks:
        if get(t, "parent_code"):
            children.setdefault(get(t, "parent_code"), []).append(t)

    def span(t):
        if not get(t, "is_summary"):
            if get(t, "enabled") and get(t, "start_date"):
                return get(t, "start_date"), get(t, "end_date")
            return None
        spans = [s for c in children.get(get(t, "code"), []) if get(c, "enabled") and (s := span(c))]
        if not spans:
            put(t, "start_date", None)
            put(t, "end_date", None)
            return None
        s, e = min(x[0] for x in spans), max(x[1] for x in spans)
        put(t, "start_date", s)
        put(t, "end_date", e)
        return s, e

    for t in tasks:
        if get(t, "parent_code") is None:
            span(t)


def effective_enabled(tasks: list[dict]) -> dict[str, bool]:
    """Работа активна, только если включена она и все её предки."""
    by_code = {t["code"]: t for t in tasks}
    cache: dict[str, bool] = {}

    def check(code: str) -> bool:
        if code in cache:
            return cache[code]
        t = by_code[code]
        ok = bool(t["enabled"]) and (check(t["parent_code"]) if t["parent_code"] in by_code else True)
        cache[code] = ok
        return ok

    return {c: check(c) for c in by_code}
