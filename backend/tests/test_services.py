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
    def test_http_camera_and_emulator(self):
        ctx = self.ctx
        uid = projects.register(ctx, "cams@site.ru", "secret123", "Камеры")["user"]["id"]
        pid = projects.create_project(ctx, uid, "Школа", "", "2025-01-01", "2026-06-30")["id"]
        bid = projects.create_building(ctx, uid, pid, "Школа на 1100 мест", "education")["id"]

        # HTTP-камера: локальный сервер отдаёт реальный снимок
        www = self.tmp / "www"
        www.mkdir(exist_ok=True)
        shutil.copy(self.images[0], www / "snapshot.png")
        self.annotate(self.images[0], [])   # имя кадра другое, разметки нет
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/snapshot.png"
            with self.assertRaises(ServiceError):
                cameras.create_camera(ctx, uid, pid, "Без объекта", source_type="http", url=url)
            cam = cameras.create_camera(ctx, uid, pid, "Мачта", source_type="http", url=url, building_id=bid,
                                        zone="Пятно застройки", interval_min=30, active=True)
            self.assertEqual([c["id"] for c in cameras.due_cameras(ctx)], [cam["id"]])
            result = cameras.poll_due(ctx)
            self.assertEqual(result, {"polled": 1, "failed": 0})
            self.assertEqual(cameras.due_cameras(ctx), [])            # следующий опрос через 30 мин
            later = dt.datetime.now() + dt.timedelta(minutes=31)
            self.assertEqual(len(cameras.due_cameras(ctx, later)), 1)
            broken = cameras.create_camera(ctx, uid, pid, "Сломанная", source_type="http",
                                           url=url.replace("snapshot", "missing"), building_id=bid, active=True)
            self.assertEqual(cameras.poll_due(ctx)["failed"], 1)
            self.assertTrue(cameras.get_camera(ctx, uid, broken["id"])["last_error"])
        finally:
            server.shutdown()

        # Эмулятор: 3 кадра, шаг 30 минут условного времени
        emu = cameras.create_camera(ctx, uid, pid, "Эмулятор", source_type="emulator", building_id=bid,
                                    zone="Котлован", interval_min=30, tick_seconds=5,
                                    emulator_start="2025-04-10T08:00")
        frames = self.images[6:9]
        for img in frames:
            self.annotate(img, [("pile_driver", (0.3, 0.1, 0.5, 0.9))])
        up = cameras.upload_emulator_frames(ctx, uid, emu["id"], self.files(frames) + [("x.txt", b"no")])
        self.assertEqual(up["saved"], 3)
        self.assertEqual(len(up["errors"]), 1)
        cameras.update_camera(ctx, uid, emu["id"], active=True)
        taken = []
        for _ in range(3):
            taken.append(cameras.poll_now(ctx, uid, emu["id"])["taken_at"])
        self.assertEqual(taken, ["2025-04-10T08:00:00", "2025-04-10T08:30:00", "2025-04-10T09:00:00"])
        with self.assertRaises(ServiceError) as e:
            cameras.poll_now(ctx, uid, emu["id"])
        self.assertEqual(e.exception.status, 409)
        self.assertFalse(cameras.get_camera(ctx, uid, emu["id"])["active"])   # остановился сам

        v = analysis.analyze(ctx, uid, bid, at="2025-04-10T09:10")["verdict"]
        self.assertIn("PILING", v["stage"]["resolved"])
        cams = {c["name"]: c for c in cameras.list_cameras(ctx, uid, pid)}
        self.assertEqual(cams["Эмулятор"]["photos_count"], 3)
        cameras.reset_emulator(ctx, uid, emu["id"], "2025-04-11T08:00")
        self.assertEqual(cameras.get_camera(ctx, uid, emu["id"])["emulator_cursor"], 0)



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

    def test_camera_cannot_point_at_service_itself(self):
        bid = projects.create_building(self.ctx, self.uid, self.pid, "Корпус", "housing")["id"]
        for url in ("http://127.0.0.1:8000/api/health", "http://169.254.169.254/latest/meta-data/",
                    "http://localhost/snapshot.jpg"):
            with self.assertRaises(ServiceError, msg=url) as e:
                cameras.create_camera(self.ctx, self.uid, self.pid, "SSRF", source_type="http",
                                       url=url, building_id=bid)
            self.assertEqual(e.exception.status, 422)
        # камера в локальной сети стройки разрешена
        cameras.check_camera_host("http://10.0.0.15/snapshot.jpg")
        cameras.check_camera_host("http://192.168.1.50/img.jpg")

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
