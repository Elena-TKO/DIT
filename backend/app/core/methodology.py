"""Методика сопоставления «этап работ → техника».

Методика хранится в ``data/methodology.json`` и может редактироваться без изменения кода:
* ``equipment`` — таксономия техники (ключ класса, русское название, текстовые подсказки для
  open-vocabulary детектора);
* ``phases`` — технологические этапы: обязательная техника (CNF: список групп-альтернатив),
  типичная техника, нетипичная техника, наблюдаемость камерами, типовое окно в графике;
* ``mapping_rules`` — правила привязки строк справочника работ к этапам (первое совпадение).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .catalog import CatalogItem

DEFAULT_METHODOLOGY_PATH = Path(__file__).resolve().parents[2] / "data" / "methodology.json"

OBSERVABILITY_LEVELS = ("high", "medium", "low", "none")
# Насколько надёжно этап подтверждается снимками (вес при расчётах).
OBSERVABILITY_WEIGHT = {"high": 1.0, "medium": 0.8, "low": 0.5, "none": 0.0}


@dataclass(frozen=True)
class Phase:
    id: str
    name: str
    observability: str
    window: tuple[float, float]
    required: tuple[tuple[str, ...], ...]
    typical: tuple[str, ...]
    unexpected: tuple[str, ...]
    hint: str = ""
    sequence: int = 0

    @property
    def observable(self) -> bool:
        """Можно ли делать выводы по технике (для low выводы мягкие)."""
        return self.observability in ("high", "medium", "low")

    @property
    def expected_classes(self) -> set[str]:
        return {c for g in self.required for c in g} | set(self.typical)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "observability": self.observability,
            "window": list(self.window), "required": [list(g) for g in self.required],
            "typical": list(self.typical), "unexpected": list(self.unexpected),
            "hint": self.hint, "sequence": self.sequence,
        }


@dataclass
class Methodology:
    equipment: dict[str, dict]
    phases: dict[str, Phase]
    mapping_rules: list[dict]
    detection: dict
    activity: dict
    analysis: dict
    economics: dict
    class_weights: dict[str, float] = field(default_factory=dict)

    # ---------- справочные методы ----------
    def label(self, cls: str) -> str:
        return self.equipment.get(cls, {}).get("label", cls)

    def phase(self, phase_id: str) -> Phase:
        return self.phases[phase_id]

    def ordered_phases(self) -> list[Phase]:
        return sorted(self.phases.values(), key=lambda p: p.sequence)

    # ---------- привязка работ к этапам ----------
    def phase_for_item(self, item: CatalogItem, items_by_code: dict[str, CatalogItem],
                       object_type: str | None = None) -> str:
        parts = item.code.split(".")
        names = [item.name.lower()]
        # Подпункты наследуют смысл родителя уровня ≥3 («Пароизоляция» внутри «Пирога кровли»).
        cur = items_by_code.get(item.parent_code) if item.parent_code else None
        while cur is not None and cur.level >= 3:
            names.append(cur.name.lower())
            cur = items_by_code.get(cur.parent_code) if cur.parent_code else None

        for rule in self.mapping_rules:
            if object_type and rule.get("types") and object_type not in rule["types"]:
                continue
            codes = rule.get("codes")
            if codes and not any(parts[: len(c.split("."))] == c.split(".") for c in codes):
                continue
            keywords = rule.get("keywords")
            if keywords and not any(k in n for k in keywords for n in names):
                continue
            return rule["phase"]
        return "ORGANIZATION"


def _validate(raw: dict) -> None:
    classes = set(raw["equipment"])
    ids = set()
    for ph in raw["phases"]:
        if ph["id"] in ids:
            raise ValueError(f"Дублируется этап {ph['id']}")
        ids.add(ph["id"])
        if ph["observability"] not in OBSERVABILITY_LEVELS:
            raise ValueError(f"{ph['id']}: неизвестная наблюдаемость {ph['observability']}")
        s, e = ph["window"]
        if not (0 <= s < e <= 1):
            raise ValueError(f"{ph['id']}: некорректное окно {ph['window']}")
        used = {c for g in ph["required"] for c in g} | set(ph["typical"]) | set(ph["unexpected"])
        unknown = used - classes
        if unknown:
            raise ValueError(f"{ph['id']}: неизвестные классы техники {sorted(unknown)}")
        clash = ({c for g in ph["required"] for c in g} | set(ph["typical"])) & set(ph["unexpected"])
        if clash:
            raise ValueError(f"{ph['id']}: класс одновременно ожидаемый и нетипичный {sorted(clash)}")
    for rule in raw["mapping_rules"]:
        if rule["phase"] not in ids:
            raise ValueError(f"Правило ссылается на неизвестный этап {rule['phase']}")


def _class_weights(phases: dict[str, Phase], classes: list[str]) -> dict[str, float]:
    """IDF-вес класса: чем в меньшем числе этапов техника ожидаема, тем она информативнее.

    Буровая установка встречается почти только в свайных работах — её появление значимо;
    грузовик ожидаем почти везде — его вклад в определение этапа мал.
    """
    n = len(phases)
    weights = {}
    for c in classes:
        df = sum(1 for p in phases.values() if c in p.expected_classes)
        weights[c] = math.log(1 + n / (1 + df))
    return weights


def build_methodology(raw: dict) -> Methodology:
    _validate(raw)
    ordered = sorted(raw["phases"], key=lambda p: (p["window"][0], p["window"][1]))
    phases = {}
    for seq, ph in enumerate(ordered):
        phases[ph["id"]] = Phase(
            id=ph["id"], name=ph["name"], observability=ph["observability"],
            window=(float(ph["window"][0]), float(ph["window"][1])),
            required=tuple(tuple(g) for g in ph["required"]),
            typical=tuple(ph["typical"]), unexpected=tuple(ph["unexpected"]),
            hint=ph.get("hint", ""), sequence=seq,
        )
    m = Methodology(
        equipment=raw["equipment"], phases=phases, mapping_rules=raw["mapping_rules"],
        detection=raw["detection"], activity=raw["activity"], analysis=raw["analysis"],
        economics=raw.get("economics", {}),
    )
    m.class_weights = _class_weights(phases, list(raw["equipment"]))
    return m


@lru_cache(maxsize=4)
def load_methodology(path: str | None = None) -> Methodology:
    with open(path or DEFAULT_METHODOLOGY_PATH, encoding="utf-8") as f:
        return build_methodology(json.load(f))
