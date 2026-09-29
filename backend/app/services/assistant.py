"""Помощник по документации (бета).

Это макет RAG без языковой модели: база знаний — демонстрационные документы плюс то, что загрузил
пользователь; поиск — по пересечению основ слов с весами IDF; ответ собирается по шаблону под тип вопроса
и выдаётся потоком, как у чат-моделей. Интерфейс и протокол (NDJSON: meta → delta… → done) рассчитаны на то,
чтобы позже подменить ``compose_answer`` вызовом LLM, а ``search`` — векторным поиском, не трогая фронтенд.

Все ФИО, телефоны и записи журнала в демонстрационных документах вымышлены.
"""
from __future__ import annotations

import io
import json
import math
import re
import time
import zipfile
from dataclasses import dataclass

from .common import AppContext, ServiceError, iso, now

MAX_DOC_BYTES = 10 * 1024 * 1024
MAX_DOC_CHARS = 200_000
TEXT_EXT = (".txt", ".md", ".csv", ".json")
INDEXED_EXT = TEXT_EXT + (".docx", ".xlsx")

# ------------------------------------------------------------------ демо-данные
CONTACTS = [
    # (классы техники, ФИО, должность, телефон)
    (("excavator",), "Иванов Иван Иванович", "механик участка земляных работ", "+7 (999) 000-10-01"),
    (("bulldozer", "loader", "grader"), "Кузнецов Андрей Викторович", "мастер участка планировки", "+7 (999) 000-10-03"),
    (("dump_truck", "truck"), "Сидоров Пётр Алексеевич", "диспетчер автотранспорта", "+7 (999) 000-10-02"),
    (("mobile_crane", "tower_crane", "crane_manipulator"), "Морозов Сергей Николаевич",
     "ответственный за безопасное производство работ кранами", "+7 (999) 000-10-04"),
    (("concrete_mixer", "concrete_pump"), "Волкова Елена Сергеевна", "диспетчер бетонного узла", "+7 (999) 000-10-05"),
    (("pile_driver",), "Лебедев Олег Игоревич", "прораб свайных работ", "+7 (999) 000-10-06"),
    (("roller", "asphalt_paver"), "Новиков Дмитрий Павлович", "мастер дорожного участка", "+7 (999) 000-10-07"),
]
CHIEF = ("Смирнова Ольга Викторовна", "главный инженер проекта", "+7 (999) 000-10-00")
DISPATCH = ("Диспетчерская генподрядчика", "заявки на технику, круглосуточно", "+7 (999) 000-00-00")

# Основы слов в вопросе → класс техники
EQUIPMENT_WORDS = [
    ("экскав", "excavator"), ("эскав", "excavator"), ("экскоав", "excavator"), ("самосв", "dump_truck"), ("бульдоз", "bulldozer"), ("погрузч", "loader"),
    ("грейдер", "grader"), ("каток", "roller"), ("катк", "roller"), ("асфальт", "asphalt_paver"),
    ("башенн", "tower_crane"), ("автокран", "mobile_crane"), ("манипулят", "crane_manipulator"),
    ("кран", "mobile_crane"), ("бетононас", "concrete_pump"), ("миксер", "concrete_mixer"),
    ("бетон", "concrete_mixer"), ("свай", "pile_driver"), ("буров", "pile_driver"), ("грузов", "truck"),
]

JOURNAL = [
    "20.01.2026, Корпус 1, котлован. Простой двух самосвалов 3 ч 10 мин: экскаватор ЭО-5126 выведен на "
    "внеплановое ТО (течь гидравлики). Самосвалы стояли под погрузкой, вывоз грунта не выполнен.",
    "21.01.2026, Корпус 1. Бульдозер Б10М не вышел на смену: подрядчик не подтвердил заявку. Планировка дна "
    "котлована перенесена, заявка передана в диспетчерскую повторно.",
    "22.01.2026, Корпус 1. Работы по разработке грунта остановлены на 6 ч: после ночных −14 °C грунт промёрз на "
    "0,6–0,8 м, ковш экскаватора не берёт мёрзлый слой. Начато рыхление гидромолотом, участок укрыт матами.",
    "23.01.2026, Корпус 1. Разработка котлована возобновлена в 10:30 после рыхления. Выработка за смену — 58% нормы.",
    "Текущий этап по Корпусу 1: разработка грунта (котлован), захватка 2 из 4. Готовность этапа 46%, отставание "
    "от графика 9 дней, основная причина — простои из-за промерзания грунта и недокомплект техники.",
]

PPR = [
    "Разработка мёрзлого грунта. При промерзании глубже 0,4 м разработка экскаватором с обычным ковшом не "
    "допускается: грунт предварительно рыхлят гидромолотом или клин-молотом либо прогревают.",
    "Предохранение грунта от промерзания: участки, разработка которых запланирована на следующие сутки, укрывают "
    "утеплительными матами или рыхлят с вечера. Решение о прогреве принимает главный инженер проекта.",
    "При температуре ниже −20 °C работа экскаваторов с гидроприводом ограничивается: гидравлику прогревают перед "
    "сменой не менее 20 минут, иначе растёт риск отказов и внеплановых ТО.",
    "Порядок действий при простое техники: мастер фиксирует простой в журнале, указывает причину (нет фронта работ, "
    "неисправность, погодные условия, нет заявки) и сообщает диспетчеру для перераспределения техники.",
]


@dataclass
class Chunk:
    doc_id: str
    title: str
    text: str


def _builtin_docs(ctx: AppContext) -> list[dict]:
    m = ctx.m
    contacts = [f"Ответственный за технику «{', '.join(m.label(c) for c in classes)}» — {name}, {role}, тел. {phone}."
                for classes, name, role, phone in CONTACTS]
    contacts += [f"{CHIEF[1].capitalize()} — {CHIEF[0]}, тел. {CHIEF[2]}. Согласует прогрев грунта и перенос сроков.",
                 f"{DISPATCH[0]}: {DISPATCH[1]}, тел. {DISPATCH[2]}. Дополнительная техника — по заявке за сутки."]
    phases = []
    for p in m.ordered_phases():
        req = "; ".join(" или ".join(m.label(c) for c in g) for g in p.required) or "не требуется"
        typical = ", ".join(m.label(c) for c in p.typical) or "—"
        phases.append(f"Этап «{p.name}». Обязательная техника: {req}. Типичная техника: {typical}. {p.hint}".strip())
    rates = m.economics.get("shift_rates", {})
    economics = [f"Ставка аренды «{m.label(k)}» с оператором — {v:,} {m.economics.get('currency', '₽')} за смену "
                 f"{m.economics.get('shift_hours', 8)} ч.".replace(",", " ") for k, v in rates.items()]
    return [
        {"id": "kb-contacts", "name": "Контакты ответственных за технику (демо).xlsx", "chunks": contacts},
        {"id": "kb-journal", "name": "Журнал производства работ, Корпус 1 (демо).pdf", "chunks": JOURNAL},
        {"id": "kb-ppr", "name": "ППР: земляные работы в зимний период (демо).docx", "chunks": PPR},
        {"id": "kb-methodology", "name": "Методика СтройКонтроль: этапы и техника.json", "chunks": phases},
        {"id": "kb-rates", "name": "Ставки аренды техники (методика).json", "chunks": economics},
    ]


# ------------------------------------------------------------------ поиск
STOP = {"как", "что", "где", "кто", "это", "для", "при", "или", "его", "она", "они", "нет", "есть", "чем",
        "так", "уже", "был", "все", "всё", "тот", "эта", "эти", "кому", "почему", "какой", "какие", "мне"}


def _stems(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-z0-9]+", (text or "").lower().replace("ё", "е"))
    # грубая основа: первые 5 букв — «аренда»/«аренды», «экскаватор»/«экскаваторов» совпадают
    return {w[:5] for w in words if len(w) >= 3 and w not in STOP}


def _split(text: str, limit: int = 600) -> list[str]:
    parts, buf = [], ""
    for para in re.split(r"\n\s*\n|\r\n\r\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        while len(para) > limit:
            cut = para.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            parts.append(para[:cut])
            para = para[cut:].strip()
        if buf and len(buf) + len(para) + 1 > limit:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf} {para}".strip()
    if buf:
        parts.append(buf)
    return parts


def _chunks(ctx: AppContext, user_id: int) -> list[Chunk]:
    out = [Chunk(d["id"], d["name"], t) for d in _builtin_docs(ctx) for t in d["chunks"]]
    for d in ctx.db.all("SELECT id, name, content FROM assistant_documents WHERE owner_id = ?", (user_id,)):
        out += [Chunk(f"user-{d['id']}", d["name"], t) for t in _split(d["content"])]
    return out


def search(ctx: AppContext, user_id: int, question: str, k: int = 3, only: set[str] | None = None) -> list[dict]:
    chunks = [c for c in _chunks(ctx, user_id) if not only or c.doc_id in only]
    if not chunks:
        return []
    stems = [_stems(c.text + " " + c.title) for c in chunks]
    df: dict[str, int] = {}
    for s in stems:
        for w in s:
            df[w] = df.get(w, 0) + 1
    q = _stems(question)
    scored = []
    for c, s in zip(chunks, stems):
        score = sum(math.log(1 + len(chunks) / df[w]) for w in q & s)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [{"doc_id": c.doc_id, "title": c.title, "snippet": c.text, "score": round(sc, 2)} for sc, c in scored[:k]]


# ------------------------------------------------------------------ ответы
def _intent(q: str) -> str:
    q = q.lower()
    if re.search(r"сколько стоит|стоимост|цена|ставк|аренд|рубл", q):
        return "rates"
    if re.search(r"контакт|телефон|звонит|позвонит|ответственн|к кому|кто отвеча|не хватает|нехватк", q):
        return "contacts"
    if re.search(r"прост[оа]|простаив|(техник\w*|экскаватор\w*|самосвал\w*|кран\w*) сто[ия]т|"
                 r"сто[иял]\w* (техник|экскаватор|самосвал|кран)|почему .*не работ", q):
        return "idle"
    if re.search(r"этап|стади|что сейчас|ход работ|текущ|готовност", q):
        return "stage"
    return "search"


def _group(cls: str) -> tuple[str, ...]:
    return next((c[0] for c in CONTACTS if cls in c[0]), (cls,))


def _equipment_in(q: str) -> list[str]:
    q = q.lower().replace("ё", "е")
    found: list[str] = []
    for stem, cls in EQUIPMENT_WORDS:
        if stem not in q or cls in found:
            continue
        # «кран» внутри «башенный кран», «бетон» внутри «бетононасос» — не отдельная техника
        if stem in ("кран", "бетон") and any(f in _group(cls) for f in found):
            continue
        found.append(cls)
    return found


def _project_context(ctx: AppContext, user_id: int, project_id: int | None) -> dict | None:
    if not project_id:
        return None
    from .analysis import project_overview
    try:
        return project_overview(ctx, user_id, project_id)
    except ServiceError:
        return None


def _answer_stage(ctx, user_id, question, overview) -> tuple[str, list[dict]]:
    if overview and overview["buildings"]:
        lines = [f"**{overview['project']['name']}** — сводка по последним снимкам:", ""]
        for b in overview["buildings"]:
            if not b["photos"]:
                lines.append(f"- **{b['name']}**: снимков ещё нет, этап не подтверждён. Загрузите фото с камер.")
                continue
            stage = b["stage"] or (f"≈ {b['stage_closest']}" if b["stage_closest"] else "не подтверждён")
            done = "—" if b["completion_percent"] is None else f"{b['completion_percent']}%"
            lines.append(f"- **{b['name']}**: этап «{stage}», готовность {done} при плане {b['planned_percent']}%"
                         + (f", отклонений: {b['deviations']}" if b["deviations"] else ", отклонений нет")
                         + (f", прогноз окончания {b['forecast_end']}" if b["forecast_end"] else "") + ".")
        lines += ["", "Детали и снимки-доказательства — на вкладке «Фото и отклонения» каждого объекта."]
        return "\n".join(lines), search(ctx, user_id, "этап техника обязательная", 1, {"kb-methodology"})
    sources = search(ctx, user_id, "текущий этап корпус готовность отставание", 2, {"kb-journal", "kb-methodology"})
    text = ("**Корпус 1** сейчас на этапе **«Разработка грунта (котлован)»**, захватка 2 из 4.\n\n"
            "- Готовность этапа — **46%**, отставание от графика — **9 дней**.\n"
            "- На площадке по снимкам: экскаватор, самосвалы; бульдозер для планировки дна не зафиксирован.\n"
            "- Главные причины отставания — простои из-за промерзания грунта и недокомплект техники.\n\n"
            "Следующий по графику этап — «Свайные работы и ограждение котлована»: для него потребуется "
            "буровая/сваебойная установка.")
    return text, sources


def _answer_idle(ctx, user_id, question, overview) -> tuple[str, list[dict]]:
    sources = search(ctx, user_id, question + " простой промерз грунт техника не вышла ТО", 3,
                     {"kb-journal", "kb-ppr"})
    head = ""
    if overview:
        idle = [b for b in overview["buildings"] if b.get("idle_minutes")]
        if idle:
            head = "По снимкам камер: " + "; ".join(
                f"{b['name']} — простой {b['idle_minutes']} мин (≈ {b['idle_cost']:,} {b['currency']})".replace(",", " ")
                for b in idle) + ".\n\n"
    text = (head + "Простой возник по трём причинам (по журналу работ):\n\n"
            "1. **Техники нет.** Бульдозер не вышел на смену — подрядчик не подтвердил заявку; планировку дна "
            "котлована перенесли.\n"
            "2. **Техника стоит.** Экскаватор ушёл на внеплановое ТО (течь гидравлики) — два самосвала простояли "
            "под погрузкой 3 ч 10 мин.\n"
            "3. **Зима, грунт промёрз.** После ночных −14 °C промерзание 0,6–0,8 м: по ППР мёрзлый слой сначала "
            "рыхлят гидромолотом или прогревают, разработку остановили на 6 ч.\n\n"
            "Что сделать: укрывать завтрашние захватки матами с вечера, прогревать гидравлику перед сменой "
            "и подавать заявки на технику за сутки через диспетчерскую.")
    return text, sources


def _answer_contacts(ctx, user_id, question, overview) -> tuple[str, list[dict]]:
    m = ctx.m
    wanted = _equipment_in(question)
    if not wanted:
        # вопрос не про технику из справочника — возможно, ответ есть в загруженных документах
        found = search(ctx, user_id, question, 3)
        if found and found[0]["doc_id"].startswith("user-"):
            return _answer_search(ctx, user_id, question, overview)
    rows = [c for c in CONTACTS if any(cls in c[0] for cls in wanted)] if wanted else CONTACTS[:4]
    shortage = bool(re.search(r"не хватает|нехватк|нет |мало", question.lower()))
    lines = []
    if wanted and shortage:
        lines.append(f"Если не хватает техники ({', '.join(m.label(c).lower() for c in wanted)}), звоните:")
    elif wanted:
        lines.append("Ответственные по вашему запросу:")
    else:
        lines.append("Ответственные за основную технику на площадке:")
    lines.append("")
    for classes, name, role, phone in rows:
        label = ", ".join(m.label(c).lower() for c in classes)
        lines.append(f"- **{name}** — {role} ({label}), тел. **{phone}**")
    lines += ["", f"Дополнительную технику заказывает **{DISPATCH[0].lower()}**: тел. {DISPATCH[2]} "
                  f"({DISPATCH[1]}). Эскалация — {CHIEF[1]} {CHIEF[0]}, {CHIEF[2]}.",
              "", "_Демо-данные: ФИО и телефоны вымышлены._"]
    query = " ".join(m.label(c) for c in wanted) + " ответственный телефон" if wanted else "ответственный техника"
    return "\n".join(lines), search(ctx, user_id, query, 2, {"kb-contacts"})


def _answer_rates(ctx, user_id, question, overview) -> tuple[str, list[dict]]:
    own = {f"user-{r['id']}" for r in list_documents(ctx, user_id) if not r["builtin"]}
    return _answer_search(ctx, user_id, question, overview, {"kb-rates"} | own)


def _answer_search(ctx, user_id, question, overview, only: set[str] | None = None) -> tuple[str, list[dict]]:
    found = search(ctx, user_id, question, 3, only)
    if not found:
        return ("В базе знаний не нашлось ответа на этот вопрос. Попробуйте переформулировать — например, "
                "спросите про этап, простой или ответственных за технику. Можно добавить свой документ "
                "кнопкой «Документ» внизу."), []
    lines = ["Вот что нашлось в документации:", ""]
    for f in found:
        lines.append(f"- {f['snippet']} _({f['title']})_")
    return "\n".join(lines), found


HANDLERS = {"rates": _answer_rates, "stage": _answer_stage, "idle": _answer_idle, "contacts": _answer_contacts, "search": _answer_search}


def compose_answer(ctx: AppContext, user_id: int, question: str, project_id: int | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise ServiceError(422, "Введите вопрос")
    if len(question) > 2000:
        raise ServiceError(422, "Вопрос слишком длинный: до 2000 символов")
    intent = _intent(question)
    overview = _project_context(ctx, user_id, project_id)
    text, sources = HANDLERS[intent](ctx, user_id, question, overview)
    return {"intent": intent, "text": text,
            "sources": [{"doc_id": s["doc_id"], "title": s["title"], "snippet": s["snippet"]} for s in sources],
            "project": overview["project"]["name"] if overview else None}


def stream_answer(ctx: AppContext, user_id: int, question: str, project_id: int | None = None, delay: float = 0.0):
    """Генератор строк NDJSON: meta (источники) → delta (фрагменты текста) → done."""
    answer = compose_answer(ctx, user_id, question, project_id)

    def gen():
        yield json.dumps({"type": "meta", "intent": answer["intent"], "sources": answer["sources"],
                          "project": answer["project"]}, ensure_ascii=False) + "\n"
        pieces = re.findall(r"\S+\s*|\s+", answer["text"])
        for i in range(0, len(pieces), 2):
            yield json.dumps({"type": "delta", "text": "".join(pieces[i:i + 2])}, ensure_ascii=False) + "\n"
            if delay:
                time.sleep(delay)
        yield json.dumps({"type": "done"}) + "\n"

    return gen()


# ------------------------------------------------------------------ документы
def _extract(name: str, data: bytes) -> str:
    low = name.lower()
    if low.endswith(TEXT_EXT):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")
    if low.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if low.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(v) for v in row if v not in (None, "")]
                if cells:
                    rows.append(" · ".join(cells))
        return "\n\n".join(rows)
    return ""


def add_document(ctx: AppContext, user_id: int, name: str, data: bytes) -> dict:
    name = (name or "документ").strip()[:200]
    if not data:
        raise ServiceError(422, "Файл пустой")
    if len(data) > MAX_DOC_BYTES:
        raise ServiceError(413, "Файл больше 10 МБ")
    try:
        text = _extract(name, data)
    except Exception:
        raise ServiceError(422, "Не удалось прочитать файл")
    text = text[:MAX_DOC_CHARS]
    doc_id = ctx.db.execute("INSERT INTO assistant_documents (owner_id, name, size, content, created_at) "
                            "VALUES (?,?,?,?,?)", (user_id, name, len(data), text, iso(now())))
    return {**_doc_out(ctx.db.one("SELECT * FROM assistant_documents WHERE id = ?", (doc_id,))),
            "note": None if text.strip() else
            "Файл сохранён. В бета-версии текст извлекается только из .txt, .md, .csv, .docx и .xlsx."}


def _doc_out(d: dict) -> dict:
    return {"id": d["id"], "name": d["name"], "size": d["size"], "created_at": d["created_at"],
            "chunks": len(_split(d["content"])), "builtin": False}


def list_documents(ctx: AppContext, user_id: int) -> list[dict]:
    builtin = [{"id": d["id"], "name": d["name"], "size": None, "created_at": None, "chunks": len(d["chunks"]),
                "builtin": True} for d in _builtin_docs(ctx)]
    own = [_doc_out(d) for d in ctx.db.all("SELECT * FROM assistant_documents WHERE owner_id = ? ORDER BY id DESC",
                                           (user_id,))]
    return own + builtin


def delete_document(ctx: AppContext, user_id: int, doc_id: int) -> None:
    """Удаляет загруженный документ. Демонстрационные документы встроены в код и не удаляются."""
    if not ctx.db.one("SELECT id FROM assistant_documents WHERE id = ? AND owner_id = ?", (doc_id, user_id)):
        raise ServiceError(404, "Документ не найден")
    ctx.db.execute("DELETE FROM assistant_documents WHERE id = ?", (doc_id,))
