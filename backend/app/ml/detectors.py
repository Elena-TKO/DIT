"""Детекторы строительной техники.

Поддерживаемые бэкенды (переменная окружения ``DETECTOR``):

* ``ultralytics`` — YOLOv8/11 через пакет ultralytics.
  - дообученные веса (``MODEL_WEIGHTS=models/construction.pt``, см. scripts/train_yolo.py);
  - YOLO-World (``MODEL_WEIGHTS=yolov8s-worldv2.pt``) — open-vocabulary, классы задаются
    текстовыми подсказками из методики, работает без дообучения;
* ``onnx`` — экспортированная YOLOv8 в ONNX через onnxruntime (лёгкий CPU-образ без torch);
* ``mock`` — читает разметку из JSON рядом со снимком (для тестов и демонстраций без модели);
* ``none`` — ничего не детектирует (явно показывается в интерфейсе).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.methodology import Methodology
from app.core.types import Detection, iou
from .class_map import map_label

log = logging.getLogger(__name__)


class Detector(Protocol):
    name: str

    def detect(self, image_path: str | Path) -> list[Detection]: ...

    def info(self) -> dict: ...


def _norm_box(x1, y1, x2, y2, w, h) -> tuple[float, float, float, float]:
    return (max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h))


# --------------------------------------------------------------------------- ultralytics
class UltralyticsDetector:
    name = "ultralytics"

    def __init__(self, weights: str, m: Methodology, conf: float = 0.25, iou: float = 0.5,
                 imgsz: int = 1280, device: str | None = None, tiles: int = 1):
        from ultralytics import YOLO  # импорт внутри: пакет тяжёлый и необязательный

        self.weights, self.conf, self.iou, self.imgsz, self.device = weights, conf, iou, imgsz, device
        self.tiles = max(1, tiles)      # >1: кадр режется на плитки, мелкая техника вдали видна лучше
        self.known = set(m.equipment)
        self.prompt_to_class: dict[str, str] = {}
        self.open_vocab = "world" in Path(weights).name.lower()
        if self.open_vocab:
            from ultralytics import YOLOWorld

            self.model = YOLOWorld(weights)
            prompts = []
            for cls, meta in m.equipment.items():
                for p in meta.get("prompts", [cls.replace("_", " ")]):
                    prompts.append(p)
                    self.prompt_to_class[p] = cls
            self.model.set_classes(prompts)
        else:
            self.model = YOLO(weights)

    def detect(self, image_path):
        found = self._predict(str(image_path))
        if self.tiles > 1:
            from PIL import Image as PILImage

            with PILImage.open(image_path) as img:
                W, H = img.size
                for (x1, y1, x2, y2) in tile_boxes(self.tiles):
                    crop = img.crop((int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H)))
                    for d in self._predict(crop):
                        bx = [x1 + d.bbox[0] * (x2 - x1), y1 + d.bbox[1] * (y2 - y1),
                              x1 + d.bbox[2] * (x2 - x1), y1 + d.bbox[3] * (y2 - y1)]
                        found.append(Detection(cls=d.cls, confidence=d.confidence,
                                               bbox=tuple(round(v, 4) for v in bx), label_raw=d.label_raw))
            found = merge_tiled(found)
        return found

    def _predict(self, source):
        kwargs = dict(source=source, conf=self.conf, iou=self.iou, imgsz=self.imgsz, verbose=False)
        if self.device:
            kwargs["device"] = self.device
        result = self.model.predict(**kwargs)[0]
        h, w = result.orig_shape
        out = []
        boxes = result.boxes
        for xyxy, conf, cls_id in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
            raw = result.names[int(cls_id)]
            cls = self.prompt_to_class.get(raw) or map_label(raw, self.known)
            if cls:
                out.append(Detection(cls=cls, confidence=round(float(conf), 3),
                                     bbox=_norm_box(*xyxy, w, h), label_raw=raw))
        return out

    def info(self):
        return {"backend": self.name, "weights": self.weights, "open_vocabulary": self.open_vocab,
                "conf": self.conf, "imgsz": self.imgsz, "tiles": self.tiles}


# --------------------------------------------------------------------------- плитки
def tile_boxes(tiles: int, overlap: float = 0.2) -> list[tuple[float, float, float, float]]:
    """Сетка плиток в долях кадра с перекрытием: техника на границе не разрезается пополам."""
    if tiles < 2:
        return [(0.0, 0.0, 1.0, 1.0)]
    step = 1 / tiles
    pad = step * overlap
    out = []
    for r in range(tiles):
        for c in range(tiles):
            out.append((max(0.0, c * step - pad), max(0.0, r * step - pad),
                        min(1.0, (c + 1) * step + pad), min(1.0, (r + 1) * step + pad)))
    return out


def merge_tiled(detections: list[Detection], iou_thr: float = 0.55) -> list[Detection]:
    """Склейка результатов по плиткам: один объект в перекрытии не должен считаться дважды."""
    kept: list[Detection] = []
    for d in sorted(detections, key=lambda x: -x.confidence):
        if any(o.cls == d.cls and iou(d.bbox, o.bbox) >= iou_thr for o in kept):
            continue
        kept.append(d)
    return kept


# --------------------------------------------------------------------------- ONNX
def letterbox(img: np.ndarray, size: int) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Масштаб с сохранением пропорций и серыми полями, как при обучении YOLO."""
    import cv2

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, (left, top)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        areas = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / np.maximum(area_i + areas - inter, 1e-9)
        order = order[1:][iou < iou_thr]
    return keep


def decode_yolov8(output: np.ndarray, conf: float, iou_thr: float, ratio: float, pad: tuple[int, int],
                  orig_w: int, orig_h: int) -> list[tuple[int, float, tuple[float, float, float, float]]]:
    """Разбор выхода YOLOv8 ONNX формы (1, 4+nc, N) → [(class_id, score, box_px)]."""
    pred = output[0]
    if pred.shape[0] < pred.shape[1]:        # (4+nc, N) -> (N, 4+nc)
        pred = pred.T
    class_scores = pred[:, 4:]
    cls_ids = class_scores.argmax(axis=1)
    scores = class_scores[np.arange(len(pred)), cls_ids]
    mask = scores >= conf
    if not mask.any():
        return []
    pred, cls_ids, scores = pred[mask], cls_ids[mask], scores[mask]
    cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad[0]) / ratio
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad[1]) / ratio
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, orig_w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, orig_h)
    out = []
    for c in np.unique(cls_ids):            # NMS по каждому классу отдельно
        idx = np.where(cls_ids == c)[0]
        for k in nms(boxes[idx], scores[idx], iou_thr):
            j = idx[k]
            out.append((int(c), float(scores[j]), tuple(float(v) for v in boxes[j])))
    return sorted(out, key=lambda x: -x[1])


class OnnxYoloDetector:
    name = "onnx"

    def __init__(self, weights: str, class_names: list[str], m: Methodology, conf: float = 0.25,
                 iou: float = 0.5, imgsz: int = 640):
        import onnxruntime as ort

        self.session = ort.InferenceSession(weights, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.weights, self.names, self.conf, self.iou, self.imgsz = weights, class_names, conf, iou, imgsz
        self.known = set(m.equipment)

    def detect(self, image_path):
        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Не удалось прочитать изображение {image_path}")
        h, w = img.shape[:2]
        boxed, ratio, pad = letterbox(img, self.imgsz)
        blob = cv2.cvtColor(boxed, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        output = self.session.run(None, {self.input_name: blob})[0]
        out = []
        for cid, score, (x1, y1, x2, y2) in decode_yolov8(output, self.conf, self.iou, ratio, pad, w, h):
            raw = self.names[cid] if cid < len(self.names) else str(cid)
            cls = map_label(raw, self.known)
            if cls:
                out.append(Detection(cls=cls, confidence=round(score, 3), bbox=_norm_box(x1, y1, x2, y2, w, h),
                                     label_raw=raw))
        return out

    def info(self):
        return {"backend": self.name, "weights": self.weights, "classes": self.names, "imgsz": self.imgsz}


# --------------------------------------------------------------------------- mock / none
class MockDetector:
    """Читает разметку ``<снимок>.json``: [{"cls": "excavator", "bbox": [x1,y1,x2,y2], "confidence": 0.9}].

    Координаты — в долях кадра. Используется в автотестах и для демонстрации без модели.
    """
    name = "mock"

    def __init__(self, annotations_dir: str | None = None):
        self.annotations_dir = Path(annotations_dir) if annotations_dir else None

    def _annotation_path(self, image_path: Path) -> Path | None:
        candidates = [image_path.with_suffix(image_path.suffix + ".json"), image_path.with_suffix(".json")]
        if self.annotations_dir:
            candidates += [self.annotations_dir / (image_path.stem + ".json")]
            # загруженный файл сохраняется под новым именем "<uuid>__<исходное имя>"
            if "__" in image_path.stem:
                candidates.append(self.annotations_dir / (image_path.stem.split("__", 1)[1] + ".json"))
        return next((c for c in candidates if c.exists()), None)

    def detect(self, image_path):
        path = self._annotation_path(Path(image_path))
        if not path:
            return []
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        return [Detection(cls=i["cls"], confidence=float(i.get("confidence", 0.9)),
                          bbox=tuple(i["bbox"]), label_raw=i.get("label", i["cls"])) for i in items]

    def info(self):
        return {"backend": self.name, "annotations_dir": str(self.annotations_dir) if self.annotations_dir else None}


class NullDetector:
    name = "none"

    def __init__(self, reason: str = ""):
        self.reason = reason

    def detect(self, image_path):
        return []

    def info(self):
        return {"backend": self.name, "warning": self.reason or "Детектор отключён"}


def create_detector(settings, m: Methodology) -> Detector:
    backend = settings.detector
    try:
        if backend == "ultralytics":
            return UltralyticsDetector(settings.model_weights, m, conf=settings.detect_conf,
                                   tiles=getattr(settings, "detect_tiles", 1),
                                       imgsz=settings.detect_imgsz, device=settings.device)
        if backend == "onnx":
            names = [n.strip() for n in settings.onnx_classes.split(",") if n.strip()]
            return OnnxYoloDetector(settings.model_weights, names, m, conf=settings.detect_conf)
        if backend == "mock":
            return MockDetector(settings.mock_annotations_dir)
        return NullDetector("DETECTOR=none")
    except Exception as exc:  # модель не загрузилась — сервис продолжает работать, но честно сообщает
        log.exception("Не удалось загрузить детектор %s", backend)
        return NullDetector(f"Не удалось загрузить детектор «{backend}»: {exc}")
