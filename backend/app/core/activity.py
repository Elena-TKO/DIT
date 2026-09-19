"""Работает техника или стоит.

Камеры делают снимок раз в ~30 минут, поэтому используем сопоставление рамок между
соседними кадрами одной камеры: если машина того же класса занимает практически ту же
область (IoU ≥ ``static_iou``), она стоит; время простоя накапливается. Если рамка
сместилась или машина появилась — работает. Для первого кадра статус неизвестен.
"""
from __future__ import annotations

from .methodology import Methodology
from .types import PhotoObs, iou


def assign_activity(frames: list[PhotoObs], m: Methodology) -> None:
    """Проставляет ``activity`` и ``idle_minutes`` детекциям. Кадры — одной камеры."""
    static_iou = m.activity["static_iou"]
    max_gap = m.activity["max_gap_minutes"]
    min_conf = m.detection["min_confidence"]

    prev: PhotoObs | None = None
    for frame in sorted(frames, key=lambda f: f.taken_at):
        dets = [d for d in frame.detections if d.confidence >= min_conf]
        for d in frame.detections:
            d.activity, d.idle_minutes = "unknown", 0

        gap = (frame.taken_at - prev.taken_at).total_seconds() / 60 if prev else None
        if prev is None or gap is None or gap > max_gap or gap <= 0:
            prev = frame
            continue

        prev_dets = [d for d in prev.detections if d.confidence >= min_conf]
        # Жадное сопоставление: сначала самые похожие пары одного класса.
        pairs = sorted(
            ((iou(a.bbox, b.bbox), i, j) for i, a in enumerate(dets)
             for j, b in enumerate(prev_dets) if a.cls == b.cls),
            reverse=True,
        )
        used_cur, used_prev = set(), set()
        for score, i, j in pairs:
            if i in used_cur or j in used_prev or score < 0.1:
                continue
            used_cur.add(i)
            used_prev.add(j)
            if score >= static_iou:
                dets[i].activity = "idle"
                dets[i].idle_minutes = prev_dets[j].idle_minutes + int(round(gap))
            else:
                dets[i].activity = "working"
        for i, d in enumerate(dets):
            if i not in used_cur:
                d.activity = "working"   # машина заехала или переместилась
        prev = frame
