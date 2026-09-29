"""Нормы подбора техники: «тип объекта → этап → техника (роль, количество, нормативы)» и инженерные расчёты.

Состав техники этапа берётся из методики (``methodology.json``: обязательные группы, типичная и нетипичная
техника), количество и нормативная база — из ``norms.json`` (типовые диапазоны на одну захватку, с поправками
по типу объекта). Точное количество под конкретный объём работ даёт расчёт по классическим формулам
организации строительства (см. METHODOLOGY.md, раздел «Расчёт количества техники»):

* ``calc_excavation`` — экскаваторы и самосвалы на земляных работах;
* ``calc_concreting`` — бетононасосы и автобетоносмесители;
* ``calc_tower_crane`` — требуемые высота подъёма, вылет, грузоподъёмность и число башенных кранов.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .methodology import Methodology

NORMS_PATH = Path(__file__).resolve().parents[2] / "data" / "norms.json"
ROLE_LABEL = {"required": "обязательная", "typical": "типичная", "unexpected": "нетипичная"}


@lru_cache(maxsize=1)
def load_norms(path: str | None = None) -> dict:
    with open(path or NORMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def count_range(norms: dict, object_type: str | None, phase: str, cls: str) -> tuple[int, int] | None:
    """Диапазон количества машин класса на этапе с учётом поправок по типу объекта."""
    by_type = norms["counts"].get(object_type or "", {}).get(phase, {})
    if cls in by_type:
        return tuple(by_type[cls])
    base = norms["counts"]["default"].get(phase, {})
    return tuple(base[cls]) if cls in base else None


def requirements(m: Methodology, norms: dict, object_type: str | None, phase: str) -> list[dict]:
    """Техника этапа: роль, группа альтернатив, диапазон количества, нормативы."""
    ph = m.phase(phase)
    docs = norms["phase_norms"].get(phase, {}).get("docs", [])
    out: list[dict] = []
    seen: set[str] = set()

    def add(cls: str, role: str, group: int | None):
        if cls in seen:
            return
        seen.add(cls)
        rng = count_range(norms, object_type, phase, cls)
        if role == "typical" and rng and rng[1] == 0:
            return            # у этого типа объекта техника на этапе не применяется (например, башенный кран на дороге)
        lo = rng[0] if rng else (1 if role == "required" else 0)
        if role == "required":
            lo = max(1, lo)   # если машина из группы «или» работает, то хотя бы одна
        out.append({"cls": cls, "label": m.label(cls), "role": role, "role_label": ROLE_LABEL[role],
                    "group": group, "min_count": lo, "max_count": rng[1] if rng else None, "docs": docs})

    for gi, group in enumerate(ph.required):
        # в группе альтернатив «или» оставляем только применимые к типу объекта машины
        usable = [c for c in group if (count_range(norms, object_type, phase, c) or (0, 1))[1] > 0] or list(group)
        for cls in usable:
            add(cls, "required", gi)
    for cls in ph.typical:
        add(cls, "typical", None)
    for cls in ph.unexpected:
        add(cls, "unexpected", None)
    return out


def task_equipment(norms: dict, m: Methodology, name: str, phase: str | None) -> list[str]:
    """Техника для конкретной работы (подпункта этапа): правила по ключевым словам, иначе — обязательная этапа."""
    low = (name or "").lower()
    found: list[str] = []
    for rule in norms.get("task_rules", []):
        if any(k in low for k in rule["match"]):
            found += [c for c in rule["equipment"] if c not in found]
    if not found and phase:
        ph = m.phase(phase)
        found = [c for g in ph.required for c in g[:1]] or list(ph.typical[:2])
    return found


def quantity_fit(counts: dict[str, int], reqs: list[dict]) -> float:
    """Насколько количество машин на снимке соответствует нормам этапа (0..1).

    Машина в пределах диапазона — 1, машина этапа вне диапазона — 0,5, чужая для этапа — 0.
    """
    if not counts:
        return 0.0
    by_cls = {r["cls"]: r for r in reqs if r["role"] != "unexpected"}
    total = 0.0
    for cls, n in counts.items():
        r = by_cls.get(cls)
        if not r:
            continue
        hi = r["max_count"] if r["max_count"] is not None else n
        total += 1.0 if r["min_count"] <= n <= max(hi, r["min_count"]) else 0.5
    return round(total / len(counts), 3)


def check_counts(counts: dict[str, int], reqs: list[dict]) -> list[dict]:
    """Сверка техники со снимков с нормами этапа: чего не хватает, что в норме, что лишнее."""
    rows = []
    groups: dict[int, list[dict]] = {}
    for r in reqs:
        if r["role"] == "required":
            groups.setdefault(r["group"], []).append(r)
    for gi, items in groups.items():
        seen = sum(counts.get(r["cls"], 0) for r in items)
        need = min(r["min_count"] for r in items) or 1
        hi = max((r["max_count"] or 0) for r in items) or None
        state = "missing" if seen == 0 else "short" if seen < need else "excess" if hi and seen > hi else "ok"
        rows.append({"labels": [r["label"] for r in items], "classes": [r["cls"] for r in items], "role": "required",
                     "seen": seen, "min_count": need, "max_count": hi, "state": state})
    for r in reqs:
        n = counts.get(r["cls"], 0)
        if r["role"] == "typical" and n:
            hi = r["max_count"]
            rows.append({"labels": [r["label"]], "classes": [r["cls"]], "role": "typical", "seen": n,
                         "min_count": r["min_count"], "max_count": hi,
                         "state": "excess" if hi is not None and n > hi else "ok"})
        elif r["role"] == "unexpected" and n:
            rows.append({"labels": [r["label"]], "classes": [r["cls"]], "role": "unexpected", "seen": n,
                         "min_count": 0, "max_count": 0, "state": "unexpected"})
    return rows


# ------------------------------------------------------------------ расчёты
def _step(name: str, formula: str, value: float, unit: str = "") -> dict:
    return {"name": name, "formula": formula, "value": round(value, 2), "unit": unit}


def _positive(**values: float) -> None:
    for k, v in values.items():
        if v is None or v <= 0:
            raise ValueError(f"Параметр {k} должен быть больше нуля")


def calc_excavation(volume_m3: float, days: float, shifts: int = 1, shift_hours: float = 8, bucket_m3: float = 1.0,
                    cycle_s: float = 20, k_fill: float = 0.9, k_loose: float = 1.2, k_time: float = 0.75,
                    truck_t: float = 20, density_t_m3: float = 1.8, distance_km: float = 10,
                    speed_loaded_kmh: float = 25, speed_empty_kmh: float = 35, unload_min: float = 2,
                    maneuver_min: float = 2) -> dict:
    """Экскаваторы и самосвалы для разработки ``volume_m3`` грунта (в плотном теле) за ``days`` суток."""
    _positive(volume_m3=volume_m3, days=days, shifts=shifts, shift_hours=shift_hours, bucket_m3=bucket_m3,
              cycle_s=cycle_s, k_fill=k_fill, k_loose=k_loose, k_time=k_time, truck_t=truck_t,
              density_t_m3=density_t_m3, distance_km=distance_km, speed_loaded_kmh=speed_loaded_kmh,
              speed_empty_kmh=speed_empty_kmh)
    p_tech = 3600 * bucket_m3 * k_fill / (cycle_s * k_loose)
    p_shift = p_tech * shift_hours * k_time
    n_exc = math.ceil(volume_m3 / (p_shift * shifts * days))
    per_bucket = bucket_m3 * k_fill / k_loose                     # м³ грунта в плотном теле в одном ковше
    truck_m3 = truck_t / density_t_m3
    buckets = max(1, math.floor(truck_m3 / per_bucket))
    t_load = buckets * cycle_s / 60 / k_time
    t_cycle = t_load + 60 * distance_km / speed_loaded_kmh + 60 * distance_km / speed_empty_kmh + unload_min + maneuver_min
    per_exc = math.ceil(t_cycle / t_load)
    steps = [
        _step("Техническая производительность экскаватора", "Пт = 3600·q·kн / (tц·kр)", p_tech, "м³/ч"),
        _step("Сменная эксплуатационная производительность", "Псм = Пт·tсм·kв", p_shift, "м³/смену"),
        _step("Экскаваторов на объём в срок", "Nэ = ⌈V / (Псм·nсм·T)⌉", n_exc, "шт."),
        _step("Ковшей на один самосвал", "nк = ⌊(Qа/γ) / (q·kн/kр)⌋", buckets, "шт."),
        _step("Время погрузки самосвала", "tп = nк·tц / 60 / kв", t_load, "мин"),
        _step("Цикл самосвала", "Tц = tп + 60·L/vгр + 60·L/vпор + tр + tм", t_cycle, "мин"),
        _step("Самосвалов на один экскаватор", "Nа = ⌈Tц / tп⌉", per_exc, "шт."),
    ]
    return {"kind": "excavation", "title": "Земляные работы: экскаваторы и самосвалы", "steps": steps,
            "result": {"excavator": n_exc, "dump_truck": n_exc * per_exc},
            "docs": ["СП 45.13330.2017 «Земляные сооружения, основания и фундаменты»",
                     "ГЭСН 81-02-01-2020 «Сборник 1. Земляные работы»",
                     "МДС 12-81.2007 «Методические рекомендации по разработке и оформлению ПОС и ППР»"]}


def calc_concreting(volume_m3: float, hours: float, pump_m3h: float = 30, mixer_m3: float = 7,
                    distance_km: float = 10, speed_kmh: float = 25, load_min: float = 10,
                    wait_min: float = 5) -> dict:
    """Бетононасосы и автобетоносмесители для непрерывной укладки ``volume_m3`` за ``hours`` часов."""
    _positive(volume_m3=volume_m3, hours=hours, pump_m3h=pump_m3h, mixer_m3=mixer_m3,
              distance_km=distance_km, speed_kmh=speed_kmh)
    n_pump = math.ceil(volume_m3 / (pump_m3h * hours))
    t_unload = 60 * mixer_m3 / pump_m3h
    t_trip = 60 * distance_km / speed_kmh
    t_cycle = load_min + 2 * t_trip + t_unload + wait_min
    per_pump = math.ceil(t_cycle / t_unload)
    steps = [
        _step("Бетононасосов на объём в срок", "Nн = ⌈V / (Пн·T)⌉", n_pump, "шт."),
        _step("Разгрузка одного миксера в насос", "tв = 60·Vм / Пн", t_unload, "мин"),
        _step("Цикл автобетоносмесителя", "Tц = tз + 2·60·L/v + tв + tож", t_cycle, "мин"),
        _step("Миксеров на один насос", "Nм = ⌈Tц / tв⌉", per_pump, "шт."),
    ]
    warnings = []
    if t_trip > 90:
        warnings.append("Доставка дольше 90 минут: проверьте сохраняемость смеси по ГОСТ 7473-2010 и договор с БСУ.")
    return {"kind": "concreting", "title": "Бетонирование: насосы и миксеры", "steps": steps,
            "result": {"concrete_pump": n_pump, "concrete_mixer": n_pump * per_pump}, "warnings": warnings,
            "docs": ["СП 70.13330.2012 «Несущие и ограждающие конструкции»",
                     "ГОСТ 7473-2010 «Смеси бетонные. Технические условия»"]}


def calc_tower_crane(building_height_m: float, building_width_m: float, building_length_m: float,
                     element_t: float = 3.0, rigging_t: float = 0.3, element_height_m: float = 3.0,
                     sling_height_m: float = 4.0, clearance_m: float = 1.0, axis_offset_m: float = 6.0,
                     crane_reach_m: float | None = None) -> dict:
    """Требуемые параметры башенного крана и число кранов по длине здания."""
    _positive(building_height_m=building_height_m, building_width_m=building_width_m,
              building_length_m=building_length_m, element_t=element_t)
    h_req = building_height_m + clearance_m + element_height_m + sling_height_m
    reach_req = axis_offset_m + building_width_m
    load_req = element_t + rigging_t
    reach = crane_reach_m or math.ceil(reach_req * 1.3)
    if reach <= reach_req:
        raise ValueError("Вылет крана меньше требуемого: кран не достаёт до дальней грани здания")
    coverage = 2 * math.sqrt(reach ** 2 - reach_req ** 2)          # длина фронта, где кран достаёт дальнюю грань
    n_cranes = max(1, math.ceil(building_length_m / coverage))
    steps = [
        _step("Требуемая высота подъёма крюка", "Hк = h0 + hз + hэ + hс", h_req, "м"),
        _step("Требуемый вылет", "Lк = c + B", reach_req, "м"),
        _step("Требуемая грузоподъёмность на вылете", "Qк = Qэ + Qстр", load_req, "т"),
        _step("Вылет выбранного крана", "R", reach, "м"),
        _step("Фронт работ одного крана по длине здания", "lф = 2·√(R² − Lк²)", coverage, "м"),
        _step("Кранов по длине здания", "Nкр = ⌈Lзд / lф⌉", n_cranes, "шт."),
    ]
    return {"kind": "tower_crane", "title": "Каркас: подбор башенного крана", "steps": steps,
            "result": {"tower_crane": n_cranes, "hook_height_m": round(h_req, 1), "reach_m": round(reach_req, 1),
                       "load_t": round(load_req, 2)},
            "docs": ["ФНП «Правила безопасности ОПО, на которых используются подъёмные сооружения» (приказ Ростехнадзора № 461)",
                     "СНиП 12-03-2001 «Безопасность труда в строительстве. Часть 1»",
                     "МДС 12-46.2008 «Методические рекомендации по разработке и оформлению ПОС, ПОР и ППР»"]}


CALCULATORS = {"excavation": calc_excavation, "concreting": calc_concreting, "tower_crane": calc_tower_crane}
# Какой расчёт уместен на каком этапе
PHASE_CALC = {"EXCAVATION": "excavation", "DEMOLITION": "excavation", "BACKFILL": "excavation",
              "FOUNDATION": "concreting", "PILING": "concreting", "BRIDGE": "concreting",
              "FRAME": "tower_crane", "ENVELOPE": "tower_crane"}
