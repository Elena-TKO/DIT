"""Оценка детектора на размеченном датасете: precision, recall, F1 и подбор порога.

    python scripts/eval_detector.py --data datasets/merged/data.yaml --split val
    python scripts/eval_detector.py --data ... --thresholds 0.2 0.25 0.3 0.35 0.4 0.5

Совпадением считается пара «предсказание — разметка» одного класса с IoU ≥ 0.5 (жадное сопоставление
по убыванию уверенности). Печатается таблица по порогам и по классам: видно, какую технику модель
не видит и где порог 0.35 из методики стоит поменять.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.methodology import load_methodology  # noqa: E402
from app.core.types import iou  # noqa: E402


def read_classes(data_yaml: Path) -> list[str]:
    for line in data_yaml.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("names:") and "[" in line:
            inner = line.split("[", 1)[1].rsplit("]", 1)[0]
            return [n.strip().strip("'\"") for n in inner.split(",") if n.strip()]
    raise SystemExit("В data.yaml не найден список names: [...]")


def load_truth(labels_dir: Path, classes: list[str]) -> dict[str, list[tuple[str, tuple]]]:
    truth = {}
    for label in sorted(labels_dir.glob("*.txt")):
        items = []
        for row in label.read_text().splitlines():
            parts = row.split()
            if len(parts) != 5:
                continue
            cid, cx, cy, w, h = int(parts[0]), *map(float, parts[1:])
            items.append((classes[cid], (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
        truth[label.stem] = items
    return truth


def match(preds: list, gts: list, iou_thr: float) -> tuple[int, int, int]:
    """Жадное сопоставление: (совпало, ложных срабатываний, пропущено)."""
    used = set()
    tp = 0
    for cls, box, _ in sorted(preds, key=lambda p: -p[2]):
        best, best_iou = None, iou_thr
        for i, (gcls, gbox) in enumerate(gts):
            if i in used or gcls != cls:
                continue
            value = iou(box, gbox)
            if value >= best_iou:
                best, best_iou = i, value
        if best is not None:
            used.add(best)
            tp += 1
    return tp, len(preds) - tp, len(gts) - tp


def evaluate(detector, images: list[Path], truth: dict, thresholds: list[float], iou_thr: float):
    raw = {}
    for image in images:
        raw[image.stem] = [(d.cls, d.bbox, d.confidence) for d in detector.detect(image)]

    print(f'{"порог":>6} {"precision":>10} {"recall":>8} {"F1":>6}  (изображений: {len(images)})')
    best = None
    for thr in thresholds:
        tp = fp = fn = 0
        for stem, preds in raw.items():
            a, b, c = match([p for p in preds if p[2] >= thr], truth.get(stem, []), iou_thr)
            tp, fp, fn = tp + a, fp + b, fn + c
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        print(f"{thr:>6.2f} {precision:>10.3f} {recall:>8.3f} {f1:>6.3f}")
        if best is None or f1 > best[1]:
            best = (thr, f1)

    thr = best[0]
    per_class: dict[str, list[int]] = {}
    for stem, preds in raw.items():
        classes = {c for c, _, _ in preds} | {c for c, _ in truth.get(stem, [])}
        for cls in classes:
            a, b, c = match([p for p in preds if p[2] >= thr and p[0] == cls],
                            [g for g in truth.get(stem, []) if g[0] == cls], iou_thr)
            row = per_class.setdefault(cls, [0, 0, 0])
            row[0] += a
            row[1] += b
            row[2] += c
    print(f"\nПо классам при пороге {thr:.2f}:")
    print(f'{"класс":<18}{"найдено":>9}{"ложных":>9}{"пропущено":>11}{"recall":>9}')
    for cls, (tp, fp, fn) in sorted(per_class.items(), key=lambda kv: -(kv[1][0] + kv[1][2])):
        recall = tp / (tp + fn) if tp + fn else 0.0
        print(f"{cls:<18}{tp:>9}{fp:>9}{fn:>11}{recall:>9.3f}")
    print(f"\nЛучший порог по F1: {thr:.2f}. В методике сейчас: "
          f"{load_methodology().detection['min_confidence']}")
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="data.yaml подготовленного датасета")
    ap.add_argument("--split", default="val")
    ap.add_argument("--thresholds", type=float, nargs="+", default=[0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6])
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0, help="ограничить число изображений")
    args = ap.parse_args()

    root = args.data.parent
    classes = read_classes(args.data)
    images = sorted((root / "images" / args.split).glob("*.*"))
    if args.limit:
        images = images[: args.limit]
    truth = load_truth(root / "labels" / args.split, classes)
    if not images:
        raise SystemExit(f"Не найдено изображений в {root / 'images' / args.split}")

    from app.config import Settings
    from app.ml.detectors import create_detector

    detector = create_detector(Settings(), load_methodology())
    print(f"Детектор: {detector.info()}")
    evaluate(detector, images, truth, sorted(args.thresholds), args.iou)


if __name__ == "__main__":
    main()
