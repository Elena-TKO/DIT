"""Тесты HTTP-слоя.

* Если FastAPI установлен (docker / локальная venv) — настоящий HTTP-сценарий через TestClient.
* Если нет — подставляются заглушки из tests/stubs и проверяется связка роутов:
  path-параметры совпадают с сигнатурами, у всех параметров есть корректные маркеры,
  и весь пользовательский сценарий проходит через функции роутов.
"""
import importlib
import inspect
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient
    REAL_FASTAPI = True
except ImportError:
    REAL_FASTAPI = False
    sys.path.insert(0, str(Path(__file__).parent / "stubs"))

SAMPLE = Path("/mnt/project/Screenshot_13.png")


def image_bytes(tmp: Path) -> bytes:
    if SAMPLE.exists():
        return SAMPLE.read_bytes()
    p = tmp / "img.png"
    Image.new("RGB", (320, 200), (90, 80, 70)).save(p)
    return p.read_bytes()


class ApiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "ann").mkdir()
        os.environ.update(DATA_DIR=str(cls.tmp / "data"), ENABLE_CAMERA_POLLER="0", DETECTOR="mock",
                          MOCK_ANNOTATIONS_DIR=str(cls.tmp / "ann"), FRONTEND_DIST=str(cls.tmp / "nodist"),
                          ALLOW_LOCAL_CAMERAS="1")
        (cls.tmp / "ann" / "site.json").write_text(
            '[{"cls": "excavator", "bbox": [0.1, 0.4, 0.3, 0.7]}, {"cls": "pile_driver", "bbox": [0.5, 0.1, 0.6, 0.9]}]')
        cls.image = image_bytes(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


@unittest.skipUnless(REAL_FASTAPI, "FastAPI не установлен — см. RouteGlueTest")
class HttpFlowTest(ApiBase):
    def test_http_flow(self):
        from app.main import create_app

        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/health").json()["detector"]["backend"], "mock")
            self.assertEqual(client.get("/api/projects").status_code, 401)
            token = client.post("/api/auth/register", json={"email": "a@b.ru", "password": "secret12"}).json()["token"]
            h = {"Authorization": f"Bearer {token}"}
            pid = client.post("/api/projects", headers=h, json={
                "name": "ЖК", "start_date": "2025-01-01", "end_date": "2026-12-31"}).json()["id"]
            r = client.post(f"/api/projects/{pid}/buildings", headers=h, json={"name": "К1", "object_type": "housing"})
            self.assertEqual(r.status_code, 201, r.text)
            bid = r.json()["id"]
            plan = client.get(f"/api/buildings/{bid}/plan", headers=h).json()
            task = plan["tasks"][5]
            r = client.patch(f"/api/buildings/{bid}/plan/tasks/{task['id']}", headers=h, json={"enabled": False})
            self.assertEqual(r.status_code, 200, r.text)
            cam = client.post(f"/api/projects/{pid}/cameras", headers=h, json={"name": "Север", "zone": "Котлован"}).json()
            r = client.post(f"/api/buildings/{bid}/photos", headers=h,
                            files=[("files", ("site.png", self.image, "image/png"))],
                            data={"camera_id": str(cam["id"]), "start_at": "2025-05-10T10:00", "interval_min": "30"})
            self.assertEqual(r.status_code, 201, r.text)
            photo_id = r.json()["photo_ids"][0]
            detail = client.get(f"/api/photos/{photo_id}", headers=h).json()
            self.assertEqual(len(detail["detections"]), 2)
            img = client.get(f"/api/photos/{photo_id}/image?w=200&token={token}")
            self.assertEqual(img.headers["content-type"], "image/jpeg")
            self.assertEqual(client.post(f"/api/buildings/{bid}/analysis", headers=h).status_code, 200)
            self.assertIn("rows", client.get(f"/api/buildings/{bid}/timeline", headers=h).json())
            html = client.get(f"/api/projects/{pid}/report.html", headers=h)
            self.assertIn("text/html", html.headers["content-type"])
            self.assertEqual(client.get("/api/projects/999", headers=h).status_code, 404)
            self.assertEqual(client.delete(f"/api/photos/{photo_id}", headers=h).status_code, 204)


@unittest.skipIf(REAL_FASTAPI, "Есть настоящий FastAPI — используется HttpFlowTest")
class RouteGlueTest(ApiBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in [m for m in sys.modules if m.startswith("app.main") or m.startswith("app.api")]:
            del sys.modules[name]
        cls.main = importlib.import_module("app.main")
        cls.app = cls.main.create_app()
        from app.config import Settings
        from app.ml.detectors import MockDetector
        from app.services.common import AppContext
        cls.ctx = AppContext(Settings(), detector=MockDetector(str(cls.tmp / "ann")))
        cls.app.state.ctx = cls.ctx

    def routes(self):
        return {(r["method"], r["path"]): r for r in self.app.routes}

    def test_route_signatures(self):
        from fastapi import _Marker
        routes = self.app.routes
        self.assertGreaterEqual(len(routes), 40)
        keys = [(r["method"], r["path"]) for r in routes]
        self.assertEqual(len(keys), len(set(keys)), "дублирующиеся роуты")
        for r in routes:
            fn, path = r["endpoint"], r["path"]
            path_params = set(re.findall(r"{(\w+)}", path))
            params = inspect.signature(fn).parameters
            self.assertTrue(path_params <= set(params), f"{path}: нет параметров {path_params - set(params)}")
            bodies = []
            for name, p in params.items():
                if name in path_params:
                    self.assertIs(p.default, inspect.Parameter.empty, f"{path}:{name}")
                    expected = "str" if name in ("token", "phase") else "int"   # id — числа; ссылка и код этапа — строки
                    self.assertEqual(p.annotation, expected, f"{path}:{name} должен быть {expected}")
                elif p.default is inspect.Parameter.empty:
                    bodies.append(name)
                    self.assertTrue(p.annotation.startswith("schemas."), f"{path}:{name} — тело без схемы")
                else:
                    self.assertIsInstance(p.default, _Marker, f"{path}:{name} без Query/Depends/Form")
            self.assertLessEqual(len(bodies), 1, path)
            if r["method"] in ("GET", "DELETE"):
                self.assertEqual(bodies, [], f"{path}: тело у {r['method']}")
            if r.get("status_code") == 204:
                src = inspect.getsource(fn)
                self.assertIn("Response(status_code=204)", src, path)
            if path == "/":
                continue
            public = ("/api/auth/register", "/api/auth/login", "/api/health", "/api/object-types",
                      "/api/methodology", "/api/catalog", "/api/public/")
            if "user" not in params and not path.startswith(public):
                self.fail(f"{path}: роут без авторизации")

    def test_flow_through_route_functions(self):
        from fastapi import Request, UploadFile
        from app import schemas
        from app.api.deps import current_user
        R, ctx = self.routes(), self.ctx

        def call(method, path, **kw):
            return R[(method, path)]["endpoint"](ctx=ctx, **kw)

        session = call("POST", "/api/auth/register", body=schemas.RegisterIn(email="g@h.ru", password="secret12"))
        uid = current_user(Request(self.app), authorization=f"Bearer {session['token']}", token=None)
        self.assertEqual(current_user(Request(self.app), authorization=None, token=session["token"]), uid)
        project = call("POST", "/api/projects", user=uid,
                       body=schemas.ProjectIn(name="ЖК", start_date="2025-01-01", end_date="2026-12-31"))
        pid = project["id"]
        call("PATCH", "/api/projects/{project_id}", user=uid, project_id=pid, body=schemas.ProjectPatch(address="Москва"))
        b = call("POST", "/api/projects/{project_id}/buildings", user=uid, project_id=pid,
                 body=schemas.BuildingIn(name="К1", object_type="housing"))
        bid = b["id"]
        plan = call("GET", "/api/buildings/{building_id}/plan", user=uid, building_id=bid)
        tid = plan["tasks"][3]["id"]
        call("PATCH", "/api/buildings/{building_id}/plan/tasks/{task_id}", user=uid, building_id=bid, task_id=tid,
             body=schemas.TaskPatch(enabled=False))
        call("POST", "/api/buildings/{building_id}/plan/bulk", user=uid, building_id=bid,
             body=schemas.BulkToggleIn(task_ids=[tid], enabled=True))
        call("POST", "/api/buildings/{building_id}/plan/reschedule", user=uid, building_id=bid)
        call("PATCH", "/api/buildings/{building_id}", user=uid, building_id=bid,
             body=schemas.BuildingPatch(end_date="2027-01-31", reschedule=True))
        cam = call("POST", "/api/projects/{project_id}/cameras", user=uid, project_id=pid,
                   body=schemas.CameraIn(name="Мачта", zone="Котлован", building_id=bid))
        cam = call("PATCH", "/api/cameras/{camera_id}", user=uid, camera_id=cam["id"],
                   body=schemas.CameraPatch(zone="Пятно застройки"))
        self.assertEqual(cam["zone"], "Пятно застройки")
        up = call("POST", "/api/buildings/{building_id}/photos", user=uid, building_id=bid,
                  files=[UploadFile("site.png", self.image)], camera_id=str(cam["id"]),
                  start_at="2025-05-01T08:30", interval_min=30, phase=None)
        self.assertEqual(up["uploaded"], 1, up["errors"])
        up2 = call("POST", "/api/buildings/{building_id}/photos", user=uid, building_id=bid,
                   files=[UploadFile("site.png", self.image)], camera_id="", start_at=None, interval_min=30, phase=None)
        self.assertEqual(up2["uploaded"], 1)
        photo_id = up["photo_ids"][0]
        detail = call("GET", "/api/photos/{photo_id}", user=uid, photo_id=photo_id)
        self.assertEqual({d["cls"] for d in detail["detections"]}, {"excavator", "pile_driver"})
        img = call("GET", "/api/photos/{photo_id}/image", user=uid, photo_id=photo_id, w=240)
        self.assertEqual(img.media_type, "image/jpeg")
        call("PUT", "/api/photos/{photo_id}/detections", user=uid, photo_id=photo_id,
             body=schemas.DetectionsIn(items=[schemas.DetectionIn(cls="dump_truck", bbox=[0.1, 0.1, 0.3, 0.3])]))
        call("POST", "/api/photos/{photo_id}/redetect", user=uid, photo_id=photo_id)
        a = call("POST", "/api/buildings/{building_id}/analysis", user=uid, building_id=bid, at="2025-05-01T09:00")
        self.assertIn(a["verdict"]["status"], ("ok", "warning", "critical"))
        log = call("GET", "/api/buildings/{building_id}/deviations", user=uid, building_id=bid, limit=10)
        self.assertEqual(len(log), len(a["verdict"]["deviations"]))
        self.assertIn("PILING", a["verdict"]["stage"]["resolved"])
        tl = call("GET", "/api/buildings/{building_id}/timeline", user=uid, building_id=bid, at=None)
        self.assertTrue(tl["rows"])
        ov = call("GET", "/api/projects/{project_id}/overview", user=uid, project_id=pid)
        self.assertEqual(len(ov["buildings"]), 1)
        rep = call("GET", "/api/projects/{project_id}/report.html", user=uid, project_id=pid, at=None)
        self.assertIn("Рекомендации по установке камер", rep.body)
        self.assertEqual(call("GET", "/api/health")["catalog_items"], 377)
        link = call("POST", "/api/projects/{project_id}/report-link", user=uid, project_id=pid, ttl_hours=24)
        public = call("GET", "/api/public/report/{token}", token=link["token"])
        self.assertIn("Рекомендации по установке камер", public.body)
        csv_text = call("GET", "/api/buildings/{building_id}/deviations.csv", user=uid, building_id=bid)
        self.assertIn("Важность", csv_text.body)
        self.assertIn("Открыть интерфейс", R[("GET", "/")]["endpoint"]().body)
        self.assertEqual(len(call("GET", "/api/catalog", object_type="roads")), 2)
        # этапы: сводка план/факт, страница этапа, ручная привязка снимка, справочник и расчёт
        st = call("GET", "/api/buildings/{building_id}/stages", user=uid, building_id=bid)
        self.assertTrue(st["stages"])
        ph = st["stages"][0]["phase"]
        self.assertEqual(call("GET", "/api/buildings/{building_id}/stages/{phase}", user=uid, building_id=bid,
                              phase=ph)["phase"], ph)
        moved = call("PATCH", "/api/photos/{photo_id}", user=uid, photo_id=photo_id,
                     body=schemas.PhotoPatch(phase=ph))
        self.assertEqual(moved["phase_source"], "manual")
        self.assertTrue(call("GET", "/api/methodology/norms", object_type="housing")["object_types"][0]["phases"])
        calc = call("POST", "/api/methodology/calc", body=schemas.CalcIn(kind="concreting",
                                                                     params={"volume_m3": 100, "hours": 8}))
        self.assertIn("concrete_mixer", calc["result"])
        # карта: ручная точка и повторное геокодирование её не перетирает
        placed = call("PATCH", "/api/projects/{project_id}", user=uid, project_id=pid,
                      body=schemas.ProjectPatch(lat=55.75, lon=37.61))
        self.assertEqual((placed["lat"], placed["geo_source"]), (55.75, "manual"))
        self.assertEqual(call("POST", "/api/projects/{project_id}/geocode", user=uid, project_id=pid,
                              force=False)["geo_source"], "manual")
        # помощник: поток NDJSON собирается в ответ с источниками
        import json as _json
        stream = call("POST", "/api/assistant/chat", user=uid,
                      body=schemas.AssistantIn(question="Контакты ответственных за экскаваторы", project_id=pid))
        events = [_json.loads(line) for line in stream.body]
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("Иванов", "".join(e.get("text", "") for e in events))
        doc = call("POST", "/api/assistant/documents", user=uid,
                   file=UploadFile("регламент.txt", "Ответственный за генераторы — Петров П. П.".encode()))
        self.assertTrue(any(d["id"] == doc["id"] for d in call("GET", "/api/assistant/documents", user=uid)))
        self.assertEqual(call("DELETE", "/api/assistant/documents/{doc_id}", user=uid,
                              doc_id=doc["id"]).status_code, 204)
        for method, path, kw in [("DELETE", "/api/photos/{photo_id}", {"photo_id": photo_id}),
                                 ("DELETE", "/api/cameras/{camera_id}", {"camera_id": cam["id"]}),
                                 ("DELETE", "/api/buildings/{building_id}", {"building_id": bid}),
                                 ("DELETE", "/api/projects/{project_id}", {"project_id": pid})]:
            self.assertEqual(call(method, path, user=uid, **kw).status_code, 204)
        self.assertEqual(call("GET", "/api/projects", user=uid), [])


if __name__ == "__main__":
    unittest.main()
