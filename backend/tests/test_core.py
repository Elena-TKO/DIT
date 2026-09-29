"""Тесты бизнес-логики: справочник, методика, план, этапы, активность, вердикт, таймлайн."""
import datetime as dt
import json
import unittest

from app.core.activity import assign_activity
from app.core.catalog import load_catalog, OBJECT_TYPES
from app.core.methodology import load_methodology, build_methodology, DEFAULT_METHODOLOGY_PATH
from app.core.planner import generate_plan, recompute_summaries, effective_enabled
from app.core.recommend import recommendations
from app.core.stage import detect_stage
from app.core.timeline import build_timeline
from app.core.types import Detection, PhotoObs
from app.core.verdict import build_verdict

M = load_methodology()
ITEMS = load_catalog()


def det(cls, box=(0.1, 0.1, 0.3, 0.3), conf=0.9):
    return Detection(cls=cls, confidence=conf, bbox=box)


def photo(pid, when, *classes, camera=1, zone="Котлован"):
    return PhotoObs(id=pid, taken_at=when, camera_id=camera, camera_name="Север", zone=zone,
                    detections=[det(c, (0.05 * i, 0.1, 0.05 * i + 0.1, 0.3)) for i, c in enumerate(classes)])


def plan_dicts(object_type="housing", start="2025-01-01", end="2026-12-31"):
    tasks = [t.to_dict() for t in generate_plan(ITEMS, object_type, start, end, M)]
    return [t for t in tasks if not t["is_summary"]]


class CatalogTest(unittest.TestCase):
    def test_parsed_items(self):
        self.assertEqual(len(ITEMS), 377)
        codes = [i.code for i in ITEMS]
        self.assertEqual(len(codes), len(set(codes)))
        by = {i.code: i for i in ITEMS}
        # Номера, превращённые Excel в даты, восстановлены
        self.assertEqual(by["10.11"].name, "Обустройство строительной площадки")
        self.assertEqual(by["12.3"].name, "Устройство подземной части")
        self.assertEqual(by["12.3.1"].parent_code, "12.3")
        self.assertEqual(by["10.2.u1"].parent_code, "10.2")

    def test_type_marks(self):
        by = {i.code: i for i in ITEMS}
        self.assertEqual(by["10.11.1"].types, ["roads"])       # ограждение — только дороги
        self.assertEqual(set(by["12.3.1"].types), set(OBJECT_TYPES))
        self.assertNotIn("housing", by["12.6.11"].types)      # мебель — не жильё


class MethodologyTest(unittest.TestCase):
    def test_every_item_has_known_phase(self):
        by = {i.code: i for i in ITEMS}
        for it in ITEMS:
            self.assertIn(M.phase_for_item(it, by), M.phases)

    def test_key_mappings(self):
        by = {i.code: i for i in ITEMS}
        expect = {"12.3.1": "EXCAVATION", "12.3.7.u10": "PILING", "12.3.4.u6": "FOUNDATION",
                  "12.4.4": "FRAME", "12.4.31.u1": "ENVELOPE", "12.7.1": "LANDSCAPING",
                  "10.3": "DEMOLITION", "10.13.1": "ORGANIZATION", "12.5.1.u2": "EXT_NETWORKS",
                  "12.5.2.u2": "INT_SYSTEMS", "12.4.30": "FRAME", "12.3.7.u2": "BACKFILL"}
        for code, phase in expect.items():
            self.assertEqual(M.phase_for_item(by[code], by), phase, code)

    def test_validation_rejects_unknown_class(self):
        with open(DEFAULT_METHODOLOGY_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        raw["phases"][1]["required"] = [["spaceship"]]
        with self.assertRaises(ValueError):
            build_methodology(raw)

    def test_distinctive_classes_weigh_more(self):
        self.assertGreater(M.class_weights["pile_driver"], M.class_weights["truck"])


class PlannerTest(unittest.TestCase):
    def test_dates_inside_building_period(self):
        tasks = generate_plan(ITEMS, "housing", "2025-03-01", "2027-03-01", M)
        leaves = [t for t in tasks if not t.is_summary]
        self.assertTrue(leaves)
        for t in leaves:
            self.assertGreaterEqual(t.start_date, "2025-03-01")
            self.assertLessEqual(t.end_date, "2027-03-01")
            self.assertLess(t.start_date, t.end_date)
        exc = min(t.start_date for t in leaves if t.phase == "EXCAVATION")
        frame = min(t.start_date for t in leaves if t.phase == "FRAME")
        land = min(t.start_date for t in leaves if t.phase == "LANDSCAPING")
        self.assertLess(exc, frame)
        self.assertLess(frame, land)

    def test_summary_spans_children_and_disable(self):
        tasks = [t.to_dict() for t in generate_plan(ITEMS, "housing", "2025-01-01", "2026-01-01", M)]
        by = {t["code"]: t for t in tasks}
        kids = [t for t in tasks if t["parent_code"] == "12.3.4"]
        self.assertEqual(by["12.3.4"]["start_date"], min(k["start_date"] for k in kids))
        for k in kids:
            k["enabled"] = False
        recompute_summaries(tasks)
        self.assertIsNone(by["12.3.4"]["start_date"])
        by["12.3"]["enabled"] = False
        eff = effective_enabled(tasks)
        self.assertFalse(eff["12.3.1"])
        self.assertTrue(eff["12.4.4"])

    def test_roads_plan_differs(self):
        roads = {t.phase for t in generate_plan(ITEMS, "roads", "2025-01-01", "2026-01-01", M) if t.phase}
        housing = {t.phase for t in generate_plan(ITEMS, "housing", "2025-01-01", "2026-01-01", M) if t.phase}
        self.assertIn("ROAD_WORKS", roads)
        self.assertNotIn("ROAD_WORKS", housing)

    def test_bad_dates(self):
        with self.assertRaises(ValueError):
            generate_plan(ITEMS, "housing", "2025-01-01", "2024-01-01", M)


class StageTest(unittest.TestCase):
    def test_pile_driver_means_piling(self):
        r = detect_stage({"pile_driver", "mobile_crane"}, M)
        self.assertEqual(r.top_phase, "PILING")

    def test_ambiguity_resolved_by_plan(self):
        r = detect_stage({"excavator", "dump_truck"}, M, planned={"EXCAVATION"})
        self.assertEqual(r.top_phase, "EXCAVATION")
        self.assertEqual(r.resolved, ["EXCAVATION"])
        self.assertIn("NETWORKS_RELOCATION", r.ambiguous_with)

    def test_concurrent_phases_explain_away(self):
        r = detect_stage({"excavator", "dump_truck", "pile_driver"}, M, planned={"EXCAVATION"})
        self.assertEqual(set(r.resolved), {"EXCAVATION", "PILING"})

    def test_incomplete_set(self):
        r = detect_stage({"excavator"}, M, planned={"EXCAVATION"})
        self.assertNotEqual(r.top_phase, "EXCAVATION")

    def test_partial_planned_phase_is_not_off_plan_evidence(self):
        r = detect_stage({"excavator", "mobile_crane"}, M, planned={"EXCAVATION", "PILING"})
        self.assertEqual(r.resolved, [])
        self.assertIn("Разработка грунта", r.explanation)
        self.assertIn("Самосвал", r.explanation)

    def test_nothing(self):
        r = detect_stage(set(), M)
        self.assertIsNone(r.top_phase)
        self.assertIn("не обнаружена", r.explanation)


class ActivityTest(unittest.TestCase):
    def test_idle_and_working(self):
        t0 = dt.datetime(2025, 5, 1, 10, 0)
        crane_box = (0.5, 0.2, 0.7, 0.8)
        frames = [
            PhotoObs(1, t0, 1, detections=[det("mobile_crane", crane_box), det("excavator", (0.1, 0.5, 0.2, 0.6))]),
            PhotoObs(2, t0 + dt.timedelta(minutes=30), 1,
                     detections=[det("mobile_crane", crane_box), det("excavator", (0.3, 0.5, 0.4, 0.6))]),
            PhotoObs(3, t0 + dt.timedelta(minutes=60), 1, detections=[det("mobile_crane", crane_box)]),
            PhotoObs(4, t0 + dt.timedelta(hours=5), 1, detections=[det("mobile_crane", crane_box)]),
        ]
        assign_activity(frames, M)
        self.assertEqual(frames[0].detections[0].activity, "unknown")
        self.assertEqual(frames[1].detections[0].activity, "idle")
        self.assertEqual(frames[1].detections[1].activity, "working")
        self.assertEqual(frames[2].detections[0].idle_minutes, 60)
        self.assertEqual(frames[3].detections[0].activity, "unknown")   # большой разрыв


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.tasks = plan_dicts()
        exc = [t for t in self.tasks if t["phase"] == "EXCAVATION"]
        s = max(t["start_date"] for t in exc)
        self.day = dt.date.fromisoformat(s) + dt.timedelta(days=1)
        self.at = dt.datetime.combine(self.day, dt.time(15, 0))

    def test_example_from_task_missing_dump_trucks(self):
        photos = [photo(1, self.at - dt.timedelta(hours=1), "excavator", "excavator")]
        v = build_verdict(M, self.at, self.tasks, photos)
        self.assertIn("EXCAVATION", [p["phase"] for p in v["planned_phases"]])
        miss = [d for d in v["deviations"] if d["kind"] == "MISSING_EQUIPMENT" and d["phase"] == "EXCAVATION"]
        self.assertEqual(len(miss), 1)
        self.assertIn("Самосвал", miss[0]["message"])
        self.assertIn("Экскаватор", miss[0]["message"])
        self.assertEqual(miss[0]["zones"], ["Котлован"])
        self.assertEqual(miss[0]["photo_ids"], [1])
        self.assertIn(v["status"], ("warning", "critical"))
        exc = next(c for c in v["checklist"] if c["phase"] == "EXCAVATION")
        self.assertEqual([g["present"] for g in exc["required"]], [True, False])

    def test_no_data(self):
        v = build_verdict(M, self.at, self.tasks, [])
        self.assertTrue(any(d["kind"] == "NO_DATA" for d in v["deviations"]))

    def test_behind_schedule_pile_driver_during_frame(self):
        frame_start = min(t["start_date"] for t in self.tasks if t["phase"] == "FRAME")
        at = dt.datetime.combine(dt.date.fromisoformat(frame_start) + dt.timedelta(days=20), dt.time(12))
        photos = [photo(5, at - dt.timedelta(hours=2), "pile_driver", "tower_crane", "concrete_mixer")]
        v = build_verdict(M, at, self.tasks, photos)
        kinds = {d["kind"] for d in v["deviations"]}
        self.assertIn("BEHIND_SCHEDULE", kinds)
        behind = next(d for d in v["deviations"] if d["kind"] == "BEHIND_SCHEDULE")
        self.assertEqual(behind["phase"], "PILING")
        # буровая уже объяснена отставанием — отдельного «нетипичная техника» по ней нет
        self.assertFalse(any(d["kind"] == "UNEXPECTED_EQUIPMENT" and "pile_driver" in d["equipment"]
                             for d in v["deviations"]))

    def test_all_good(self):
        photos = [photo(1, self.at - dt.timedelta(hours=1), "excavator", "dump_truck", "dump_truck")]
        v = build_verdict(M, self.at, self.tasks, photos)
        blocking = [d for d in v["deviations"]
                    if d["severity"] != "info" and d["phase"] == "EXCAVATION"]
        self.assertEqual(blocking, [])
        self.assertEqual(v["stage"]["top_phase"], "EXCAVATION")

    def test_idle_equipment(self):
        box = (0.4, 0.4, 0.6, 0.6)
        frames = [PhotoObs(i, self.at - dt.timedelta(minutes=30 * (3 - i)), 7, "Юг", "Въезд",
                           [det("dump_truck", box), det("excavator", (0.1 * i, 0.1, 0.1 * i + 0.1, 0.2))])
                  for i in range(4)]
        assign_activity(frames, M)
        v = build_verdict(M, self.at, self.tasks, frames)
        idle = [d for d in v["deviations"] if d["kind"] == "IDLE_EQUIPMENT"]
        self.assertEqual(len(idle), 1)
        self.assertEqual(idle[0]["equipment"], ["dump_truck"])
        self.assertEqual(idle[0]["severity"], "warning")
        self.assertTrue(recommendations(M, v, {"rows": []}))


class TimelineTest(unittest.TestCase):
    def test_delay_counted_only_since_first_photo(self):
        """Задержка не вменяется за период до первого снимка: иначе первая же загрузка даёт «61 день»."""
        import datetime as dt

        from app.core.timeline import build_timeline
        from app.core.types import Detection, PhotoObs

        def frame(i, when, cls):
            return PhotoObs(id=i, taken_at=when, camera_id=1, camera_name="c", zone="z",
                            detections=[Detection(id=i, cls=cls, confidence=0.9, bbox=(0.2, 0.2, 0.4, 0.4),
                                                  label_raw="")])

        # Котлован идёт с 10 января, но камеры поставили только 20 мая
        tasks = [{"code": "1", "name": "Котлован", "phase": "EXCAVATION",
                  "start_date": "2025-01-10", "end_date": "2025-08-10"}]
        at = dt.datetime(2025, 5, 25, 18)
        tl = build_timeline(M, at, tasks, [frame(1, dt.datetime(2025, 5, 20, 10), "tower_crane")],
                            "2025-01-10", "2025-12-31")
        row = tl["rows"][0]
        self.assertLessEqual(row["delay_days"], 5)            # не больше срока наблюдения, а не 130 дней
        self.assertLessEqual(tl["max_delay_days"], 5)

        # без наблюдений вообще этап тем более не «отстаёт»
        early = build_timeline(M, at, tasks, [], "2025-01-10", "2025-12-31")
        self.assertEqual(early["rows"][0]["status"], "unconfirmed")
        self.assertEqual(early["max_delay_days"], 0)

        # этап завершился до первого кадра: если на снимке техника более позднего этапа —
        # считаем выполненным; если техники нет вовсе — «не подтверждено». Отставания нет ни там, ни там.
        old_tasks = [{"code": "1", "name": "Снос", "phase": "DEMOLITION",
                      "start_date": "2025-01-10", "end_date": "2025-03-10"}]
        later = build_timeline(M, at, old_tasks, [frame(2, dt.datetime(2025, 5, 20, 10), "tower_crane")],
                               "2025-01-10", "2025-12-31")
        self.assertEqual(later["rows"][0]["status"], "done")
        self.assertEqual(later["max_delay_days"], 0)

        empty = PhotoObs(id=3, taken_at=dt.datetime(2025, 5, 20, 10), camera_id=1, camera_name="c", zone="z",
                         detections=[])
        gap = build_timeline(M, at, old_tasks, [empty], "2025-01-10", "2025-12-31")
        self.assertEqual(gap["rows"][0]["status"], "unconfirmed")
        self.assertEqual(gap["max_delay_days"], 0)

    def test_statuses_and_forecast(self):
        tasks = plan_dicts()
        piling = [t for t in tasks if t["phase"] == "PILING"]
        exc = [t for t in tasks if t["phase"] == "EXCAVATION"]
        p_s = dt.date.fromisoformat(min(t["start_date"] for t in piling))
        p_e = dt.date.fromisoformat(max(t["end_date"] for t in piling))
        e_s = dt.date.fromisoformat(min(t["start_date"] for t in exc))
        # Сваи шли весь срок и ещё 10 дней после; котлован начат вовремя
        photos, pid = [], 1
        d = p_s
        while d <= p_e + dt.timedelta(days=10):
            photos.append(photo(pid, dt.datetime.combine(d, dt.time(12)), "pile_driver"))
            pid += 1
            d += dt.timedelta(days=2)
        d = e_s
        while d <= p_e + dt.timedelta(days=10):
            photos.append(photo(pid, dt.datetime.combine(d, dt.time(13)), "excavator", "dump_truck"))
            pid += 1
            d += dt.timedelta(days=2)
        at = dt.datetime.combine(p_e + dt.timedelta(days=11), dt.time(18))
        tl = build_timeline(M, at, tasks, photos, "2025-01-01", "2026-12-31")
        rows = {r["phase"]: r for r in tl["rows"]}
        self.assertEqual(rows["PILING"]["status"], "delayed")
        self.assertGreaterEqual(rows["PILING"]["delay_days"], 10)
        self.assertEqual(rows["EXCAVATION"]["status"], "on_track")
        self.assertEqual(rows["LANDSCAPING"]["status"], "planned")
        self.assertIn(rows["ORGANIZATION"]["status"], ("done", "unobservable"))
        # снос камерами не видели, но последующие этапы идут — считаем выполненным
        self.assertEqual(rows["DEMOLITION"]["status"], "done")
        self.assertGreater(tl["completion_percent"], 0)
        self.assertEqual(tl["forecast_end"], (dt.date(2026, 12, 31) + dt.timedelta(days=tl["max_delay_days"])).isoformat())
        self.assertIn(tl["delay_risk"], ("medium", "high"))
        self.assertTrue(rows["PILING"]["evidence"])


if __name__ == "__main__":
    unittest.main()
