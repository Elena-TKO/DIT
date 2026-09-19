"""Парсер «Справочника видов работ» (xlsx от организаторов).

Особенности исходного файла, которые учитывает парсер:
* номера пунктов вида ``10.1.`` Excel превратил в даты (10 января) с форматом ``d.m.`` —
  восстанавливаем их обратно в строку «день.месяц»;
* у части строк номера нет: это подпункты последнего пронумерованного пункта;
* галочка «˅» в колонке типа объекта означает, что работа применяется для этого типа.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path

import openpyxl

# Колонки типов объектов: ключ -> заголовок в файле.
OBJECT_TYPES: dict[str, str] = {
    "housing": "Жильё",
    "education": "Образование",
    "healthcare": "Здравоохранение",
    "sport": "Спорт",
    "culture": "Культура",
    "admin": "Административные здания",
    "kindergarten": "ДОУ",
    "office": "Офисно-деловой центр",
    "roads": "Дороги",
}

CHECK_MARKS = {"˅", "v", "V", "✓", "✔", "+", "x", "X", "1"}


@dataclass
class CatalogItem:
    code: str                 # "12.3.4" или "12.3.4.u2" для ненумерованных подпунктов
    name: str
    level: int                # 1 — раздел, 2 — этап, 3 — вид работ, 4+ — подпункты
    parent_code: str | None
    numbered: bool
    types: list[str] = field(default_factory=list)
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_code(raw) -> str | None:
    """Приводит значение ячейки «№ п/п» к виду '12.3.4'."""
    if raw is None:
        return None
    if isinstance(raw, dt.datetime):  # 10.1. -> 2025-01-10
        return f"{raw.day}.{raw.month}"
    if isinstance(raw, (int, float)):
        return str(int(raw)) if float(raw).is_integer() else str(raw).rstrip(".")
    text = str(raw).strip().rstrip(".")
    return text or None


def parse_catalog(path: str | Path) -> list[CatalogItem]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    header_idx = next(
        i for i, row in enumerate(rows) if row and any(str(c).strip() == "Вид работ" for c in row if c)
    )
    header = [str(c).strip() if c else "" for c in rows[header_idx]]
    type_cols = {key: header.index(title) for key, title in OBJECT_TYPES.items() if title in header}

    items: list[CatalogItem] = []
    stack: list[CatalogItem] = []           # цепочка пронумерованных родителей
    unnumbered_counter: dict[str, int] = {}

    for row in rows[header_idx + 1:]:
        if not row or len(row) < 2 or not row[1] or not str(row[1]).strip():
            continue
        name = " ".join(str(row[1]).split())
        code = _normalize_code(row[0])
        types = [k for k, col in type_cols.items()
                 if col < len(row) and row[col] is not None and str(row[col]).strip() in CHECK_MARKS]

        if code:
            level = code.count(".") + 1
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1].code if stack else None
            item = CatalogItem(code=code, name=name, level=level, parent_code=parent,
                               numbered=True, types=types)
            stack.append(item)
        else:
            if not stack:
                continue
            parent = stack[-1]
            n = unnumbered_counter.get(parent.code, 0) + 1
            unnumbered_counter[parent.code] = n
            item = CatalogItem(code=f"{parent.code}.u{n}", name=name, level=parent.level + 1,
                               parent_code=parent.code, numbered=False, types=types)
        item.order = len(items)
        items.append(item)
    return items


DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "works_catalog.xlsx"


@lru_cache(maxsize=4)
def load_catalog(path: str | None = None) -> tuple[CatalogItem, ...]:
    return tuple(parse_catalog(path or DEFAULT_CATALOG_PATH))


def ancestors(items_by_code: dict[str, CatalogItem], code: str) -> list[CatalogItem]:
    """Цепочка предков от ближайшего к корню."""
    chain = []
    cur = items_by_code.get(code)
    while cur and cur.parent_code:
        cur = items_by_code.get(cur.parent_code)
        if cur:
            chain.append(cur)
    return chain


def catalog_tree(items: list[CatalogItem] | tuple[CatalogItem, ...], object_type: str | None = None) -> list[dict]:
    """Дерево справочника (опционально — только работы для типа объекта)."""
    nodes: dict[str, dict] = {}
    roots: list[dict] = []
    for it in items:
        if object_type and object_type not in it.types:
            continue
        node = {**it.to_dict(), "children": []}
        nodes[it.code] = node
        parent = nodes.get(it.parent_code) if it.parent_code else None
        (parent["children"] if parent else roots).append(node)
    return roots
