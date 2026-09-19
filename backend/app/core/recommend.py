"""Рекомендации по результатам анализа (правила «отклонение → действие»)."""
from __future__ import annotations

from .methodology import Methodology

CAMERA_GUIDELINES = [
    "Ставьте обзорную камеру на высоте 15–30 м (башенный кран, соседнее здание, мачта) так, "
    "чтобы в кадр попадало всё пятно застройки и котлован целиком.",
    "Используйте минимум две обзорные камеры с противоположных углов площадки: техника "
    "перекрывает друг друга, а часть площадки из одной точки всегда не видна.",
    "Отдельная камера на въезде/выезде фиксирует самосвалы и бетоносмесители — это главный "
    "косвенный показатель темпа земляных и бетонных работ.",
    "Держите в кадре горизонт и избегайте съёмки против солнца; для зимы и ночи нужна "
    "ИК-подсветка или камеры с WDR.",
    "Не меняйте положение и зум камер: определение простоя техники сравнивает соседние кадры.",
    "Снимок раз в 30 минут достаточен для контроля этапов; для контроля простоя желательно "
    "каждые 10–15 минут.",
    "Размечайте зоны площадки (котлован, склад, подъезд) и привязывайте к ним камеры — "
    "предупреждения будут указывать, где именно отклонение.",
]


def recommendations(m: Methodology, verdict: dict, timeline: dict) -> list[dict]:
    recs: list[dict] = []

    def add(priority: str, text: str, reason: str):
        if not any(r["text"] == text for r in recs):
            recs.append({"priority": priority, "text": text, "reason": reason})

    for d in verdict.get("deviations", []):
        kind, eq = d["kind"], [m.label(c) for c in d.get("equipment", [])]
        phase = d.get("phase_name") or ""
        if kind == "MISSING_EQUIPMENT":
            add("high" if d["severity"] != "info" else "medium",
                f"Обеспечить на площадке: {', '.join(dict.fromkeys(eq))} для этапа «{phase}».", d["message"])
        elif kind == "NO_ACTIVITY":
            add("high", f"Выяснить у подрядчика причину остановки работ на этапе «{phase}» и получить "
                        "план восстановления темпа.", d["message"])
        elif kind == "BEHIND_SCHEDULE":
            add("high", f"Добавить ресурсы на этап «{phase}» или скорректировать график последующих этапов.",
                d["message"])
        elif kind == "NOT_IN_PLAN":
            add("medium", f"Проверить план объекта: этап «{phase}» фактически выполняется, но не запланирован.",
                d["message"])
        elif kind == "IDLE_EQUIPMENT":
            add("medium", f"Проверить загрузку техники ({', '.join(eq)}): вывести с площадки или "
                          "перераспределить на другие фронты работ.", d["message"])
        elif kind == "UNEXPECTED_EQUIPMENT" and d["severity"] == "warning":
            add("medium", f"Уточнить назначение техники ({', '.join(eq)}) — она не соответствует текущему этапу.",
                d["message"])
        elif kind in ("CAMERA_SILENT", "NO_DATA"):
            add("high", "Восстановить передачу снимков с камер: без данных объективный контроль невозможен.",
                d["message"])
        elif kind == "OUT_OF_VIEW":
            add("low", "Для работ внутри здания запросить у подрядчика фотоотчёт или установить "
                       "временные камеры на этажах.", d["message"])

    if timeline.get("delay_risk") == "high":
        add("high", f"Риск срыва срока ввода: прогнозная дата окончания {timeline.get('forecast_end')}. "
                    "Провести штаб по объекту.", f"Максимальная задержка {timeline.get('max_delay_days')} дн.")
    for row in timeline.get("rows", []):
        if row["status"] == "unconfirmed":
            add("low", f"Этап «{row['name']}» по графику завершён, но камерами не подтверждён — "
                       "проверить обзор камер или запросить исполнительную документацию.", row["status_label"])
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: order[r["priority"]])
