"""Автоматическое определение этапа работ по обнаруженной технике.

Для каждого наблюдаемого этапа считается объяснимый балл (0..1):

    score = w_req · доля выполненных групп обязательной техники
          + w_exp · взвешенная доля увиденной техники, ожидаемой на этапе
          − w_unexp · взвешенная доля увиденной нетипичной техники
    score *= вес наблюдаемости этапа (high 1.0, medium 0.8, low 0.5)

Веса классов — IDF (буровая установка информативнее грузовика).
Этап считается подтверждённым, если все группы обязательной техники присутствуют
и балл ≥ ``stage_min_score``.

Одинаковый набор техники может соответствовать нескольким этапам (экскаватор + самосвал —
это и котлован, и наружные сети). Неоднозначность разрешается «объяснением»:
сначала берём этапы, активные по графику, затем добавляем внеплановые этапы только если
у них есть обязательная техника, которую выбранные этапы не объясняют.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .methodology import Methodology, OBSERVABILITY_WEIGHT, Phase
from .types import PhotoObs


@dataclass
class ClassObservation:
    cls: str
    label: str
    photos: int = 0          # на скольких снимках встречается
    max_count: int = 0       # максимум одновременно на одном снимке
    working: int = 0
    idle: int = 0
    photo_ids: list[int] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PhaseScore:
    phase: str
    name: str
    score: float
    required_coverage: float
    explained: float
    unexpected: float
    confirmed: bool
    present_required: list[str]
    missing_groups: list[list[str]]
    unexpected_seen: list[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def observe(photos: list[PhotoObs], m: Methodology) -> dict[str, ClassObservation]:
    """Сводка по технике за набор снимков."""
    min_conf = m.detection["min_confidence"]
    obs: dict[str, ClassObservation] = {}
    for p in photos:
        counts: dict[str, int] = defaultdict(int)
        for d in p.detections:
            if d.confidence < min_conf or d.cls not in m.equipment:
                continue
            counts[d.cls] += 1
            o = obs.setdefault(d.cls, ClassObservation(cls=d.cls, label=m.label(d.cls)))
            if d.activity == "working":
                o.working += 1
            elif d.activity == "idle":
                o.idle += 1
        for cls, n in counts.items():
            o = obs[cls]
            o.photos += 1
            o.max_count = max(o.max_count, n)
            o.photo_ids.append(p.id)
            if p.zone and p.zone not in o.zones:
                o.zones.append(p.zone)
    return obs


def score_phase(ph: Phase, present: set[str], m: Methodology) -> PhaseScore:
    w = m.detection["weights"]
    cw = m.class_weights
    total_w = sum(cw.get(c, 1.0) for c in present)

    satisfied = [g for g in ph.required if present & set(g)]
    missing = [list(g) for g in ph.required if not present & set(g)]
    req_cov = len(satisfied) / len(ph.required) if ph.required else 0.0
    explained = (sum(cw.get(c, 1.0) for c in present & ph.expected_classes) / total_w) if total_w else 0.0
    unexpected_seen = sorted(present & set(ph.unexpected))
    unexpected = (sum(cw.get(c, 1.0) for c in unexpected_seen) / total_w) if total_w else 0.0

    raw = w["required"] * req_cov + w["explained"] * explained - w["unexpected"] * unexpected
    score = max(0.0, raw) * OBSERVABILITY_WEIGHT[ph.observability] if present else 0.0
    present_required = sorted({c for g in ph.required for c in g} & present)
    confirmed = bool(ph.required) and not missing and score >= m.detection["stage_min_score"]
    return PhaseScore(
        phase=ph.id, name=ph.name, score=round(score, 3), required_coverage=round(req_cov, 3),
        explained=round(explained, 3), unexpected=round(unexpected, 3), confirmed=confirmed,
        present_required=present_required, missing_groups=missing, unexpected_seen=unexpected_seen,
    )


def rank_phases(present: set[str], m: Methodology) -> list[PhaseScore]:
    scores = [score_phase(ph, present, m) for ph in m.ordered_phases() if ph.observable]
    return sorted(scores, key=lambda s: (-s.score, m.phase(s.phase).sequence))


def resolve_phases(ranking: list[PhaseScore], present: set[str], planned: set[str],
                   m: Methodology) -> list[str]:
    """Этапы, которые реально объясняют увиденную технику (с учётом графика)."""
    candidates = [s for s in ranking if s.confirmed]
    if not candidates:
        return []
    planned_seq = [m.phase(p).sequence for p in planned] or [0]
    center = sum(planned_seq) / len(planned_seq)

    def order(s: PhaseScore):
        in_plan = s.phase in planned
        return (0 if in_plan else 1, -s.score, abs(m.phase(s.phase).sequence - center))

    chosen: list[str] = []
    # Плановые этапы, для которых видна хотя бы часть обязательной техники, уже «объясняют»
    # свою технику: экскаватор на котловане без самосвалов — это неполный котлован,
    # а не опережение по наружным сетям.
    explained: set[str] = set()
    for sc in ranking:
        if sc.phase in planned and sc.required_coverage > 0:
            explained |= m.phase(sc.phase).expected_classes & present
    for s in sorted(candidates, key=order):
        ph = m.phase(s.phase)
        distinct = set(s.present_required) - explained
        if s.phase in planned or (not chosen and not explained) or distinct:
            chosen.append(s.phase)
            explained |= ph.expected_classes
    return chosen


@dataclass
class StageResult:
    top_phase: str | None
    top_name: str | None
    closest_name: str | None
    confidence: float
    resolved: list[str]
    ambiguous_with: list[str]
    ranking: list[PhaseScore]
    explanation: str

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["ranking"] = [r.to_dict() for r in self.ranking]
        return d


def detect_stage(present: set[str], m: Methodology, planned: set[str] | None = None) -> StageResult:
    planned = planned or set()
    ranking = rank_phases(present, m)
    resolved = resolve_phases(ranking, present, planned, m)
    if not present:
        return StageResult(None, None, None, 0.0, [], [], ranking,
                           "Техника не обнаружена: работы не ведутся или этап визуально не наблюдаем.")
    if not resolved:
        partial = [s for s in ranking if s.phase in planned and s.required_coverage > 0]
        best = partial[0] if partial else (ranking[0] if ranking else None)
        text = "Набор техники не подтверждает ни один этап полностью"
        if best and best.score > 0:
            miss = "; ".join(" / ".join(m.label(c) for c in g) for g in best.missing_groups)
            text += f". Ближе всего «{best.name}», не хватает: {miss or '—'}"
        return StageResult(None, None, best.name if best and best.score > 0 else None,
                           best.score if best else 0.0, [], [], ranking, text + ".")

    top = next(s for s in ranking if s.phase == resolved[0])
    eps = m.detection["tie_epsilon"]
    ambiguous = [s.phase for s in ranking if s.confirmed and s.phase not in resolved
                 and s.score >= top.score - eps]
    labels = ", ".join(m.label(c) for c in sorted(present))
    text = (f"Обнаружено: {labels}. Это соответствует этапу «{top.name}» "
            f"(обязательная техника: {', '.join(m.label(c) for c in top.present_required)}).")
    if len(resolved) > 1:
        text += " Параллельно: " + ", ".join(f"«{m.phase(p).name}»" for p in resolved[1:]) + "."
    if ambiguous:
        text += (" Тот же набор техники характерен для: "
                 + ", ".join(f"«{m.phase(p).name}»" for p in ambiguous)
                 + (" — выбран этап по графику." if top.phase in planned else "."))
    return StageResult(top.phase, top.name, top.name, top.score, resolved, ambiguous, ranking, text)
