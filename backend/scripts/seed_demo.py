"""Демо-данные: пользователь, стройка, объект, камера и снимки из папки.

    python scripts/seed_demo.py --photos /path/to/screenshots --start 2025-05-12T08:00

Вход: demo@stroykontrol.ru / demo12345. Детектор берётся из переменных окружения.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.services import analysis, cameras, photos, projects  # noqa: E402
from app.services.common import AppContext, ServiceError  # noqa: E402

EMAIL, PASSWORD = "demo@stroykontrol.ru", "demo12345"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--start", default="2025-05-12T08:00")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    ctx = AppContext(Settings())
    try:
        uid = projects.register(ctx, EMAIL, PASSWORD, "Демо-инженер")["user"]["id"]
    except ServiceError:
        uid = projects.login(ctx, EMAIL, PASSWORD)["user"]["id"]
    project = projects.create_project(ctx, uid, "ЖК «Северный парк»", "Москва, Дмитровское ш., вл. 1",
                                      "2025-01-15", "2027-03-31")
    building = projects.create_building(ctx, uid, project["id"], "Корпус 1", "housing")
    cam = cameras.create_camera(ctx, uid, project["id"], "Обзорная, мачта", zone="Котлован",
                                building_id=building["id"])
    files = sorted(p for p in args.photos.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[: args.limit]
    res = photos.upload_photos(ctx, uid, building["id"], [(p.name, p.read_bytes()) for p in files],
                               camera_id=cam["id"], start_at=args.start, interval_min=args.interval)
    result = analysis.analyze(ctx, uid, building["id"], save=True)
    print(f"Загружено снимков: {res['uploaded']}, ошибок: {len(res['errors'])}")
    print(result["verdict"]["summary"])
    print(f"Вход: {EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    main()
