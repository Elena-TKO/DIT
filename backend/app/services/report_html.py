"""HTML-отчёт по стройке: самодостаточный файл (миниатюры встроены), печатается в PDF из браузера."""
from __future__ import annotations

import base64
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .analysis import project_report
from .common import AppContext
from .photos import image_path

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def ru_date(value) -> str:
    """'2025-05-28' или ISO-время → '28 мая 2025'."""
    if not value:
        return "—"
    text = str(value)
    y, m, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
    return f"{d} {_MONTHS[m - 1]} {y}"


def ru_datetime(value) -> str:
    if not value:
        return "—"
    text = str(value)
    return f"{ru_date(text)}, {text[11:16]}" if len(text) >= 16 else ru_date(text)


_env.filters["ru_date"] = ru_date
_env.filters["ru_datetime"] = ru_datetime


def _thumb_b64(ctx: AppContext, photo_id: int, width: int = 360) -> str | None:
    photo = ctx.db.one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        return None
    path = image_path(ctx, photo)
    if not path.exists():
        return None
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((width, width))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except:
        return None


def render_report(ctx: AppContext, user_id: int, project_id: int, at: str | None = None) -> str:
    data = project_report(ctx, user_id, project_id, at)
    thumbs: dict[int, str] = {}
    for b in data["buildings"]:
        for d in b["verdict"]["deviations"][:8]:
            for pid in d["photo_ids"][-2:]:
                if pid not in thumbs and (t := _thumb_b64(ctx, pid)):
                    thumbs[pid] = t
    return _env.get_template("report.html").render(**data, thumbs=thumbs)
