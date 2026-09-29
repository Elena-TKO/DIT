"""Хранилище: SQLite (встроенный модуль, без внешних зависимостей).

Схема спроектирована так, чтобы переезд на PostgreSQL сводился к замене драйвера:
только стандартные типы и внешние ключи.

Версии схемы (PRAGMA user_version):
  1 — базовая схема
  2 — verdicts: completion_percent, planned_percent, idle_cost
  3 — целостность данных: статус детекции, источник времени, хеш снимка, версии методики и модели,
      жизненный цикл отклонений
  4 — камера — просто метка для группировки снимков (без опроса адресов и эмулятора)
  5 — координаты стройки для карты (lat, lon, geo_source) и документы базы знаний помощника
  6 — этап у каждого снимка (phase, phase_source, auto_phase, phase_score) и справочные таблицы
      «тип объекта ↔ этап ↔ техника» (заполняются из методики и norms.json при старте, см. core/reference.py)
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 6

# Актуальная схема для новых баз. Индексы по колонкам, добавленным миграциями, здесь не создаются:
# у старых баз этих колонок на момент executescript ещё нет. Их создаёт _migrate.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lat        REAL,                                   -- v5: координаты для карты
    lon        REAL,
    geo_source TEXT                                    -- v5: yandex | nominatim | approx | manual
);
CREATE INDEX IF NOT EXISTS ix_projects_owner ON projects (owner_id);

-- Объект (дом, школа, участок дороги) внутри стройки
CREATE TABLE IF NOT EXISTS buildings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    object_type         TEXT NOT NULL,
    start_date          TEXT NOT NULL,
    end_date            TEXT NOT NULL,
    methodology_version TEXT NOT NULL DEFAULT '1.0',   -- v3: по какой методике сформирован план
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_buildings_project ON buildings (project_id);

-- План работ: строки справочника, отобранные для типа объекта; phase — этап методики
CREATE TABLE IF NOT EXISTS plan_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    code        TEXT NOT NULL,
    parent_code TEXT,
    name        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    phase       TEXT,
    is_summary  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    start_date  TEXT,
    end_date    TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (building_id, code)
);

-- Камера — метка для группировки снимков по зонам площадки (без опроса адресов и эмулятора).
-- Снимки по-прежнему загружаются только вручную; camera_id у фото — опциональный тег.
CREATE TABLE IF NOT EXISTS cameras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    zone        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cameras_project ON cameras (project_id);

CREATE TABLE IF NOT EXISTS photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id   INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    camera_id     INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    original_name TEXT NOT NULL DEFAULT '',
    file_name     TEXT NOT NULL,
    width         INTEGER,
    height        INTEGER,
    taken_at      TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL,
    detector      TEXT NOT NULL DEFAULT '',
    process_ms    INTEGER NOT NULL DEFAULT 0,
    -- v3
    time_source   TEXT NOT NULL DEFAULT 'synthetic',   -- exif | camera | synthetic
    detect_status TEXT NOT NULL DEFAULT 'done',        -- pending | done | failed | skipped
    model_version TEXT NOT NULL DEFAULT '',            -- хеш весов + конфиг детектора
    content_hash  TEXT,                                -- sha256 содержимого, для дедупликации
    -- v6: этап работ, к которому относится снимок
    phase         TEXT,                                -- действующий этап (авто или выбран пользователем)
    phase_source  TEXT,                                -- auto | manual; NULL — ещё не определялся
    auto_phase    TEXT,                                -- этап по технике на кадре (для сверки с ручным)
    phase_score   REAL,                                -- балл автоопределения 0..1
    phase_confirmed INTEGER NOT NULL DEFAULT 0         -- 1 — вся обязательная техника этапа на кадре
);
CREATE INDEX IF NOT EXISTS ix_photos_building_time ON photos (building_id, taken_at);
CREATE INDEX IF NOT EXISTS ix_photos_camera_time ON photos (camera_id, taken_at);

CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id      INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    cls           TEXT NOT NULL,
    label_raw     TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL,
    x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
    activity      TEXT NOT NULL DEFAULT 'unknown',
    idle_minutes  INTEGER NOT NULL DEFAULT 0,
    manual        INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'model',       -- v3: model | manual (готовая разметка для дообучения)
    model_version TEXT NOT NULL DEFAULT ''             -- v3
);
CREATE INDEX IF NOT EXISTS ix_detections_photo ON detections (photo_id);

-- Снимки вердиктов и журнал отклонений (история для отчёта)
CREATE TABLE IF NOT EXISTS verdicts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id         INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    at                  TEXT NOT NULL,
    status              TEXT NOT NULL,
    payload             TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    completion_percent  REAL,
    planned_percent     REAL,
    idle_cost           INTEGER NOT NULL DEFAULT 0,
    methodology_version TEXT NOT NULL DEFAULT '1.0'    -- v3
);

CREATE TABLE IF NOT EXISTS deviations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    verdict_id  INTEGER NOT NULL REFERENCES verdicts(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    phase       TEXT,
    message     TEXT NOT NULL,
    equipment   TEXT NOT NULL DEFAULT '[]',
    photo_ids   TEXT NOT NULL DEFAULT '[]',
    zones       TEXT NOT NULL DEFAULT '[]',
    first_seen  TEXT,                                  -- v3: когда отклонение впервые зафиксировано
    last_seen   TEXT,                                  -- v3: когда подтверждено в последний раз
    resolved_at TEXT                                   -- v3: когда исчезло (NULL — ещё актуально)
);
CREATE INDEX IF NOT EXISTS ix_deviations_building ON deviations (building_id, at);

-- v5: документы, добавленные пользователем в базу знаний помощника (бета, поиск по ключевым словам)
CREATE TABLE IF NOT EXISTS assistant_documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    size       INTEGER NOT NULL DEFAULT 0,
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assistant_docs_owner ON assistant_documents (owner_id);

-- v6: справочник «тип объекта ↔ этап ↔ техника». Источник истины — methodology.json и norms.json,
-- таблицы пересобираются при старте, чтобы связь была доступна SQL-запросами и внешним системам.
CREATE TABLE IF NOT EXISTS object_types (
    key   TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_phases (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    sequence      INTEGER NOT NULL,
    observability TEXT NOT NULL,                       -- high | medium | low | none — видно ли камерами
    hint          TEXT NOT NULL DEFAULT '',
    rule          TEXT NOT NULL DEFAULT '',            -- правило подбора техники (norms.json)
    docs          TEXT NOT NULL DEFAULT '[]'           -- нормативные документы, JSON-массив
);
CREATE TABLE IF NOT EXISTS equipment_types (
    cls        TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    shift_rate INTEGER                                  -- ставка аренды с оператором за смену, ₽
);
CREATE TABLE IF NOT EXISTS object_type_phases (
    object_type TEXT NOT NULL REFERENCES object_types(key) ON DELETE CASCADE,
    phase_id    TEXT NOT NULL REFERENCES work_phases(id) ON DELETE CASCADE,
    tasks       INTEGER NOT NULL DEFAULT 0,            -- сколько работ справочника относится к этапу
    PRIMARY KEY (object_type, phase_id)
);
CREATE TABLE IF NOT EXISTS phase_equipment (
    object_type TEXT NOT NULL REFERENCES object_types(key) ON DELETE CASCADE,
    phase_id    TEXT NOT NULL REFERENCES work_phases(id) ON DELETE CASCADE,
    cls         TEXT NOT NULL REFERENCES equipment_types(cls) ON DELETE CASCADE,
    role        TEXT NOT NULL,                         -- required | typical | unexpected
    alt_group   INTEGER,                               -- номер группы «или» для обязательной техники
    min_count   INTEGER NOT NULL DEFAULT 0,
    max_count   INTEGER,
    PRIMARY KEY (object_type, phase_id, cls)
);
CREATE INDEX IF NOT EXISTS ix_phase_equipment_phase ON phase_equipment (phase_id, cls);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30, detect_types=0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")     # в WAL безопасно и заметно быстрее записи
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Небольшие помощники, чтобы сервисный код оставался коротким
    def one(self, sql: str, params=()) -> dict | None:
        with self.connect() as c:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params=()) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def execute(self, sql: str, params=()) -> int:
        with self.connect() as c:
            return c.execute(sql, params).lastrowid

    def _migrate_cameras_v4(self, conn: sqlite3.Connection) -> None:
        """Пересобирает ``cameras`` в лёгкую метку (без опроса/эмулятора), если найдена старая схема.

        Выполняется до общей транзакции миграций и отдельно от неё: у ``photos.camera_id`` есть
        внешний ключ на эту таблицу, а пересоздание таблицы-родителя требует выключенных проверок
        FK. SQLite тихо игнорирует ``PRAGMA foreign_keys`` внутри активной транзакции, поэтому
        переключать её нужно в autocommit-режиме — до и после отдельным шагом.
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= 4:
            return
        cols = _columns(conn, "cameras")
        if not (cols - {"id", "project_id", "building_id", "name", "zone", "created_at"}):
            return   # новая база или уже пересобранная схема — нечего делать
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE cameras_v4 (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
                    name        TEXT NOT NULL,
                    zone        TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO cameras_v4 (id, project_id, building_id, name, zone, created_at) "
                "SELECT id, project_id, building_id, name, COALESCE(zone, ''), created_at FROM cameras")
            conn.execute("DROP TABLE cameras")
            conn.execute("ALTER TABLE cameras_v4 RENAME TO cameras")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_cameras_project ON cameras (project_id)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Версионирование схемы. BEGIN IMMEDIATE сериализует процессы: второй увидит уже новую версию."""
        self._migrate_cameras_v4(conn)

        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]

        if version < 2:     # история готовности и потерь для тренда
            _add_column(conn, "verdicts", "completion_percent", "REAL")
            _add_column(conn, "verdicts", "planned_percent", "REAL")
            _add_column(conn, "verdicts", "idle_cost", "INTEGER NOT NULL DEFAULT 0")

        if version < 3:
            _add_column(conn, "buildings", "methodology_version", "TEXT NOT NULL DEFAULT '1.0'")
            _add_column(conn, "photos", "time_source", "TEXT NOT NULL DEFAULT 'synthetic'")
            _add_column(conn, "photos", "detect_status", "TEXT NOT NULL DEFAULT 'done'")
            _add_column(conn, "photos", "model_version", "TEXT NOT NULL DEFAULT ''")
            _add_column(conn, "photos", "content_hash", "TEXT")
            _add_column(conn, "detections", "source", "TEXT NOT NULL DEFAULT 'model'")
            _add_column(conn, "detections", "model_version", "TEXT NOT NULL DEFAULT ''")
            _add_column(conn, "verdicts", "methodology_version", "TEXT NOT NULL DEFAULT '1.0'")
            _add_column(conn, "deviations", "first_seen", "TEXT")
            _add_column(conn, "deviations", "last_seen", "TEXT")
            _add_column(conn, "deviations", "resolved_at", "TEXT")

            # Backfill: ручные правки помечаем источником, у отклонений первое/последнее появление = момент вердикта
            conn.execute("UPDATE detections SET source = 'manual' WHERE manual = 1 AND source = 'model'")
            conn.execute("UPDATE deviations SET first_seen = at WHERE first_seen IS NULL")
            conn.execute("UPDATE deviations SET last_seen = at WHERE last_seen IS NULL")

            # Дубли вердиктов (повторные POST /analysis в старой версии) — оставляем последний по id.
            # Отклонения удалённых вердиктов уходят каскадом.
            conn.execute("DELETE FROM verdicts WHERE id NOT IN "
                         "(SELECT MAX(id) FROM verdicts GROUP BY building_id, at)")

        if version < 5:
            _add_column(conn, "projects", "lat", "REAL")
            _add_column(conn, "projects", "lon", "REAL")
            _add_column(conn, "projects", "geo_source", "TEXT")

        if version < 6:
            _add_column(conn, "photos", "phase", "TEXT")
            _add_column(conn, "photos", "phase_source", "TEXT")
            _add_column(conn, "photos", "auto_phase", "TEXT")
            _add_column(conn, "photos", "phase_score", "REAL")
            _add_column(conn, "photos", "phase_confirmed", "INTEGER NOT NULL DEFAULT 0")

        # Индексы создаём после колонок; IF NOT EXISTS делает шаг идемпотентным.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_verdicts_at ON verdicts (building_id, at)")
        # Дедупликация снимков по хешу содержимого — двумя индексами, а не одним.
        # SQL считает NULL != NULL, поэтому один UNIQUE(building_id, camera_id, content_hash) не ловит
        # дубли при camera_id IS NULL (ручная загрузка) — именно этот случай самый частый.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_photos_hash_cam ON photos (building_id, camera_id, "
                     "content_hash) WHERE content_hash IS NOT NULL AND camera_id IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_photos_hash_nocam ON photos (building_id, content_hash) "
                     "WHERE content_hash IS NOT NULL AND camera_id IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_photos_status ON photos (building_id, detect_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_photos_phase ON photos (building_id, phase, taken_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_deviations_open ON deviations (building_id, kind) "
                     "WHERE resolved_at IS NULL")

        if version != SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")