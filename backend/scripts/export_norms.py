"""Обновляет в METHODOLOGY.md приложения, которые должны совпадать с кодом:

* нормы техники «тип объекта → этап → техника (количество)» — из methodology.json и norms.json;
* пример расчётов — вызовом тех же функций, что работают в API.

    python scripts/export_norms.py            # переписать блоки между маркерами
    python scripts/export_norms.py --check    # только проверить, что документ актуален (для CI и тестов)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.catalog import OBJECT_TYPES, load_catalog  # noqa: E402
from app.core.methodology import load_methodology  # noqa: E402
from app.core.norms import calc_concreting, calc_excavation, calc_tower_crane, load_norms, requirements  # noqa: E402
from app.core.reference import phases_by_object_type  # noqa: E402

DOC = ROOT.parent / "METHODOLOGY.md"
OBS = {"high": "высокая", "medium": "средняя", "low": "низкая", "none": "нет"}


def _rng(r: dict) -> str:
    lo, hi = r["min_count"], r["max_count"]
    if hi is None:
        return f"≥{lo}" if lo else "по потребности"
    return f"{lo}" if lo == hi else f"{lo}–{hi}"


def norms_table(m, norms, catalog) -> str:
    by_type = phases_by_object_type(catalog, m)
    tables: dict[str, list[str]] = {}
    for key in OBJECT_TYPES:
        rows = []
        for ph in m.ordered_phases():
            if ph.id not in by_type[key]:
                continue
            reqs = requirements(m, norms, key, ph.id)
            groups: dict[int, list[str]] = {}
            for r in reqs:
                if r["role"] == "required":
                    groups.setdefault(r["group"], []).append(f"{r['label']} {_rng(r)}")
            lead = "; ".join(" или ".join(g) for g in groups.values()) or "—"
            comp = ", ".join(f"{r['label']} {_rng(r)}" for r in reqs if r["role"] == "typical") or "—"
            odd = ", ".join(r["label"] for r in reqs if r["role"] == "unexpected") or "—"
            rows.append(f"| {ph.name} | {lead} | {comp} | {odd} | {OBS[ph.observability]} |")
        tables[key] = rows
    # одинаковые таблицы у разных типов объектов показываем один раз
    groups: list[tuple[list[str], list[str]]] = []
    for key, rows in tables.items():
        for names, same in groups:
            if same == rows:
                names.append(OBJECT_TYPES[key])
                break
        else:
            groups.append(([OBJECT_TYPES[key]], rows))
    out = []
    for names, rows in groups:
        out += [f"#### {', '.join(names)}", "",
                "| Этап | Ведущая машина (обязательно, шт. на захватку) | Комплект (типично, шт.) | Нетипична | Видно камерами |",
                "|---|---|---|---|---|", *rows, ""]
    out.append("Нормативная база по этапам:")
    out.append("")
    for ph in m.ordered_phases():
        docs = norms["phase_norms"].get(ph.id, {}).get("docs", [])
        out.append(f"- **{ph.name}** — {'; '.join(docs) or '—'}")
    return "\n".join(out).rstrip() + "\n"


def _calc_block(res: dict) -> list[str]:
    lines = ["| Величина | Формула | Значение |", "|---|---|---|"]
    num = lambda v: f"{v:g}".replace(".", ",")   # noqa: E731 — русская десятичная запятая
    lines += [f"| {s['name']} | `{s['formula']}` | {num(s['value'])} {s['unit']} |" for s in res["steps"]]
    return lines


def calc_examples() -> str:
    ex = calc_excavation(volume_m3=20000, days=20)
    con = calc_concreting(volume_m3=480, hours=16)
    cr = calc_tower_crane(building_height_m=75, building_width_m=18, building_length_m=120)
    out = ["**Пример 1. Котлован 20 000 м³ за 20 рабочих дней**, одна смена 8 ч, экскаватор с ковшом 1,0 м³ "
           "(tц = 20 с, kн = 0,9, kр = 1,2, kв = 0,75), самосвалы 20 т, грунт 1,8 т/м³, плечо вывоза 10 км "
           "(25 км/ч гружёным, 35 км/ч порожним), разгрузка и манёвры по 2 мин.", "",
           *_calc_block(ex), "",
           f"Итог: **{ex['result']['excavator']} экскаватора и {ex['result']['dump_truck']} самосвалов**. "
           "Норма на захватку в справочнике — 1–3 экскаватора и 2–8 самосвалов: расчёт показывает, что при плече 10 км "
           "одного экскаватора обслуживают 9 самосвалов, то есть типовой диапазон нужно поднять — ровно для этого "
           "расчёт и нужен.", "",
           "**Пример 2. Бетонирование фундаментной плиты 480 м³ за 16 ч**, бетононасос 30 м³/ч, "
           "миксер 7 м³, до бетонного узла 10 км (25 км/ч), загрузка 10 мин, ожидание 5 мин.", "",
           *_calc_block(con), "",
           f"Итог: **{con['result']['concrete_pump']} бетононасос и {con['result']['concrete_mixer']} "
           "автобетоносмесителей** для непрерывной укладки без холодных швов.", "",
           "**Пример 3. Жилой дом 75 м × 18 м × 120 м**, самый тяжёлый элемент 3 т (бадья с бетоном), "
           "стропы 0,3 т, высота элемента 3 м, строповки 4 м, запас по высоте 1 м, ось крана в 6 м от фасада.", "",
           *_calc_block(cr), "",
           f"Итог: кран с высотой подъёма не менее **{cr['result']['hook_height_m']} м**, вылетом не менее "
           f"**{cr['result']['reach_m']} м** и грузоподъёмностью на этом вылете не менее **{cr['result']['load_t']} т**; "
           f"по длине здания — **{cr['result']['tower_crane']} крана**."]
    return "\n".join(out) + "\n"


def render(text: str) -> str:
    m, norms, catalog = load_methodology(), load_norms(), load_catalog()
    parts = {"NORMS": norms_table(m, norms, catalog), "CALC": calc_examples()}
    for name, body in parts.items():
        start, end = f"<!-- AUTO:{name} -->", f"<!-- /AUTO:{name} -->"
        i, j = text.index(start) + len(start), text.index(end)
        text = text[:i] + "\n" + body + text[j:]
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    current = DOC.read_text(encoding="utf-8")
    fresh = render(current)
    if args.check:
        if fresh != current:
            print("METHODOLOGY.md устарел: запустите python scripts/export_norms.py")
            return 1
        print("METHODOLOGY.md актуален")
        return 0
    DOC.write_text(fresh, encoding="utf-8")
    print(f"Обновлено: {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
