"""Тест подготовки датасета для дообучения (без самого обучения)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import train_yolo  # noqa: E402


class PrepareDatasetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merge_yolo_and_voc(self):
        yolo = self.tmp / "roboflow"
        for split in ("train", "valid"):
            (yolo / split / "images").mkdir(parents=True)
            (yolo / split / "labels").mkdir(parents=True)
        (yolo / "data.yaml").write_text("train: ../train/images\nnc: 3\nnames: ['Dump Truck', 'person', 'Excavator']\n")
        for i in range(4):
            Image.new("RGB", (64, 64)).save(yolo / "train" / "images" / f"a{i}.jpg")
            (yolo / "train" / "labels" / f"a{i}.txt").write_text("0 0.5 0.5 0.2 0.2\n1 0.1 0.1 0.1 0.1\n2 0.3 0.3 0.1 0.1\n")
        voc = self.tmp / "voc"
        voc.mkdir()
        Image.new("RGB", (200, 100)).save(voc / "b.jpg")
        (voc / "b.xml").write_text(
            "<annotation><filename>b.jpg</filename><size><width>200</width><height>100</height></size>"
            "<object><name>bulldozer</name><bndbox><xmin>20</xmin><ymin>10</ymin><xmax>120</xmax><ymax>90</ymax>"
            "</bndbox></object></annotation>")
        data = train_yolo.prepare([yolo, voc], self.tmp / "merged", val_share=0.2)
        text = data.read_text()
        self.assertIn("names: [excavator, dump_truck", text)
        labels = list((self.tmp / "merged" / "labels").rglob("*.txt"))
        self.assertEqual(len(labels), 5)
        rows = [line for p in labels for line in p.read_text().split("\n") if line]
        ids = {int(r.split()[0]) for r in rows}
        self.assertEqual(ids, {0, 1, 2})          # excavator, dump_truck, bulldozer; person отброшен
        self.assertIn("2 0.350000 0.500000 0.500000 0.800000", rows)


if __name__ == "__main__":
    unittest.main()


class EvalDetectorTest(unittest.TestCase):
    """Проверка метрик на заведомо известном ответе: детектор-заглушка с контролируемыми ошибками."""

    def test_precision_recall_and_threshold(self):
        import eval_detector
        from app.core.types import Detection

        class FakeDetector:
            def detect(self, path):
                # два верных объекта (0.9 и 0.3) и одно ложное срабатывание (0.4)
                return [Detection(id=0, cls="excavator", confidence=0.9, bbox=(0.1, 0.1, 0.3, 0.3), label_raw=""),
                        Detection(id=0, cls="excavator", confidence=0.3, bbox=(0.5, 0.5, 0.7, 0.7), label_raw=""),
                        Detection(id=0, cls="dump_truck", confidence=0.4, bbox=(0.8, 0.8, 0.9, 0.9), label_raw="")]

            def info(self):
                return {"backend": "fake"}

        truth = {"a": [("excavator", (0.1, 0.1, 0.3, 0.3)), ("excavator", (0.5, 0.5, 0.7, 0.7))]}
        best = eval_detector.evaluate(FakeDetector(), [Path("a.jpg")], truth, [0.25, 0.35, 0.5], 0.5)
        self.assertEqual(best[0], 0.25)            # низкий порог даёт лучший F1 на этой выборке
        self.assertAlmostEqual(best[1], 0.8, places=3)

    def test_match_counts(self):
        import eval_detector

        preds = [("excavator", (0, 0, 0.2, 0.2), 0.9), ("excavator", (0.5, 0.5, 0.6, 0.6), 0.8)]
        gts = [("excavator", (0, 0, 0.2, 0.2)), ("dump_truck", (0.5, 0.5, 0.6, 0.6))]
        self.assertEqual(eval_detector.match(preds, gts, 0.5), (1, 1, 1))


class MethodologyDocTest(unittest.TestCase):
    def test_methodology_md_matches_code(self):
        """Приложения METHODOLOGY.md сгенерированы из текущих norms.json / methodology.json."""
        import export_norms
        current = export_norms.DOC.read_text(encoding="utf-8")
        self.assertEqual(export_norms.render(current), current,
                         "METHODOLOGY.md устарел: python scripts/export_norms.py")
