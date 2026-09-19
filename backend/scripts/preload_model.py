"""Скачивает веса детектора заранее (вызывается при сборке Docker-образа)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.methodology import load_methodology  # noqa: E402

weights = os.environ.get("MODEL_WEIGHTS", "yolov8s-worldv2.pt")
if "world" in weights.lower():
    from ultralytics import YOLOWorld

    model = YOLOWorld(weights)
    prompts = [p for meta in load_methodology().equipment.values() for p in meta["prompts"]]
    model.set_classes(prompts)          # загружает CLIP
else:
    from ultralytics import YOLO

    YOLO(weights)
print(f"Модель {weights} готова")
