"""Сквозной сценарий через сервисный слой: вход → стройка → объект → план → снимки/камеры →
определение этапа → вердикт → таймлайн → отчёт. Используются реальные снимки из проекта
(если доступны) и mock-детектор с JSON-разметкой."""
import datetime as dt
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from app.config import Settings
from app.ml.detectors import MockDetector
from app.services import analysis, cameras, photos, projects
from app.services.common import AppContext, ServiceError
from app.services.report_html import render_report

SAMPLES = Path(os.environ.get("SAMPLE_PHOTOS", "/mnt/project"))


def sample_images(n: int, tmp: Path) -> list[Path]:
    found = sorted(SAMPLES.glob("Screenshot_*.png"))[:n] if SAMPLES.exists() else []
    if len(found) >= n:
        return found
    out = []
    for i in range(n):   # запасной вариант без реальных снимков
        p = tmp / f"synthetic_{i}.png"
        Image.new("RGB", (640, 400), (120 + i, 110, 90)).save(p)
        out.append(p)
    return out


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.ann = cls.tmp / "annotations"
        cls.ann.mkdir()
        os.environ["DATA_DIR"] = str(cls.tmp / "data")
        os.environ["ALLOW_LOCAL_CAMERAS"] = "1"   # тестовая камера поднимается на 127.0.0.1
        cls.ctx = AppContext(Settings(), detector=MockDetector(str(cls.ann)))
        cls.images = sample_images(10, cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def annotate(self, image: Path, items: list[tuple[str, tuple]]):
        (self.ann / (image.stem + ".json")).write_text(json.dumps(
            [{"cls": c, "bbox": list(b), "confidence": 0.88} for c, b in items]))

    def files(self, paths):
        return [(p.name, p.read_bytes()) for p in paths]

    # ------------------------------------------------------------------
    def test_full_flow(self):
        ctx = self.ctx
        # 1. Авторизация
        session = projects.register(ctx, "Engineer@Site.ru", "secret123", "Инженер")
        uid = projects.user_from_token(ctx, session["token"])
        with self.assertRaises(ServiceError) as e:
            projects.register(ctx, "engineer@site.ru", "secret123", "Дубль")
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ServiceError):
            projects.login(ctx, "engineer@site.ru", "wrong")
        self.assertEqual(projects.login(ctx, "engineer@site.ru", "secret123")["user"]["id"], uid)
        with self.assertRaises(ServiceError):
            projects.user_from_token(ctx, "garbage.token.value")

        # 2. Стройка
        with self.assertRaises(ServiceError):
            projects.create_project(ctx, uid, "Плохие даты", "", "2025-05-01", "2025-01-01")
        project = projects.create_project(ctx, uid, "ЖК Северный", "Москва, ул. Лесная, 1", "2025-01-01", "2026-12-31")
        pid = project["id"]

        # 3. Объект и тип
        building = projects.create_building(ctx, uid, pid, "Корпус 1", "housing")
        bid = building["id"]
        self.assertEqual(building["object_type_title"], "Жильё")
        self.assertEqual(len(projects.list_buildings(ctx, uid, pid)), 1)

        # 4. Интерактивный план
        plan = projects.get_plan(ctx, uid, bid)
        self.assertEqual(len(plan["tasks"]), 254)
        exc_phase = next(p for p in plan["phases"] if p["phase"] == "EXCAVATION")
        leaf = next(t for t in plan["tasks"] if t["phase"] == "LANDSCAPING")
        delta = projects.update_task(ctx, uid, bid, leaf["id"], enabled=False)
        self.assertFalse(next(t for t in delta["tasks"] if t["id"] == leaf["id"])["active"])
        plan = projects.get_plan(ctx, uid, bid)
        summary = next(t for t in plan["tasks"] if t["code"] == "12.3")
        delta = projects.update_task(ctx, uid, bid, summary["id"], enabled=False)
        # ответ на правку — только затронутые строки, а не весь план
        self.assertTrue(delta["partial"])
        self.assertLess(len(delta["tasks"]), len(plan["tasks"]) / 2)
        self.assertTrue(all(not t["active"] for t in delta["tasks"] if t["code"].startswith("12.3.")))
        self.assertIn("12", {t["code"] for t in delta["tasks"]})        # предок для пересчёта сроков
        projects.update_task(ctx, uid, bid, summary["id"], enabled=True)
        plan = projects.get_plan(ctx, uid, bid)
        with self.assertRaises(ServiceError):
            projects.update_task(ctx, uid, bid, summary["id"], start_date="2025-02-01")
        t = next(t for t in plan["tasks"] if t["phase"] == "EXCAVATION")
        projects.update_task(ctx, uid, bid, t["id"], start_date=exc_phase["start"], end_date=exc_phase["end"])
        plan = projects.reschedule_plan(ctx, uid, bid)
        self.assertTrue(plan["phases"])

        # 5–7. Снимки: этап «котлован», экскаватор есть, самосвалов нет
        cam = cameras.create_camera(ctx, uid, pid, "Север", zone="Котлован", building_id=bid)
        start = dt.datetime.combine(dt.date.fromisoformat(exc_phase["start"]) + dt.timedelta(days=5), dt.time(9))
        batch = self.images[:4]
        for i, img in enumerate(batch):
            # экскаватор работает (рамка смещается), автокран стоит на месте
            self.annotate(img, [("excavator", (0.1 + 0.08 * i, 0.4, 0.3 + 0.08 * i, 0.7)),
                                ("mobile_crane", (0.6, 0.1, 0.8, 0.9))])
        res = photos.upload_photos(ctx, uid, bid, self.files(batch), camera_id=cam["id"],
                                   start_at=start.isoformat(), interval_min=30)
        self.assertEqual(res["uploaded"], 4, res["errors"])
        bad = photos.upload_photos(ctx, uid, bid, [("notes.txt", b"not an image")], camera_id=cam["id"])
        self.assertEqual(bad["uploaded"], 0)
        self.assertIn("не является изображением", bad["errors"][0]["error"])

        last_id = res["photo_ids"][-1]
        detail = photos.photo_detail(ctx, uid, last_id)
        acts = {d["cls"]: d["activity"] for d in detail["detections"]}
        self.assertEqual(acts, {"excavator": "working", "mobile_crane": "idle"})
        crane = next(d for d in detail["detections"] if d["cls"] == "mobile_crane")
        self.assertEqual(crane["idle_minutes"], 90)
        self.assertIn("EXCAVATION", [p["phase"] for p in detail["planned_phases"]])

        # 8. Вердикт
        result = analysis.analyze(ctx, uid, bid, save=True)
        v = result["verdict"]
        self.assertEqual(v["photos_in_window"], 4)
        missing = [d for d in v["deviations"] if d["kind"] == "MISSING_EQUIPMENT" and d["phase"] == "EXCAVATION"]
        self.assertEqual(len(missing), 1)
        self.assertIn("Самосвал", missing[0]["message"])
        self.assertEqual(missing[0]["zones"], ["Котлован"])
        self.assertTrue(set(missing[0]["photo_ids"]) <= set(res["photo_ids"]))
        self.assertTrue(any(d["kind"] == "IDLE_EQUIPMENT" for d in v["deviations"]))
        self.assertTrue(result["recommendations"])
        self.assertTrue(analysis.deviation_log(ctx, uid, bid))

        # Добавили самосвалы — предупреждение по котловану уходит
        more = self.images[4:6]
        for img in more:
            self.annotate(img, [("excavator", (0.2, 0.4, 0.4, 0.7)), ("dump_truck", (0.5, 0.5, 0.7, 0.8))])
        photos.upload_photos(ctx, uid, bid, self.files(more), camera_id=cam["id"],
                             start_at=(start + dt.timedelta(hours=2)).isoformat(), interval_min=30)
        v2 = analysis.analyze(ctx, uid, bid)["verdict"]
        self.assertFalse([d for d in v2["deviations"] if d["kind"] == "MISSING_EQUIPMENT" and d["phase"] == "EXCAVATION"])
        self.assertEqual(v2["stage"]["top_phase"], "EXCAVATION")

        # Ручная корректировка разметки
        fixed = photos.replace_detections(ctx, uid, last_id, [{"cls": "dump_truck", "bbox": [0.1, 0.1, 0.2, 0.2]}])
        self.assertEqual([d["cls"] for d in fixed["detections"]], ["dump_truck"])
        with self.assertRaises(ServiceError):
            photos.replace_detections(ctx, uid, last_id, [{"cls": "ufo", "bbox": [0, 0, 1, 1]}])

        # 9. Таймлайн
        tl = analysis.timeline(ctx, uid, bid)
        rows = {r["phase"]: r for r in tl["rows"]}
        self.assertEqual(rows["EXCAVATION"]["status"], "on_track")
        self.assertTrue(rows["EXCAVATION"]["evidence"])
        land_codes = [t["code"] for t in rows["LANDSCAPING"]["tasks"]]
        self.assertNotIn(leaf["code"], land_codes)          # отключённая работа не в таймлайне
        self.assertNotIn("EXT_NETWORKS", {r["phase"] for r in tl["rows"] if r["status"] == "ahead"})
        self.assertTrue(all(0 <= r["left"] <= 100 for r in tl["rows"]))
        self.assertIsNotNone(tl["forecast_end"])

        # 10. Сводка и отчёт
        overview = analysis.project_overview(ctx, uid, pid)
        self.assertEqual(overview["buildings"][0]["id"], bid)
        newest = photos.list_photos(ctx, uid, bid, limit=1)["items"][0]["id"]   # обложка — самый поздний кадр
        self.assertEqual(overview["buildings"][0]["cover_photo_id"], newest)
        self.assertEqual(projects.list_projects(ctx, uid)[0]["cover_photo_id"], newest)
        self.assertEqual(projects.get_building(ctx, uid, bid)["cover_photo_id"], newest)
        html = render_report(ctx, uid, pid)
        self.assertIn("ЖК Северный", html)
        self.assertIn("Рекомендации по установке камер", html)
        self.assertIn("data:image/jpeg;base64,", html)

        # Миниатюры и удаление
        path, mime = photos.image_file(ctx, uid, last_id, width=320)
        self.assertEqual(mime, "image/jpeg")
        with Image.open(path) as im:
            self.assertLessEqual(im.width, 320)
        photos.delete_photo(ctx, uid, res["photo_ids"][0])
        self.assertEqual(photos.list_photos(ctx, uid, bid)["total"], 5)

        # Чужой пользователь ничего не видит
        other = projects.register(ctx, "other@site.ru", "secret123", "Чужой")["user"]["id"]
        for call in (lambda: projects.get_project(ctx, other, pid),
                     lambda: projects.get_plan(ctx, other, bid),
                     lambda: photos.photo_detail(ctx, other, last_id),
                     lambda: analysis.analyze(ctx, other, bid)):
            with self.assertRaises(ServiceError) as e:
                call()
            self.assertEqual(e.exception.status, 404)

    # ------------------------------------------------------------------
    def test_camera_labels(self):
        """Камера — метка точки съёмки: название, зона, объект. Снимки с камерой считаются по ней."""
        ctx = self.ctx
        uid = projects.register(ctx, "cams@site.ru", "secret123", "Камеры")["user"]["id"]
        pid = projects.create_project(ctx, uid, "Школа", "", "2025-01-01", "2026-06-30")["id"]
        bid = projects.create_building(ctx, uid, pid, "Школа на 1100 мест", "education")["id"]
        with self.assertRaises(ServiceError) as e:
            cameras.create_camera(ctx, uid, pid, "  ")
        self.assertEqual(e.exception.status, 422)
        cam = cameras.create_camera(ctx, uid, pid, "Мачта", zone="Котлован", building_id=bid)
        frames = self.images[6:9]
        for img in frames:
            self.annotate(img, [("pile_driver", (0.3, 0.1, 0.5, 0.9))])
        up = photos.upload_photos(ctx, uid, bid, self.files(frames), camera_id=cam["id"],
                                  start_at="2025-04-10T08:00", interval_min=30)
        self.assertEqual(up["uploaded"], 3)
        self.assertEqual([p["taken_at"] for p in up["photos"]],
                         ["2025-04-10T08:00:00", "2025-04-10T08:30:00", "2025-04-10T09:00:00"])
        v = analysis.analyze(ctx, uid, bid, at="2025-04-10T09:10")["verdict"]
        self.assertIn("PILING", v["stage"]["resolved"])
        got = cameras.get_camera(ctx, uid, cam["id"])
        self.assertEqual(got["photos_count"], 3)
        self.assertEqual(got["last_photo_at"], "2025-04-10T09:00:00")
        cameras.update_camera(ctx, uid, cam["id"], zone="Пятно застройки")
        self.assertEqual(cameras.get_camera(ctx, uid, cam["id"])["zone"], "Пятно застройки")
        cameras.delete_camera(ctx, uid, cam["id"])
        self.assertEqual(cameras.list_cameras(ctx, uid, pid), [])
        # снимки остаются, метка камеры снимается
        left = photos.list_photos(ctx, uid, bid, 10, 0, None, None, None, None)
        self.assertEqual(left["total"], 3)
        self.assertTrue(all(p["camera_id"] is None for p in left["items"]))



class HonestyTest(unittest.TestCase):
    """Без наблюдений система не имеет права показывать проценты и риски (найдено прогоном по ролям)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["DATA_DIR"] = str(cls.tmp / "data")
        cls.ctx = AppContext(Settings(), detector=MockDetector(str(cls.tmp)))
        cls.uid = projects.register(cls.ctx, "honest@site.ru", "secret123", "Ч")["user"]["id"]
        cls.pid = projects.create_project(cls.ctx, cls.uid, "Стройка", "", "2025-01-01", "2027-03-31")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_building_without_photos(self):
        bid = projects.create_building(self.ctx, self.uid, self.pid, "Без снимков", "housing")["id"]
        result = analysis.analyze(self.ctx, self.uid, bid, at="2026-05-01T12:00")
        self.assertEqual(result["verdict"]["status"], "unknown")
        self.assertIn("Снимков с объекта ещё не было", result["verdict"]["summary"])
        self.assertIsNone(result["timeline_summary"]["completion_percent"])
        self.assertIsNone(result["timeline_summary"]["spi"])
        self.assertEqual(result["timeline_summary"]["delay_risk"], "unknown")
        self.assertEqual(result["timeline_summary"]["max_delay_days"], 0)
        tl = analysis.timeline(self.ctx, self.uid, bid, at="2026-05-01T12:00")
        self.assertFalse(tl["observed"])
        self.assertLessEqual({r["status"] for r in tl["rows"]}, {"planned", "unconfirmed"})
        self.assertGreater(tl["planned_percent"], 0)          # план показывать можно

    def test_plan_without_active_tasks(self):
        bid = projects.create_building(self.ctx, self.uid, self.pid, "Пустой план", "housing")["id"]
        plan = projects.get_plan(self.ctx, self.uid, bid)
        roots = [t["id"] for t in plan["tasks"] if not t["parent_code"]]
        projects.bulk_toggle(self.ctx, self.uid, bid, roots, False)
        v = analysis.analyze(self.ctx, self.uid, bid)["verdict"]
        self.assertEqual(v["status"], "unknown")
        self.assertIn("нет активных работ", v["summary"])


class CleanupAndSecurityTest(unittest.TestCase):
    """Удаление файлов, защита от SSRF, требования к паролю."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["DATA_DIR"] = str(self.tmp / "data")
        os.environ.pop("ALLOW_LOCAL_CAMERAS", None)
        self.settings = Settings()
        self.ctx = AppContext(self.settings, detector=MockDetector(str(self.tmp)))
        self.uid = projects.register(self.ctx, "clean@site.ru", "secret123", "Ч")["user"]["id"]
        self.pid = projects.create_project(self.ctx, self.uid, "Стройка", "", "2025-01-01", "2026-12-31")["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ["ALLOW_LOCAL_CAMERAS"] = "1"

    def test_files_removed_with_building_and_project(self):
        img = sample_images(1, self.tmp)[0]
        bid = projects.create_building(self.ctx, self.uid, self.pid, "Корпус", "housing")["id"]
        res = photos.upload_photos(self.ctx, self.uid, bid, [(img.name, img.read_bytes())],
                                   start_at="2025-06-01T09:00")
        photos.image_file(self.ctx, self.uid, res["photo_ids"][0], width=200)     # создаём миниатюру
        folder = self.settings.photos_dir / str(bid)
        self.assertTrue(any(folder.iterdir()))
        self.assertTrue(any((self.settings.photos_dir / "thumbs").iterdir()))
        projects.delete_building(self.ctx, self.uid, bid)
        self.assertFalse(folder.exists())
        self.assertEqual(list((self.settings.photos_dir / "thumbs").glob("*.jpg")), [])

        bid2 = projects.create_building(self.ctx, self.uid, self.pid, "Корпус 2", "housing")["id"]
        photos.upload_photos(self.ctx, self.uid, bid2, [(img.name, img.read_bytes())], start_at="2025-06-01T09:00")
        projects.delete_project(self.ctx, self.uid, self.pid)
        self.assertFalse((self.settings.photos_dir / str(bid2)).exists())

    def test_camera_from_other_project_rejected(self):
        other = projects.create_project(self.ctx, self.uid, "Другая", "", "2025-01-01", "2026-01-01")["id"]
        bid = projects.create_building(self.ctx, self.uid, other, "Чужой корпус", "housing")["id"]
        with self.assertRaises(ServiceError) as e:
            cameras.create_camera(self.ctx, self.uid, self.pid, "Не туда", building_id=bid)
        self.assertEqual(e.exception.status, 422)

    def test_password_policy(self):
        for weak in ("1234567", "12345678", "password", "8"):
            with self.assertRaises(ServiceError, msg=weak):
                projects.register(self.ctx, f"w{len(weak)}{weak[:2]}@site.ru", weak, "W")
        projects.register(self.ctx, "good@site.ru", "kotlovan-7", "G")


class BusinessValueTest(unittest.TestCase):
    """Деньги, ссылка для заказчика, выгрузка и защита входа."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.ann = cls.tmp / "ann"
        cls.ann.mkdir()
        os.environ["DATA_DIR"] = str(cls.tmp / "data")
        cls.ctx = AppContext(Settings(), detector=MockDetector(str(cls.ann)))
        cls.uid = projects.register(cls.ctx, "value@site.ru", "secret123", "В")["user"]["id"]
        cls.pid = projects.create_project(cls.ctx, cls.uid, "Стройка", "", "2025-01-01", "2027-01-01")["id"]
        cls.bid = projects.create_building(cls.ctx, cls.uid, cls.pid, "Корпус", "housing")["id"]
        cls.cam = cameras.create_camera(cls.ctx, cls.uid, cls.pid, "Мачта", zone="Котлован",
                                        building_id=cls.bid)["id"]
        images = sample_images(4, cls.tmp)
        for img in images:                                  # автокран стоит на месте все кадры
            (cls.ann / (img.stem + ".json")).write_text(json.dumps(
                [{"cls": "mobile_crane", "bbox": [0.6, 0.1, 0.8, 0.9], "confidence": 0.9}]))
        cls.start = dt.datetime(2025, 6, 2, 8, 0)
        photos.upload_photos(cls.ctx, cls.uid, cls.bid, [(p.name, p.read_bytes()) for p in images],
                             camera_id=cls.cam, start_at=cls.start.isoformat(), interval_min=30)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_idle_not_measurable_without_camera(self):
        """Снимки без камеры: простой неизмерим, и это должно быть видно, а не выглядеть нулём-фактом."""
        bid = projects.create_building(self.ctx, self.uid, self.pid, "Без камеры", "housing")["id"]
        images = sample_images(2, self.tmp)
        photos.upload_photos(self.ctx, self.uid, bid, [(p.name, p.read_bytes()) for p in images],
                             start_at="2025-06-02T08:00", interval_min=30)
        money = analysis.analyze(self.ctx, self.uid, bid)["economics"]
        self.assertFalse(money["idle_measurable"])
        self.assertEqual(money["idle_total"], 0)
        self.assertEqual(money["photos_in_window"], 2)
        # с камерой — измеримо
        with_cam = analysis.analyze(self.ctx, self.uid, self.bid)["economics"]
        self.assertTrue(with_cam["idle_measurable"])

    def test_delay_is_not_multiplied_into_money(self):
        """Дни отставания не превращаются в рубли: это завышало потери в сотни раз."""
        money = analysis.analyze(self.ctx, self.uid, self.bid)["economics"]
        self.assertNotIn("delay_cost", money)
        self.assertNotIn("total", money)
        self.assertEqual(money["measured_total"], money["idle_total"])
        self.assertGreater(money["daily_fleet_cost"], 0)      # справка о стоимости дня — остаётся

    def test_idle_converted_to_money(self):
        money = analysis.analyze(self.ctx, self.uid, self.bid)["economics"]
        self.assertEqual(money["idle_minutes"], 90)          # 4 кадра по 30 мин: простой 90 мин
        crane = self.ctx.m.economics["shift_rates"]["mobile_crane"]
        self.assertEqual(money["idle_total"], round(90 / 60 * crane / 8))
        self.assertEqual(money["by_equipment"][0]["label"], "Автокран")
        self.assertEqual(money["currency"], "₽")

    def test_report_link_is_readonly_scoped_and_expires(self):
        link = analysis.create_report_link(self.ctx, self.uid, self.pid, ttl_hours=1)
        pid, owner = analysis.project_by_report_token(self.ctx, link["token"])
        self.assertEqual((pid, owner), (self.pid, self.uid))
        html = render_report(self.ctx, owner, pid)
        self.assertIn("Стройка", html)
        with self.assertRaises(ServiceError):                 # чужой проект по своей ссылке не открыть
            analysis.project_by_report_token(self.ctx, link["token"][:-3] + "abc")
        with self.assertRaises(ServiceError):
            analysis.create_report_link(self.ctx, self.uid, self.pid, ttl_hours=0)
        from app.security import create_scoped_token, decode_scoped_token
        expired = create_scoped_token(self.ctx.settings.secret_key, "report", self.pid, -1)
        self.assertIsNone(decode_scoped_token(expired, self.ctx.settings.secret_key, "report"))
        # токен отчёта не работает как токен пользователя
        self.assertIsNone(decode_scoped_token(link["token"], self.ctx.settings.secret_key, "user"))
        with self.assertRaises(ServiceError):
            projects.user_from_token(self.ctx, link["token"])

    def test_history_and_schema_migration(self):
        """Миграция v2 добавляет историю готовности; тренд считается по записанным вердиктам."""
        import sqlite3

        from app.db import SCHEMA_VERSION

        with sqlite3.connect(self.ctx.settings.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(verdicts)")}
        self.assertTrue({"completion_percent", "planned_percent", "idle_cost"} <= cols)

        analysis.analyze(self.ctx, self.uid, self.bid, at="2025-06-02T10:00", save=True)
        analysis.analyze(self.ctx, self.uid, self.bid, at="2025-08-02T10:00", save=True)
        h = analysis.history(self.ctx, self.uid, self.bid)
        self.assertGreaterEqual(len(h["points"]), 2)
        self.assertIsNotNone(h["change_percent"])
        self.assertEqual(h["points"][0]["at"] < h["points"][-1]["at"], True)   # по возрастанию времени

    def test_old_database_is_upgraded(self):
        """База, созданная до v2, открывается и достраивается, а не ломается."""
        import sqlite3

        from app.db import Database

        old = self.tmp / "old.sqlite3"
        with sqlite3.connect(old) as conn:
            conn.execute("CREATE TABLE verdicts (id INTEGER PRIMARY KEY AUTOINCREMENT, building_id INTEGER, "
                         "at TEXT, status TEXT, payload TEXT, created_at TEXT)")
            conn.execute("INSERT INTO verdicts (building_id, at, status, payload, created_at) "
                         "VALUES (1, '2025-01-01T10:00', 'ok', '{}', '2025-01-01T10:00')")
            conn.execute("PRAGMA user_version = 1")
        db = Database(old)
        row = db.one("SELECT * FROM verdicts WHERE id = 1")
        self.assertEqual(row["status"], "ok")               # старая запись на месте
        self.assertIsNone(row["completion_percent"])        # новые колонки добавлены пустыми

    def test_gallery_filters(self):
        by_cam = photos.list_photos(self.ctx, self.uid, self.bid, camera_id=self.cam)
        self.assertEqual(by_cam["total"], 4)
        by_cls = photos.list_photos(self.ctx, self.uid, self.bid, cls="mobile_crane")
        self.assertEqual(by_cls["total"], 4)
        self.assertEqual(photos.list_photos(self.ctx, self.uid, self.bid, cls="roller")["total"], 0)
        window = photos.list_photos(self.ctx, self.uid, self.bid, taken_from="2025-06-02T09:00",
                                    taken_to="2025-06-02T09:40")
        self.assertEqual(window["total"], 2)
        with self.assertRaises(ServiceError):
            photos.list_photos(self.ctx, self.uid, self.bid, cls="нечто")

    def test_deviations_csv_opens_in_excel(self):
        analysis.analyze(self.ctx, self.uid, self.bid, save=True)
        csv_text = analysis.deviations_csv(self.ctx, self.uid, self.bid)
        self.assertTrue(csv_text.startswith("\ufeff"))        # BOM: кириллица в Excel без настроек
        head, *rows = csv_text.lstrip("\ufeff").splitlines()
        self.assertEqual(head.split(";")[:3], ["Момент", "Важность", "Код"])
        self.assertTrue(rows)

    def test_login_bruteforce_is_throttled(self):
        for _ in range(10):
            with self.assertRaises(ServiceError):
                projects.login(self.ctx, "value@site.ru", "wrong-pass")
        with self.assertRaises(ServiceError) as e:
            projects.login(self.ctx, "value@site.ru", "wrong-pass")
        self.assertEqual(e.exception.status, 429)
        with self.assertRaises(ServiceError) as e:            # и верный пароль тоже ждёт
            projects.login(self.ctx, "value@site.ru", "secret123")
        self.assertEqual(e.exception.status, 429)
        self.ctx.login_attempts.clear()
        self.assertTrue(projects.login(self.ctx, "value@site.ru", "secret123")["token"])


class TrimBordersTest(unittest.TestCase):
    def test_trims_screenshot_margins_only(self):
        import io
        import numpy as np
        from app.services.photos import trim_borders

        rng = np.random.default_rng(0)
        content = rng.integers(40, 200, size=(200, 300, 3), dtype=np.uint8)
        framed = np.full((212, 310, 3), 255, dtype=np.uint8)
        framed[0:200, 0:300] = content                        # белые поля справа и снизу
        buf = io.BytesIO()
        Image.fromarray(framed).save(buf, "PNG")
        with Image.open(io.BytesIO(trim_borders(buf.getvalue()))) as out:
            self.assertEqual(out.size, (300, 200))

        snow = np.full((200, 300, 3), 250, dtype=np.uint8)    # однородно светлый кадр не режется целиком
        buf = io.BytesIO()
        Image.fromarray(snow).save(buf, "PNG")
        self.assertEqual(trim_borders(buf.getvalue()), buf.getvalue())

        if SAMPLES.exists() and (SAMPLES / "Screenshot_5.png").exists():
            raw = (SAMPLES / "Screenshot_5.png").read_bytes()
            with Image.open(io.BytesIO(raw)) as a, Image.open(io.BytesIO(trim_borders(raw))) as b:
                self.assertLess(b.size[0], a.size[0])


if __name__ == "__main__":
    unittest.main()


class MapAndAssistantTest(unittest.TestCase):
    """Карта строек (геокодирование без сети) и помощник по документации (бета)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ.update(DATA_DIR=str(cls.tmp / "data"), GEOCODER="off")
        cls.ctx = AppContext(Settings(), MockDetector())
        cls.uid = projects.register(cls.ctx, "map@site.ru", "secret123", "Карта")["user"]["id"]
        os.environ.pop("GEOCODER", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_geocode_offline_and_manual_point(self):
        from app.services import geo
        ctx, uid = self.ctx, self.uid
        pid = projects.create_project(ctx, uid, "ЖК", "Москва, Дмитровское ш., вл. 1", "2025-01-01", "2026-01-01")["id"]
        found = geo.geocode_project(ctx, uid, pid)
        self.assertEqual(found["geo_source"], "approx")
        self.assertAlmostEqual(found["lat"], 55.87, places=1)
        self.assertEqual(projects.list_projects(ctx, uid)[0]["lat"], found["lat"])
        # аббревиатура округа — отдельным словом, не внутри слова
        self.assertIsNotNone(geo.approximate("Москва, ЮЗАО, ул. Строителей"))
        self.assertIsNone(geo.approximate("Москва, Сао-Паульская ул."))
        unknown = projects.create_project(ctx, uid, "Без адреса", "", "2025-01-01", "2026-01-01")["id"]
        self.assertFalse(geo.geocode_project(ctx, uid, unknown)["found"])
        placed = projects.update_project(ctx, uid, unknown, lat=55.7, lon=37.6)
        self.assertEqual(placed["geo_source"], "manual")
        with self.assertRaises(ServiceError):
            projects.update_project(ctx, uid, unknown, lat=95, lon=37.6)
        # смена адреса сбрасывает точку — её определят заново
        moved = projects.update_project(ctx, uid, pid, address="Москва, Варшавское ш., 10")
        self.assertIsNone(moved["lat"])

    def test_assistant_intents_and_documents(self):
        from app.services import assistant
        ctx, uid = self.ctx, self.uid
        cases = {"Опиши текущий этап": "stage", "Почему возник простой?": "idle",
                 "не хватает эскаваторов, кому звонить?": "contacts", "Сколько стоит смена автокрана": "rates"}
        for q, intent in cases.items():
            self.assertEqual(assistant.compose_answer(ctx, uid, q)["intent"], intent, q)
        contacts = assistant.compose_answer(ctx, uid, "не хватает экскаваторов кому звонить")
        self.assertIn("Иванов Иван Иванович", contacts["text"])
        self.assertTrue(contacts["sources"])
        with self.assertRaises(ServiceError):
            assistant.compose_answer(ctx, uid, "   ")
        # текущий этап по реальной стройке пользователя
        pid = projects.create_project(ctx, uid, "Школа", "", "2025-01-01", "2026-06-30")["id"]
        projects.create_building(ctx, uid, pid, "Корпус А", "education")
        stage = assistant.compose_answer(ctx, uid, "Опиши текущий этап", pid)
        self.assertEqual(stage["project"], "Школа")
        self.assertIn("Корпус А", stage["text"])
        # загруженный документ находится поиском, чужой пользователь его не видит
        doc = assistant.add_document(ctx, uid, "регламент.txt", "Ответственный за генераторы — Петров П. П.".encode())
        self.assertIn("Петров", assistant.compose_answer(ctx, uid, "кто отвечает за генераторы")["text"])
        other = projects.register(ctx, "other@site.ru", "secret123", "Другой")["user"]["id"]
        self.assertNotIn("Петров", assistant.compose_answer(ctx, other, "кто отвечает за генераторы")["text"])
        with self.assertRaises(ServiceError):
            assistant.delete_document(ctx, other, doc["id"])
        self.assertTrue(all(d["builtin"] for d in assistant.list_documents(ctx, other)))
        assistant.delete_document(ctx, uid, doc["id"])
        lines = list(assistant.stream_answer(ctx, uid, "почему простой"))
        self.assertEqual([json.loads(lines[0])["type"], json.loads(lines[-1])["type"]], ["meta", "done"])


class _CountingDetector:
    """Детектор для тестов этапов: разметка задаётся по имени файла (``exc2_dump4.png``)."""
    name = "fake"
    CODES = {"exc": "excavator", "dump": "dump_truck", "pile": "pile_driver", "mix": "concrete_mixer",
             "pump": "concrete_pump", "tower": "tower_crane"}

    def detect(self, path):
        from app.core.types import Detection
        out = []
        stem = Path(path).stem.split("__", 1)[-1]
        for part in stem.split("_"):
            code = part.rstrip("0123456789")
            n = int(part[len(code):] or 1)
            for i in range(n):
                if code in self.CODES:
                    x = 0.05 + 0.09 * i
                    out.append(Detection(cls=self.CODES[code], confidence=0.9, bbox=(x, 0.4, x + 0.08, 0.6)))
        return out

    def info(self):
        return {"backend": self.name}


class StagesTest(unittest.TestCase):
    """Этап у каждого снимка, загрузка на этап, план ↔ факт, справочник и расчёты техники."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ.update(DATA_DIR=str(cls.tmp / "data"))
        cls.ctx = AppContext(Settings(), _CountingDetector())
        cls.uid = projects.register(cls.ctx, "stage@site.ru", "secret123", "Этапы")["user"]["id"]
        cls.pid = projects.create_project(cls.ctx, cls.uid, "ЖК", "", "2025-01-15", "2027-03-31")["id"]
        cls.bid = projects.create_building(cls.ctx, cls.uid, cls.pid, "Корпус 1", "housing")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def png(self, name: str, shade: int) -> tuple[str, bytes]:
        path = self.tmp / name
        Image.new("RGB", (320, 200), (shade, 90, 70)).save(path)
        return name, path.read_bytes()

    def test_auto_stage_manual_stage_and_plan_sync(self):
        from app.services import stages
        ctx, uid, bid = self.ctx, self.uid, self.bid
        plan = projects.get_plan(ctx, uid, bid)
        exc = next(p for p in plan["phases"] if p["phase"] == "EXCAVATION")
        # экскаватор + 4 самосвала в сроки котлована → этап «котлован» определяется сам, сразу после загрузки
        up = photos.upload_photos(ctx, uid, bid, [self.png("exc1_dump4.png", 10)], start_at=exc["start"] + "T09:00")
        self.assertEqual(up["photos"][0]["phase"], "EXCAVATION")
        self.assertEqual(up["photos"][0]["phase_source"], "auto")
        self.assertTrue(up["photos"][0]["phase_confirmed"])
        # количество решает при одинаковом наборе: один экскаватор и один самосвал вне сроков котлована
        # по нормам ближе к наружным сетям/выносу сетей, чем к котловану (самосвалов меньше минимума)
        from app.core.norms import quantity_fit, requirements
        few = {"excavator": 1, "dump_truck": 1}
        self.assertGreater(quantity_fit(few, requirements(ctx.m, ctx.norms, "housing", "EXT_NETWORKS")),
                           quantity_fit(few, requirements(ctx.m, ctx.norms, "housing", "EXCAVATION")))
        # загрузка на конкретный этап: несколько снимков на один этап, этап не перезаписывается автоматикой
        pil = next(p for p in plan["phases"] if p["phase"] == "PILING")
        up2 = photos.upload_photos(ctx, uid, bid, [self.png("pile1.png", 20), self.png("exc1.png", 30)],
                                   start_at=pil["start"] + "T10:00", phase="PILING")
        self.assertEqual([p["phase"] for p in up2["photos"]], ["PILING", "PILING"])
        self.assertEqual({p["phase_source"] for p in up2["photos"]}, {"manual"})
        self.assertNotEqual(up2["photos"][1]["auto_phase"], "PILING")      # по технике — не сваи
        with self.assertRaises(ServiceError):
            photos.upload_photos(ctx, uid, bid, [self.png("x.png", 40)], phase="NOPE")

        summary = stages.stage_list(ctx, uid, bid)
        by = {s["phase"]: s for s in summary["stages"]}
        self.assertEqual(by["EXCAVATION"]["photos"], 1)
        self.assertEqual(by["PILING"]["photos"], 2)
        self.assertEqual(by["PILING"]["photo_start"], pil["start"])
        self.assertTrue(by["PILING"]["photo_days"])
        self.assertTrue(by["EXCAVATION"]["tasks"])
        self.assertTrue(all(t["equipment"] for t in by["EXCAVATION"]["tasks"]))
        self.assertEqual(by["FOUNDATION"]["photos"], 0)

        detail = stages.stage_detail(ctx, uid, bid, "PILING")
        self.assertEqual(len(detail["photos"]), 2)
        self.assertTrue(detail["docs"])
        self.assertTrue(any(p["mismatch"] for p in detail["photos"]))
        required = [c for c in detail["check"] if c["role"] == "required"]
        self.assertEqual(required[0]["state"], "ok")                          # буровая установка есть
        # перенос снимка на другой этап и возврат к автоопределению
        moved = photos.set_photo_phase(ctx, uid, up2["photo_ids"][1], "EXCAVATION")
        self.assertEqual((moved["phase"], moved["phase_source"]), ("EXCAVATION", "manual"))
        back = photos.set_photo_phase(ctx, uid, up2["photo_ids"][1], "")
        self.assertEqual(back["phase_source"], "auto")
        # фильтр галереи по этапу
        self.assertEqual(photos.list_photos(ctx, uid, bid, 50, 0, phase="PILING")["total"], 1)

    def test_reference_tables_link_type_phase_equipment(self):
        from app.services import stages
        rows = self.ctx.db.all(
            "SELECT pe.min_count, pe.max_count FROM phase_equipment pe "
            "WHERE pe.object_type = 'housing' AND pe.phase_id = 'EXCAVATION' AND pe.cls = 'dump_truck'")
        self.assertEqual(rows, [{"min_count": 2, "max_count": 8}])
        roads = stages.norms_matrix(self.ctx, "roads")["object_types"][0]
        self.assertIn("ROAD_WORKS", [p["phase"] for p in roads["phases"]])
        frame = next(p for p in roads["phases"] if p["phase"] == "FRAME")
        self.assertNotIn("tower_crane", [e["cls"] for e in frame["equipment"]])   # на дороге башенный кран не ставят
        housing = stages.norms_matrix(self.ctx, "housing")["object_types"][0]
        self.assertNotIn("ROAD_WORKS", [p["phase"] for p in housing["phases"]])
        self.assertTrue(all(p["docs"] for p in housing["phases"] if p["phase"] != "ORGANIZATION"))
        with self.assertRaises(ServiceError):
            stages.norms_matrix(self.ctx, "spaceport")

    def test_equipment_calculations(self):
        from app.core.norms import calc_concreting, calc_excavation, calc_tower_crane
        ex = calc_excavation(volume_m3=20000, days=20)
        self.assertEqual(ex["result"]["excavator"], 2)          # 20 000 / (810 м³/смену · 20) → 2
        self.assertEqual(ex["result"]["dump_truck"], 18)        # 9 самосвалов на экскаватор при плече 10 км
        near = calc_excavation(volume_m3=20000, days=20, distance_km=2)
        self.assertLess(near["result"]["dump_truck"], ex["result"]["dump_truck"])
        con = calc_concreting(volume_m3=480, hours=16)
        self.assertEqual(con["result"], {"concrete_pump": 1, "concrete_mixer": 6})
        cr = calc_tower_crane(building_height_m=75, building_width_m=18, building_length_m=120)
        self.assertEqual(cr["result"]["hook_height_m"], 83.0)
        self.assertGreaterEqual(cr["result"]["tower_crane"], 2)
        with self.assertRaises(ValueError):
            calc_excavation(volume_m3=0, days=5)
