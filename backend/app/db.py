"""Хранилище: SQLite (встроенный модуль, без внешних зависимостей).

Схема спроектирована так, чтобы переезд на PostgreSQL сводился к замене драйвера:
только стандартные типы и внешние ключи.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

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
    created_at TEXT NOT NULL
);

-- Объект (дом, школа, участок дороги) внутри стройки
CREATE TABLE IF NOT EXISTS buildings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    object_type TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

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

-- Камеры: upload — ручная загрузка; http/rtsp — опрос адреса; emulator — лента кадров из папки
CREATE TABLE IF NOT EXISTS cameras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    building_id     INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    zone            TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT 'upload',
    url             TEXT NOT NULL DEFAULT '',
    interval_min    INTEGER NOT NULL DEFAULT 30,
    tick_seconds    INTEGER NOT NULL DEFAULT 10,
    active          INTEGER NOT NULL DEFAULT 0,
    emulator_cursor INTEGER NOT NULL DEFAULT 0,
    emulator_clock  TEXT,
    last_polled_at  TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL
);

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
    process_ms    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_photos_building_time ON photos (building_id, taken_at);
CREATE INDEX IF NOT EXISTS ix_photos_camera_time ON photos (camera_id, taken_at);

CREATE TABLE IF NOT EXISTS detections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id     INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    cls          TEXT NOT NULL,
    label_raw    TEXT NOT NULL DEFAULT '',
    confidence   REAL NOT NULL,
    x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
    activity     TEXT NOT NULL DEFAULT 'unknown',
    idle_minutes INTEGER NOT NULL DEFAULT 0,
    manual       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_detections_photo ON detections (photo_id);

-- Снимки вердиктов и журнал отклонений (история для отчёта)
CREATE TABLE IF NOT EXISTS verdicts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
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
    zones       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_deviations_building ON deviations (building_id, at);
"""


SCHEMA_VERSION = 2          # поднимается вместе с каждой новой миграцией в _migrate


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

    def _migrate(self, conn):
        """Версионирование схемы: новые колонки добавляются здесь, а не молча ломают старые базы."""
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(verdicts)")}
        if "completion_percent" not in columns:      # v2: история готовности и потерь для тренда
            conn.execute("ALTER TABLE verdicts ADD COLUMN completion_percent REAL")
            conn.execute("ALTER TABLE verdicts ADD COLUMN planned_percent REAL")
            conn.execute("ALTER TABLE verdicts ADD COLUMN idle_cost INTEGER NOT NULL DEFAULT 0")
        if version != SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
