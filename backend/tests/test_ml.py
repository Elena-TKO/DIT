"""Тесты ML-слоя без весов модели: разбор выхода YOLOv8, NMS, letterbox, маппинг меток."""
import unittest

import numpy as np

from app.core.methodology import load_methodology
from app.ml.class_map import map_label
from app.ml.detectors import (decode_yolov8, letterbox, nms, create_detector, NullDetector,
                              tile_boxes, merge_tiled)
from app.core.types import Detection

M = load_methodology()


class ClassMapTest(unittest.TestCase):
    def test_aliases(self):
        cases = {"Dump Truck": "dump_truck", "dump_truck": "dump_truck", "EXCAVATORS": "excavator",
                 "concrete-mixer-truck": "concrete_mixer", "Wheel Loader": "loader", "truck": "truck",
                 "tower crane": "tower_crane", "drilling rig": "pile_driver", "person": None, "car": None}
        for raw, expected in cases.items():
            self.assertEqual(map_label(raw, set(M.equipment)), expected, raw)

    def test_every_prompt_maps_back(self):
        for cls, meta in M.equipment.items():
            for p in meta["prompts"]:
                self.assertEqual(map_label(p), cls, p)


class DecodeTest(unittest.TestCase):
    def test_decode_with_letterbox_and_nms(self):
        orig_w, orig_h = 1280, 720
        img = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
        boxed, ratio, pad = letterbox(img, 640)
        self.assertEqual(boxed.shape, (640, 640, 3))
        self.assertAlmostEqual(ratio, 0.5)
        self.assertEqual(pad, (0, 140))

        nc, n = 3, 8400
        out = np.zeros((1, 4 + nc, n), dtype=np.float32)
        # объект класса 1 в исходных координатах (200,100)-(600,500) -> в letterbox: *0.5, +pad по y
        cx, cy, w, h = 200, 150 + 140, 200, 200
        for k, (dx, score) in enumerate([(0, 0.9), (4, 0.8), (300, 0.7)]):
            out[0, :4, k] = [cx + dx, cy, w, h]
            out[0, 4 + 1, k] = score
        out[0, :4, 10] = [100, 300, 50, 50]
        out[0, 4 + 2, 10] = 0.1   # ниже порога
        dets = decode_yolov8(out, conf=0.25, iou_thr=0.5, ratio=ratio, pad=pad, orig_w=orig_w, orig_h=orig_h)
        self.assertEqual(len(dets), 2)            # дубль подавлен NMS, слабый отброшен
        cid, score, box = dets[0]
        self.assertEqual(cid, 1)
        self.assertAlmostEqual(score, 0.9, places=5)
        np.testing.assert_allclose(box, (200, 100, 600, 500), atol=1e-3)

    def test_nms_keeps_separate(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=float)
        self.assertEqual(sorted(nms(boxes, np.array([0.9, 0.8, 0.7]), 0.5)), [0, 2])


class TilingTest(unittest.TestCase):
    """Разрезание кадра на плитки: техника на дальнем плане мельче 30 px и теряется при сжатии."""

    def test_grid_covers_frame_with_overlap(self):
        self.assertEqual(tile_boxes(1), [(0.0, 0.0, 1.0, 1.0)])
        tiles = tile_boxes(2, overlap=0.2)
        self.assertEqual(len(tiles), 4)
        for x1, y1, x2, y2 in tiles:
            self.assertTrue(0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1)
        self.assertGreater(tiles[0][2], 0.5)                 # перекрытие с соседней плиткой
        self.assertLess(tiles[3][0], 0.5)
        self.assertAlmostEqual(min(t[0] for t in tiles), 0.0)
        self.assertAlmostEqual(max(t[2] for t in tiles), 1.0)

    def test_duplicate_in_overlap_is_merged(self):
        d = lambda cls, box, conf: Detection(id=0, cls=cls, confidence=conf, bbox=box, label_raw="")
        merged = merge_tiled([d("excavator", (0.48, 0.5, 0.58, 0.6), 0.9),
                              d("excavator", (0.49, 0.51, 0.59, 0.61), 0.7),     # тот же объект с соседней плитки
                              d("excavator", (0.1, 0.1, 0.2, 0.2), 0.8),
                              d("dump_truck", (0.48, 0.5, 0.58, 0.6), 0.6)])     # другой класс — остаётся
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0].confidence, 0.9)


class FactoryTest(unittest.TestCase):
    def test_missing_backend_degrades_honestly(self):
        class S:
            detector, model_weights, detect_conf, detect_imgsz, device = "ultralytics", "x.pt", 0.25, 640, None
        det = create_detector(S(), M)
        # ultralytics в тестовом окружении может отсутствовать — сервис не падает, а сообщает причину
        if isinstance(det, NullDetector):
            self.assertIn("ultralytics", det.info()["warning"])


if __name__ == "__main__":
    unittest.main()
