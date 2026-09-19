"""Перевод наблюдаемого простоя в деньги.

Считается только то, что видно на снимках: техника стоит на месте N минут — это прямые потери
по ставке аренды. Дни отставания в рубли НЕ переводятся: умножать задержку графика на аренду
всего парка некорректно (техника в эти дни не стоит под счётчик), а завышенная цифра
разрушает доверие ко всем остальным. Для отставания показывается справка — во сколько
обходится один день работы замеченной на объекте техники.

Ставки берутся из методики (`economics.shift_rates`) и заменяются договорными.
"""
from __future__ import annotations

from .methodology import Methodology
from .types import PhotoObs


def idle_losses(m: Methodology, photos: list[PhotoObs]) -> dict:
    """Стоимость простоя техники за окно анализа.

    ``idle_minutes`` накапливается по ходу серии кадров, поэтому за серию берётся её максимум:
    иначе один и тот же простой посчитался бы несколько раз.
    """
    econ = m.economics or {}
    rates = econ.get("shift_rates", {})
    shift = max(1, econ.get("shift_hours", 8))
    min_conf = m.detection["min_confidence"]
    limit = m.activity["idle_alert_minutes"]

    runs: dict[tuple, int] = {}          # (камера, класс) -> минуты текущей серии
    totals: dict[str, int] = {}
    for p in sorted(photos, key=lambda x: x.taken_at):
        seen: dict[tuple, int] = {}
        for d in p.detections:
            if d.confidence < min_conf:
                continue
            key = (p.camera_id, d.cls)
            if d.activity == "idle":
                seen[key] = max(seen.get(key, 0), d.idle_minutes)
        for key, minutes in seen.items():
            if minutes < runs.get(key, 0):      # серия прервалась — закрываем предыдущую
                totals[key[1]] = totals.get(key[1], 0) + runs[key]
            runs[key] = minutes
        for key in [k for k in runs if k not in seen]:
            totals[key[1]] = totals.get(key[1], 0) + runs.pop(key)
    for key, minutes in runs.items():
        totals[key[1]] = totals.get(key[1], 0) + minutes

    rows, total = [], 0.0
    for cls, minutes in totals.items():
        if minutes < limit:
            continue
        cost = round(minutes / 60 * rates.get(cls, 0) / shift)
        rows.append({"cls": cls, "label": m.label(cls), "minutes": minutes, "cost": cost})
        total += cost
    rows.sort(key=lambda r: -r["cost"])
    return {
        "currency": econ.get("currency", "₽"),
        "note": econ.get("note", ""),
        "idle_total": round(total),
        "idle_minutes": sum(r["minutes"] for r in rows),
        "by_equipment": rows,
    }


def daily_fleet_cost(m: Methodology, photos: list[PhotoObs]) -> dict:
    """Справка: во сколько обходится день работы техники, замеченной на объекте."""
    rates = (m.economics or {}).get("shift_rates", {})
    min_conf = m.detection["min_confidence"]
    classes = {d.cls for p in photos for d in p.detections if d.confidence >= min_conf}
    return {"daily_fleet_cost": sum(rates.get(c, 0) for c in classes),
            "fleet": sorted(m.label(c) for c in classes)}


def summary(m: Methodology, timeline: dict, window_photos: list[PhotoObs], all_photos: list[PhotoObs]) -> dict:
    """Экономика объекта: измеренный простой в рублях + справочная стоимость дня работы парка."""
    idle = idle_losses(m, window_photos)
    fleet = daily_fleet_cost(m, all_photos)
    # Простой считается по соседним кадрам одной камеры: без привязки к камере он неизмерим,
    # и об этом нужно сказать прямо, а не показывать ноль как факт.
    measurable = any(p.camera_id for p in window_photos)
    return {**idle, **fleet,
            "delay_days": timeline.get("max_delay_days") or 0,
            "measured_total": idle["idle_total"],
            "photos_in_window": len(window_photos),
            "idle_measurable": measurable}
