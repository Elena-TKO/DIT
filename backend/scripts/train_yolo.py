"""Подготовка объединённого датасета и дообучение YOLO под классы методики.

Поддерживаемые форматы исходных датасетов (скачайте их по ссылкам организаторов):
* YOLO (Roboflow «YOLOv8», Kaggle): папка с data.yaml, images/, labels/;
* Pascal VOC: папки с *.jpg и одноимёнными *.xml.

Метки исходных датасетов переводятся в классы методики (app/ml/class_map.py);
всё, что не является строительной техникой, отбрасывается.

Примеры:
    python scripts/train_yolo.py --src datasets/roboflow datasets/kaggle_voc --out datasets/merged --prepare-only
    python scripts/train_yolo.py --src datasets/roboflow --out datasets/merged --epochs 60 --model yolov8s.pt
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.methodology import load_methodology  # noqa: E402
from app.ml.class_map import map_label  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _read_yaml_names(path: Path) -> list[str]:
    """Имена классов из data.yaml без зависимости от PyYAML (форматы list и dict)."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # если установлен — надёжнее

        names = yaml.safe_load(text).get("names")
        return list(names.values()) if isinstance(names, dict) else list(names)
    except ImportError:
        pass
    for line in text.splitlines():
        if line.strip().startswith("names:") and "[" in line:
            inner = line.split("[", 1)[1].rsplit("]", 1)[0]
            return [n.strip().strip("'\"") for n in inner.split(",") if n.strip()]
    names, capture = [], False
    for line in text.splitlines():
        if line.strip().startswith("names:"):
            capture = True
            continue
        if capture:
            s = line.strip()
            if s.startswith("- "):
                names.append(s[2:].strip().strip("'\""))
            elif ":" in s and s.split(":")[0].strip().isdigit():
                names.append(s.split(":", 1)[1].strip().strip("'\""))
            elif s:
                break
    return names


def collect_yolo(src: Path, classes: list[str]) -> list[tuple[Path, list[str]]]:
    yaml_path = next(iter(src.rglob("data.yaml")), None)
    if not yaml_path:
        return []
    names = _read_yaml_names(yaml_path)
    samples = []
    for label in src.rglob("*.txt"):
        if label.parent.name != "labels" and "labels" not in label.parts:
            continue
        img_dir = Path(*["images" if p == "labels" else p for p in label.parent.parts])
        image = next((img_dir / (label.stem + e) for e in IMAGE_EXT if (img_dir / (label.stem + e)).exists()), None)
        if not image:
            continue
        lines = []
        for row in label.read_text().splitlines():
            parts = row.split()
            if len(parts) != 5 or not parts[0].isdigit() or int(parts[0]) >= len(names):
                continue
            cls = map_label(names[int(parts[0])], set(classes))
            if cls:
                lines.append(" ".join([str(classes.index(cls))] + parts[1:]))
        samples.append((image, lines))
    return samples


def collect_voc(src: Path, classes: list[str]) -> list[tuple[Path, list[str]]]:
    samples = []
    for xml in src.rglob("*.xml"):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        size = root.find("size")
        if size is None:
            continue
        w, h = float(size.findtext("width", "0")), float(size.findtext("height", "0"))
        image = next((p for p in (xml.with_suffix(e) for e in IMAGE_EXT) if p.exists()), None)
        if image is None:
            fname = root.findtext("filename") or ""
            image = next((p for p in src.rglob(fname) if p.suffix.lower() in IMAGE_EXT), None) if fname else None
        if not image or w <= 0 or h <= 0:
            continue
        lines = []
        for obj in root.findall("object"):
            cls = map_label(obj.findtext("name", ""), set(classes))
            box = obj.find("bndbox")
            if not cls or box is None:
                continue
            x1, y1 = float(box.findtext("xmin")), float(box.findtext("ymin"))
            x2, y2 = float(box.findtext("xmax")), float(box.findtext("ymax"))
            cx, cy, bw, bh = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h
            lines.append(f"{classes.index(cls)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        samples.append((image, lines))
    return samples


def prepare(sources: list[Path], out: Path, val_share: float = 0.15, seed: int = 42) -> Path:
    classes = list(load_methodology().equipment)
    samples = []
    for src in sources:
        found = collect_yolo(src, classes) or collect_voc(src, classes)
        print(f"{src}: {len(found)} изображений")
        samples += found
    samples = [s for s in samples if s[1]]
    if not samples:
        raise SystemExit("Не найдено ни одного изображения с техникой из методики")
    random.Random(seed).shuffle(samples)
    n_val = max(1, int(len(samples) * val_share))
    for split, part in (("val", samples[:n_val]), ("train", samples[n_val:])):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i, (image, lines) in enumerate(part):
            name = f"{i:06d}{image.suffix.lower()}"
            shutil.copy(image, out / "images" / split / name)
            (out / "labels" / split / f"{i:06d}.txt").write_text("\n".join(lines) + "\n")
    yaml_path = out / "data.yaml"
    yaml_path.write_text(
        f"path: {out.resolve()}\ntrain: images/train\nval: images/val\n"
        f"names: [{', '.join(classes)}]\n", encoding="utf-8")
    counts = {c: 0 for c in classes}
    for _, lines in samples:
        for line in lines:
            counts[classes[int(line.split()[0])]] += 1
    print("Объекты по классам:", {k: v for k, v in counts.items() if v})
    return yaml_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("datasets/merged"))
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--export-onnx", action="store_true")
    args = ap.parse_args()

    data = prepare(args.src, args.out)
    if args.prepare_only:
        print(f"Датасет готов: {data}")
        return
    from ultralytics import YOLO

    model = YOLO(args.model)
    model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, project="runs",
                name="construction", exist_ok=True)
    best = Path("runs/construction/weights/best.pt")
    target = Path("models/construction.pt")
    target.parent.mkdir(exist_ok=True)
    shutil.copy(best, target)
    print(f"Веса сохранены: {target}. Запуск: MODEL_WEIGHTS={target}")
    if args.export_onnx:
        YOLO(str(target)).export(format="onnx", imgsz=640)


if __name__ == "__main__":
    main()
