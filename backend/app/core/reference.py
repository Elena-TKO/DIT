"""Заполнение справочных таблиц «тип объекта ↔ этап ↔ техника» из методики и норм.

Связь «тип объекта → этапы» выводится из справочника работ: этапы, к которым относятся работы,
отмеченные для типа объекта. «Этап → техника» — роли из методики и количество из ``norms.json``
с поправками по типу объекта. Таблицы — производные данные: пересобираются целиком при каждом старте.
"""
from __future__ import annotations

import json
from collections import Counter

from .catalog import OBJECT_TYPES, CatalogItem
from .methodology import Methodology
from .norms import requirements
from .planner import generate_plan


def phases_by_object_type(items, m: Methodology) -> dict[str, Counter]:
    out = {}
    for key in OBJECT_TYPES:
        tasks = generate_plan(items, key, "2025-01-01", "2026-12-31", m)
        out[key] = Counter(t.phase for t in tasks if t.phase and not t.is_summary)
    return out


def seed_reference(conn, m: Methodology, items: tuple[CatalogItem, ...] | list[CatalogItem], norms: dict) -> None:
    for table in ("phase_equipment", "object_type_phases", "equipment_types", "work_phases", "object_types"):
        conn.execute(f"DELETE FROM {table}")
    conn.executemany("INSERT INTO object_types (key, title) VALUES (?, ?)", list(OBJECT_TYPES.items()))
    conn.executemany(
        "INSERT INTO work_phases (id, name, sequence, observability, hint, rule, docs) VALUES (?,?,?,?,?,?,?)",
        [(p.id, p.name, p.sequence, p.observability, p.hint, norms["phase_norms"].get(p.id, {}).get("rule", ""),
          json.dumps(norms["phase_norms"].get(p.id, {}).get("docs", []), ensure_ascii=False))
         for p in m.ordered_phases()])
    rates = m.economics.get("shift_rates", {})
    conn.executemany("INSERT INTO equipment_types (cls, label, shift_rate) VALUES (?,?,?)",
                     [(c, v["label"], rates.get(c)) for c, v in m.equipment.items()])
    links, equipment = [], []
    for key, phases in phases_by_object_type(items, m).items():
        for phase, n in phases.items():
            links.append((key, phase, n))
            for r in requirements(m, norms, key, phase):
                equipment.append((key, phase, r["cls"], r["role"], r["group"], r["min_count"], r["max_count"]))
    conn.executemany("INSERT INTO object_type_phases (object_type, phase_id, tasks) VALUES (?,?,?)", links)
    conn.executemany("INSERT INTO phase_equipment (object_type, phase_id, cls, role, alt_group, min_count, max_count) "
                     "VALUES (?,?,?,?,?,?,?)", equipment)
