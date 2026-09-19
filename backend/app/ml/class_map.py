"""Приведение меток разных моделей/датасетов к классам методики.

Открытые датасеты (Kaggle, Roboflow) называют одну и ту же технику по-разному:
"Dump Truck", "dump_truck", "tipper"… Модель COCO знает только "truck".
"""
from __future__ import annotations

import re

ALIASES: dict[str, list[str]] = {
    "excavator": ["excavator", "excavators", "digger", "hydraulic excavator", "mini excavator",
                  "crawler excavator", "экскаватор"],
    "dump_truck": ["dump truck", "dumptruck", "dump", "tipper", "tipper truck", "articulated dump truck",
                   "haul truck", "самосвал"],
    "bulldozer": ["bulldozer", "dozer", "crawler dozer", "бульдозер"],
    "roller": ["roller", "road roller", "compactor", "roller compactor", "steamroller", "vibratory roller",
               "каток"],
    "mobile_crane": ["mobile crane", "truck crane", "crane truck", "crawler crane", "all terrain crane",
                     "crane", "автокран"],
    "crane_manipulator": ["truck mounted crane", "crane manipulator", "knuckle boom crane", "loader crane",
                          "hiab", "кран манипулятор"],
    "tower_crane": ["tower crane", "башенный кран"],
    "concrete_mixer": ["concrete mixer", "concrete mixer truck", "mixer truck", "cement truck", "mixer",
                       "transit mixer", "cement mixer", "бетоносмеситель", "автобетоносмеситель"],
    "concrete_pump": ["concrete pump", "concrete pump truck", "boom pump", "бетононасос", "автобетононасос"],
    "pile_driver": ["pile driver", "piling rig", "drilling rig", "drill rig", "rotary drilling rig", "pile rig",
                    "буровая установка", "сваебойная установка"],
    "truck": ["truck", "lorry", "flatbed truck", "semi truck", "trailer truck", "грузовик"],
    "loader": ["loader", "wheel loader", "backhoe loader", "backhoe", "front loader", "skid steer",
               "skid steer loader", "погрузчик"],
    "grader": ["grader", "motor grader", "автогрейдер"],
    "asphalt_paver": ["asphalt paver", "paver", "асфальтоукладчик"],
}

_LOOKUP = {alias: cls for cls, names in ALIASES.items() for alias in names}


def normalize(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-]+", " ", str(label).lower())).strip()


def map_label(label: str, known: set[str] | None = None) -> str | None:
    """Класс методики для метки модели или None, если это не строительная техника."""
    norm = normalize(label)
    if known and norm.replace(" ", "_") in known:
        return norm.replace(" ", "_")
    if norm in _LOOKUP:
        return _LOOKUP[norm]
    if norm.endswith("s") and norm[:-1] in _LOOKUP:
        return _LOOKUP[norm[:-1]]
    return None
