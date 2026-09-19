"""Генерирует docs/methodology.md из data/methodology.json (документ всегда совпадает с кодом)."""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.catalog import load_catalog, OBJECT_TYPES  # noqa: E402
from app.core.methodology import load_methodology  # noqa: E402
from app.core.planner import generate_plan  # noqa: E402

OBS = {"high": "высокая", "medium": "средняя", "low": "низкая", "none": "не наблюдается"}


def main(out: Path):
    raw = json.loads((ROOT / "data" / "methodology.json").read_text(encoding="utf-8"))
    m = load_methodology()
    label = lambda c: raw["equipment"][c]["label"]  # noqa: E731
    lines = ["# Методика «этап работ → техника»", "",
             "Сгенерировано автоматически из `backend/data/methodology.json`.", "",
             "Обязательная техника задаётся группами: внутри группы достаточно любой единицы (ИЛИ), "
             "группы между собой — И. Нетипичная техника снижает балл этапа.", "",
             "| № | Этап | Обязательная техника | Типичная | Нетипичная | Наблюдаемость | Окно в графике |",
             "|---|---|---|---|---|---|---|"]
    for i, p in enumerate(raw["phases"], 1):
        req = "; ".join(" или ".join(label(c) for c in g) for g in p["required"]) or "—"
        lines.append(f"| {i} | {p['name']} | {req} | {', '.join(label(c) for c in p['typical']) or '—'} | "
                     f"{', '.join(label(c) for c in p['unexpected']) or '—'} | {OBS[p['observability']]} | "
                     f"{int(p['window'][0]*100)}–{int(p['window'][1]*100)}% |")
    lines += ["", "## Параметры анализа", ""]
    for section in ("detection", "activity", "analysis"):
        lines.append(f"- `{section}`: `{json.dumps(raw[section], ensure_ascii=False)}`")
    lines += ["", "## Классы техники", ""]
    for c, meta in raw["equipment"].items():
        lines.append(f"- **{meta['label']}** (`{c}`), подсказки детектору: {', '.join(meta['prompts'])}")
    lines += ["", "## Привязка работ справочника к этапам (число работ по типам объектов)", ""]
    catalog = load_catalog()
    per_type = {}
    for t in OBJECT_TYPES:
        leaves = [x for x in generate_plan(catalog, t, "2025-01-01", "2026-12-31", m) if not x.is_summary]
        per_type[t] = collections.Counter(x.phase for x in leaves)
    lines.append("| Этап | " + " | ".join(OBJECT_TYPES.values()) + " |")
    lines.append("|---" * (len(OBJECT_TYPES) + 1) + "|")
    for p in raw["phases"]:
        lines.append(f"| {p['name']} | " + " | ".join(str(per_type[t].get(p['id'], 0) or "") for t in OBJECT_TYPES) + " |")
    lines.append(f"\nВсего позиций справочника: {len(catalog)}; типов объектов: {len(OBJECT_TYPES)}.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Записано: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "docs" / "methodology.md")
