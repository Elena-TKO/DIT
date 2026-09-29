"""Пользователи, стройки, объекты и план работ (шаги 1–4 сценария)."""
from __future__ import annotations

import re
import time

from app.core.catalog import OBJECT_TYPES, catalog_tree
from app.core.planner import generate_plan, recompute_summaries, effective_enabled, schedule, PlanTask
from app.security import (hash_password, verify_password, create_token, decode_token,
                          create_scoped_token, decode_scoped_token)
from .common import (AppContext, ServiceError, now, iso, parse_date, require_project, require_building)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEAK_PASSWORDS = {"password", "qwerty123", "12345678", "qwertyui", "stroyka1", "admin123", "iloveyou",
                  "123456789", "qwerty", "password1", "stroykontrol"}


# ------------------------------------------------------------------ авторизация
def register(ctx: AppContext, email: str, password: str, name: str) -> dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ServiceError(422, "Укажите корректный e-mail")
    if len(password or "") < 8:
        raise ServiceError(422, "Пароль должен быть не короче 8 символов")
    if (password or "").lower() in WEAK_PASSWORDS or (password or "").isdigit():
        raise ServiceError(422, "Слишком простой пароль: добавьте буквы и не используйте очевидные сочетания")
    if ctx.db.one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ServiceError(409, "Пользователь с таким e-mail уже зарегистрирован")
    user_id = ctx.db.execute(
        "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (email, (name or "").strip() or email.split("@")[0], hash_password(password), iso(now())))
    return _session(ctx, user_id)


LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 10


def _check_login_rate(ctx: AppContext, key: str) -> None:
    now_ts = time.time()
    tries = [t for t in ctx.login_attempts.get(key, []) if now_ts - t < LOGIN_WINDOW_SECONDS]
    if tries:
        ctx.login_attempts[key] = tries
    else:
        ctx.login_attempts.pop(key, None)
    if len(ctx.login_attempts) > 1000:
        for k in [k for k, v in ctx.login_attempts.items() if not v]:
            ctx.login_attempts.pop(k, None)
    if len(tries) >= LOGIN_MAX_ATTEMPTS:
        wait = int((LOGIN_WINDOW_SECONDS - (now_ts - tries[0])) / 60) + 1
        raise ServiceError(429, f"Слишком много попыток входа. Повторите через {wait} мин")


def _register_failure(ctx: AppContext, key: str) -> None:
    ctx.login_attempts.setdefault(key, []).append(time.time())


def login(ctx: AppContext, email: str, password: str) -> dict:
    key = (email or "").strip().lower()
    _check_login_rate(ctx, key)
    user = ctx.db.one("SELECT * FROM users WHERE email = ?", (key,))
    if not user or not verify_password(password or "", user["password_hash"]):
        _register_failure(ctx, key)
        raise ServiceError(401, "Неверный e-mail или пароль")
    ctx.login_attempts.pop(key, None)
    return _session(ctx, user["id"])


def _session(ctx: AppContext, user_id: int) -> dict:
    return {"token": create_token(user_id, ctx.settings.secret_key, ctx.settings.token_ttl_hours),
            "user": get_user(ctx, user_id)}


def get_user(ctx: AppContext, user_id: int) -> dict:
    user = ctx.db.one("SELECT id, email, name, created_at FROM users WHERE id = ?", (user_id,))
    if not user:
        raise ServiceError(401, "Сессия недействительна")
    return user


def user_from_token(ctx: AppContext, token: str | None) -> int:
    user_id = decode_token(token or "", ctx.settings.secret_key)
    if not user_id or not ctx.db.one("SELECT id FROM users WHERE id = ?", (user_id,)):
        raise ServiceError(401, "Требуется вход в систему")
    return user_id


# ------------------------------------------------------------------ справочники
def object_types() -> list[dict]:
    return [{"key": k, "title": v} for k, v in OBJECT_TYPES.items()]


def methodology(ctx: AppContext) -> dict:
    m = ctx.m
    return {
        "equipment": [{"cls": k, "label": v["label"]} for k, v in m.equipment.items()],
        "phases": [p.to_dict() for p in m.ordered_phases()],
        "detection": m.detection, "activity": m.activity, "analysis": m.analysis,
    }


def catalog(ctx: AppContext, object_type: str | None) -> list[dict]:
    if object_type and object_type not in OBJECT_TYPES:
        raise ServiceError(422, "Неизвестный тип объекта")
    return catalog_tree(ctx.catalog, object_type)


# ------------------------------------------------------------------ стройки
def _check_period(start: str, end: str):
    s, e = parse_date(start), parse_date(end)
    if e <= s:
        raise ServiceError(422, "Дата окончания должна быть позже даты начала")
    return s.isoformat(), e.isoformat()


def create_project(ctx: AppContext, user_id: int, name: str, address: str, start_date: str, end_date: str) -> dict:
    if not (name or "").strip():
        raise ServiceError(422, "Укажите название стройки")
    s, e = _check_period(start_date, end_date)
    pid = ctx.db.execute(
        "INSERT INTO projects (owner_id, name, address, start_date, end_date, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, name.strip(), (address or "").strip(), s, e, iso(now())))
    return get_project(ctx, user_id, pid)


def list_projects(ctx: AppContext, user_id: int) -> list[dict]:
    return ctx.db.all(
        "SELECT p.*, (SELECT COUNT(*) FROM buildings b WHERE b.project_id = p.id) AS buildings_count, "
        "(SELECT COUNT(*) FROM cameras c WHERE c.project_id = p.id) AS cameras_count, "
        "(SELECT ph.id FROM photos ph JOIN buildings b ON b.id = ph.building_id WHERE b.project_id = p.id "
        "ORDER BY ph.taken_at DESC, ph.id DESC LIMIT 1) AS cover_photo_id "
        "FROM projects p WHERE p.owner_id = ? ORDER BY p.created_at DESC, p.id DESC", (user_id,))


def get_project(ctx: AppContext, user_id: int, project_id: int) -> dict:
    project = require_project(ctx, user_id, project_id)
    project["buildings"] = list_buildings(ctx, user_id, project_id)
    return project


def update_project(ctx: AppContext, user_id: int, project_id: int, **fields) -> dict:
    from .geo import check_point

    project = require_project(ctx, user_id, project_id)
    data = {k: v for k, v in fields.items() if v is not None and k in ("name", "address", "start_date", "end_date")}
    merged = {**project, **data}
    if not (merged["name"] or "").strip():
        raise ServiceError(422, "Укажите название стройки")
    merged["address"] = (merged["address"] or "").strip()
    merged["start_date"], merged["end_date"] = _check_period(merged["start_date"], merged["end_date"])
    lat, lon, source = project.get("lat"), project.get("lon"), project.get("geo_source")
    if fields.get("lat") is not None or fields.get("lon") is not None:
        lat, lon = check_point(fields.get("lat"), fields.get("lon"))
        source = "manual"
    elif merged["address"] != project["address"]:
        lat = lon = source = None          # адрес сменился — точку определим заново
    ctx.db.execute("UPDATE projects SET name=?, address=?, start_date=?, end_date=?, lat=?, lon=?, geo_source=? "
                   "WHERE id=?", (merged["name"].strip(), merged["address"], merged["start_date"], merged["end_date"],
                                  lat, lon, source, project_id))
    return get_project(ctx, user_id, project_id)


def delete_project(ctx: AppContext, user_id: int, project_id: int) -> None:
    from .photos import purge_building_files

    require_project(ctx, user_id, project_id)
    for b in ctx.db.all("SELECT id FROM buildings WHERE project_id = ?", (project_id,)):
        purge_building_files(ctx, b["id"])
    ctx.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ------------------------------------------------------------------ объекты
def create_building(ctx: AppContext, user_id: int, project_id: int, name: str, object_type: str,
                    start_date: str | None = None, end_date: str | None = None) -> dict:
    project = require_project(ctx, user_id, project_id)
    if object_type not in OBJECT_TYPES:
        raise ServiceError(422, "Выберите тип объекта из справочника")
    if not (name or "").strip():
        raise ServiceError(422, "Укажите название объекта")
    s, e = _check_period(start_date or project["start_date"], end_date or project["end_date"])
    tasks = generate_plan(ctx.catalog, object_type, s, e, ctx.m)
    with ctx.db.connect() as conn:
        bid = conn.execute(
            "INSERT INTO buildings (project_id, name, object_type, start_date, end_date, created_at) "
            "VALUES (?,?,?,?,?,?)", (project_id, name.strip(), object_type, s, e, iso(now()))).lastrowid
        _insert_tasks(conn, bid, tasks)
    return get_building(ctx, user_id, bid)


def _insert_tasks(conn, building_id: int, tasks: list[PlanTask]):
    conn.execute("DELETE FROM plan_tasks WHERE building_id = ?", (building_id,))
    conn.executemany(
        "INSERT INTO plan_tasks (building_id, code, parent_code, name, level, phase, is_summary, enabled, "
        "start_date, end_date, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(building_id, t.code, t.parent_code, t.name, t.level, t.phase, int(t.is_summary), int(t.enabled),
          t.start_date, t.end_date, t.sort_order) for t in tasks])


def list_buildings(ctx: AppContext, user_id: int, project_id: int) -> list[dict]:
    require_project(ctx, user_id, project_id)
    rows = ctx.db.all(
        "SELECT b.*, (SELECT COUNT(*) FROM photos ph WHERE ph.building_id = b.id) AS photos_count, "
        "(SELECT MAX(taken_at) FROM photos ph WHERE ph.building_id = b.id) AS last_photo_at, "
        "(SELECT status FROM verdicts v WHERE v.building_id = b.id ORDER BY v.id DESC LIMIT 1) AS last_status, "
        "(SELECT id FROM photos ph WHERE ph.building_id = b.id ORDER BY taken_at DESC, id DESC LIMIT 1) AS cover_photo_id "
        "FROM buildings b WHERE b.project_id = ? ORDER BY b.id", (project_id,))
    for r in rows:
        r["object_type_title"] = OBJECT_TYPES.get(r["object_type"], r["object_type"])
    return rows


def get_building(ctx: AppContext, user_id: int, building_id: int) -> dict:
    b = require_building(ctx, user_id, building_id)
    b["object_type_title"] = OBJECT_TYPES.get(b["object_type"], b["object_type"])
    b["project"] = ctx.db.one("SELECT id, name, address, start_date, end_date FROM projects WHERE id = ?",
                              (b["project_id"],))
    b["photos_count"] = ctx.db.one("SELECT COUNT(*) AS n FROM photos WHERE building_id = ?", (building_id,))["n"]
    b["cover_photo_id"] = cover_photo_id(ctx, building_id)
    return b


def cover_photo_id(ctx: AppContext, building_id: int) -> int | None:
    row = ctx.db.one("SELECT id FROM photos WHERE building_id = ? ORDER BY taken_at DESC, id DESC LIMIT 1",
                     (building_id,))
    return row["id"] if row else None


def update_building(ctx: AppContext, user_id: int, building_id: int, name: str | None = None,
                    start_date: str | None = None, end_date: str | None = None, reschedule: bool = False) -> dict:
    b = require_building(ctx, user_id, building_id)
    s, e = _check_period(start_date or b["start_date"], end_date or b["end_date"])
    ctx.db.execute("UPDATE buildings SET name=?, start_date=?, end_date=? WHERE id=?",
                   ((name or b["name"]).strip(), s, e, building_id))
    if reschedule:
        reschedule_plan(ctx, user_id, building_id)
    return get_building(ctx, user_id, building_id)


def delete_building(ctx: AppContext, user_id: int, building_id: int) -> None:
    from .photos import purge_building_files

    require_building(ctx, user_id, building_id)
    purge_building_files(ctx, building_id)
    ctx.db.execute("DELETE FROM buildings WHERE id = ?", (building_id,))


# ------------------------------------------------------------------ план
def get_plan(ctx: AppContext, user_id: int, building_id: int) -> dict:
    b = require_building(ctx, user_id, building_id)
    tasks = ctx.db.all("SELECT * FROM plan_tasks WHERE building_id = ? ORDER BY sort_order", (building_id,))
    eff = effective_enabled(tasks)
    for t in tasks:
        t["enabled"] = bool(t["enabled"])
        t["is_summary"] = bool(t["is_summary"])
        t["active"] = eff[t["code"]]
        t["phase_name"] = ctx.m.phase(t["phase"]).name if t["phase"] else None
    leaves = [t for t in tasks if t["active"] and not t["is_summary"] and t["start_date"]]
    phases = {}
    for t in leaves:
        p = phases.setdefault(t["phase"], {"phase": t["phase"], "name": t["phase_name"], "tasks": 0,
                                           "start": t["start_date"], "end": t["end_date"],
                                           "observability": ctx.m.phase(t["phase"]).observability})
        p["tasks"] += 1
        p["start"], p["end"] = min(p["start"], t["start_date"]), max(p["end"], t["end_date"])
    return {
        "building_id": building_id, "start_date": b["start_date"], "end_date": b["end_date"],
        "tasks": tasks,
        "phases": sorted(phases.values(), key=lambda x: ctx.m.phase(x["phase"]).sequence),
        "active_tasks": len(leaves),
    }


def update_task(ctx: AppContext, user_id: int, building_id: int, task_id: int, enabled: bool | None = None,
                start_date: str | None = None, end_date: str | None = None, phase: str | None = None) -> dict:
    require_building(ctx, user_id, building_id)
    task = ctx.db.one("SELECT * FROM plan_tasks WHERE id = ? AND building_id = ?", (task_id, building_id))
    if not task:
        raise ServiceError(404, "Работа не найдена в плане")
    if enabled is not None:
        task["enabled"] = int(bool(enabled))
    if phase is not None:
        if task["is_summary"] or phase not in ctx.m.phases:
            raise ServiceError(422, "Этап можно назначить только конкретной работе из методики")
        task["phase"] = phase
    if start_date or end_date:
        if task["is_summary"]:
            raise ServiceError(422, "Сроки сводной работы считаются по вложенным работам")
        s, e = _check_period(start_date or task["start_date"], end_date or task["end_date"])
        task["start_date"], task["end_date"] = s, e
    ctx.db.execute("UPDATE plan_tasks SET enabled=?, phase=?, start_date=?, end_date=? WHERE id=?",
                   (task["enabled"], task["phase"], task["start_date"], task["end_date"], task_id))
    _refresh_summaries(ctx, building_id)
    return plan_delta(ctx, user_id, building_id, {task["code"]})


def bulk_toggle(ctx: AppContext, user_id: int, building_id: int, task_ids: list[int], enabled: bool) -> dict:
    require_building(ctx, user_id, building_id)
    with ctx.db.connect() as conn:
        conn.executemany("UPDATE plan_tasks SET enabled = ? WHERE id = ? AND building_id = ?",
                         [(int(enabled), tid, building_id) for tid in task_ids])
    _refresh_summaries(ctx, building_id)
    return get_plan(ctx, user_id, building_id)


def plan_delta(ctx: AppContext, user_id: int, building_id: int, changed_codes: set[str]) -> dict:
    """Ответ на правку одной работы: только затронутые строки, а не весь план на 80 КБ.

    Затронуты сама работа, её потомки (включённость наследуется) и предки (сводные сроки).
    """
    plan = get_plan(ctx, user_id, building_id)
    affected = set(changed_codes)
    for code in list(changed_codes):
        parts = code.split(".")
        affected |= {".".join(parts[:i]) for i in range(1, len(parts))}
    tasks = [t for t in plan["tasks"]
             if t["code"] in affected or any(t["code"].startswith(c + ".") for c in changed_codes)]
    return {"building_id": building_id, "partial": True, "tasks": tasks,
            "phases": plan["phases"], "active_tasks": plan["active_tasks"]}


def _refresh_summaries(ctx: AppContext, building_id: int):
    tasks = ctx.db.all("SELECT * FROM plan_tasks WHERE building_id = ?", (building_id,))
    for t in tasks:
        t["enabled"], t["is_summary"] = bool(t["enabled"]), bool(t["is_summary"])
    recompute_summaries(tasks)
    with ctx.db.connect() as conn:
        conn.executemany("UPDATE plan_tasks SET start_date=?, end_date=? WHERE id=?",
                         [(t["start_date"], t["end_date"], t["id"]) for t in tasks if t["is_summary"]])


def reschedule_plan(ctx: AppContext, user_id: int, building_id: int) -> dict:
    """Пересчитать сроки по типовому графику, сохранив включённость работ."""
    b = require_building(ctx, user_id, building_id)
    rows = ctx.db.all("SELECT * FROM plan_tasks WHERE building_id = ? ORDER BY sort_order", (building_id,))
    tasks = [PlanTask(code=r["code"], parent_code=r["parent_code"], name=r["name"], level=r["level"],
                      phase=r["phase"], is_summary=bool(r["is_summary"]), enabled=bool(r["enabled"]),
                      start_date=None, end_date=None, sort_order=r["sort_order"]) for r in rows]
    schedule(tasks, parse_date(b["start_date"]), parse_date(b["end_date"]), ctx.m)
    with ctx.db.connect() as conn:
        conn.executemany("UPDATE plan_tasks SET start_date=?, end_date=? WHERE building_id=? AND code=?",
                         [(t.start_date, t.end_date, building_id, t.code) for t in tasks])
    return get_plan(ctx, user_id, building_id)


def regenerate_plan(ctx: AppContext, user_id: int, building_id: int) -> dict:
    """Сбросить план к исходному (по справочнику и типовому графику)."""
    b = require_building(ctx, user_id, building_id)
    tasks = generate_plan(ctx.catalog, b["object_type"], b["start_date"], b["end_date"], ctx.m)
    with ctx.db.connect() as conn:
        _insert_tasks(conn, building_id, tasks)
    return get_plan(ctx, user_id, building_id)


def active_leaf_tasks(ctx: AppContext, building_id: int) -> list[dict]:
    tasks = ctx.db.all("SELECT * FROM plan_tasks WHERE building_id = ? ORDER BY sort_order", (building_id,))
    eff = effective_enabled(tasks)
    return [t for t in tasks if eff[t["code"]] and not t["is_summary"] and t["phase"] and t["start_date"]]