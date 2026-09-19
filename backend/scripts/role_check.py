"""Прогон приложения по ролям (разведочное тестирование).

    SAMPLE_PHOTOS=/путь/к/снимкам python scripts/role_check.py

Оригинал: руководитель, инженер, жюри, интегратор, злоумышленник.

Не заменяет unit-тесты: это разведка. Скрипт печатает факты (тайминги, число запросов,
сообщения об ошибках), по которым дальше принимаются решения об улучшениях.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp())
ANN = TMP / 'ann'
ANN.mkdir()
os.environ['DATA_DIR'] = str(TMP / 'data')
os.environ['ALLOW_LOCAL_CAMERAS'] = '0'

from PIL import Image  # noqa: E402

from app.config import Settings  # noqa: E402
from app.ml.detectors import MockDetector  # noqa: E402
from app.services import analysis, cameras, photos, projects  # noqa: E402
from app.services.common import AppContext, ServiceError  # noqa: E402
from app.services.report_html import render_report  # noqa: E402

SAMPLES = sorted(Path(os.environ.get('SAMPLE_PHOTOS', '/mnt/project')).glob('*.png'))
findings: list[tuple[str, str, str]] = []


def note(role: str, severity: str, text: str):
    findings.append((role, severity, text))
    print(f'  [{severity}] {text}')


def annotate(stem: str, items):
    (ANN / f'{stem}.json').write_text(json.dumps(
        [{'cls': c, 'bbox': list(b), 'confidence': 0.9} for c, b in items]))


class CountingDB:
    """Обёртка для подсчёта SQL-запросов в сценарии."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.n = 0

    def __enter__(self):
        self.orig = self.ctx.db.all, self.ctx.db.one
        def all_(*a, **k):
            self.n += 1
            return self.orig[0](*a, **k)
        def one(*a, **k):
            self.n += 1
            return self.orig[1](*a, **k)
        self.ctx.db.all, self.ctx.db.one = all_, one
        return self

    def __exit__(self, *exc):
        self.ctx.db.all, self.ctx.db.one = self.orig


ctx = AppContext(Settings(), detector=MockDetector(str(ANN)))

# ----------------------------------------------------------------- 1. Руководитель
print('\n=== Роль: руководитель стройки (первый заход, хочет ответ за минуту) ===')
boss = projects.register(ctx, 'boss@stroy.ru', 'secret123', 'Руководитель')['user']['id']
p1 = projects.create_project(ctx, boss, 'ЖК «Северный парк»', 'Москва', '2025-01-15', '2027-03-31')['id']
t0 = time.perf_counter()
b1 = projects.create_building(ctx, boss, p1, 'Корпус 1', 'housing')['id']
note('руководитель', 'ЗАМЕР', f'создание объекта с планом: {time.perf_counter() - t0:.2f} с')

fresh = analysis.analyze(ctx, boss, b1)
note('руководитель', 'ФАКТ', f'объект без снимков: статус={fresh["verdict"]["status"]!r}, '
                             f'итог={fresh["verdict"]["summary"]!r}')
note('руководитель', 'ФАКТ', f'отклонений сразу после создания: '
                             f'{[d["kind"] for d in fresh["verdict"]["deviations"]]}')
ov = analysis.project_overview(ctx, boss, p1)['buildings'][0]
note('руководитель', 'ФАКТ', f'в сводке: готовность={ov["completion_percent"]}%, '
                             f'прогноз={ov["forecast_end"]}, риск={ov["delay_risk"]}')

# ----------------------------------------------------------------- 2. Инженер
print('\n=== Роль: инженер стройконтроля (ежедневная работа, 24 снимка) ===')
cam = cameras.create_camera(ctx, boss, p1, 'Мачта', zone='Котлован', building_id=b1)
plan = projects.get_plan(ctx, boss, b1)
exc = next(p for p in plan['phases'] if p['phase'] == 'EXCAVATION')
start = dt.datetime.fromisoformat(exc['start']) + dt.timedelta(days=3, hours=8)
batch = SAMPLES[:24]
for i, f in enumerate(batch):
    annotate(f.stem, [('excavator', (0.1 + 0.01 * i, 0.4, 0.3 + 0.01 * i, 0.7))])
t0 = time.perf_counter()
res = photos.upload_photos(ctx, boss, b1, [(f.name, f.read_bytes()) for f in batch],
                           camera_id=cam['id'], start_at=start.isoformat(), interval_min=30)
up = time.perf_counter() - t0
note('инженер', 'ЗАМЕР', f'загрузка 24 снимков (mock-детектор): {up:.2f} с, ошибок {len(res["errors"])}')

with CountingDB(ctx) as c:
    t0 = time.perf_counter()
    lst = photos.list_photos(ctx, boss, b1, limit=60)
    note('инженер', 'ЗАМЕР', f'галерея 24 снимков: {time.perf_counter() - t0:.2f} с, SQL-запросов {c.n}')
with CountingDB(ctx) as c:
    t0 = time.perf_counter()
    a = analysis.analyze(ctx, boss, b1)
    note('инженер', 'ЗАМЕР', f'анализ: {time.perf_counter() - t0:.2f} с, SQL-запросов {c.n}')
note('инженер', 'ФАКТ', f'вердикт: {a["verdict"]["summary"]!r}')

with CountingDB(ctx) as c:
    t0 = time.perf_counter()
    plan = projects.get_plan(ctx, boss, b1)
    note('инженер', 'ЗАМЕР', f'план ({len(plan["tasks"])} строк): {time.perf_counter() - t0:.2f} с, SQL {c.n}')
leaf = next(t for t in plan['tasks'] if not t['is_summary'])
t0 = time.perf_counter()
projects.update_task(ctx, boss, b1, leaf['id'], enabled=False)
note('инженер', 'ЗАМЕР', f'снять галочку с одной работы: {time.perf_counter() - t0:.2f} с '
                         f'(ответ отдаёт весь план целиком)')

# Все работы отключены
ids = [t['id'] for t in plan['tasks'] if not t['parent_code']]
projects.bulk_toggle(ctx, boss, b1, ids, False)
empty = analysis.analyze(ctx, boss, b1)
note('инженер', 'ФАКТ', f'план полностью отключён: статус={empty["verdict"]["status"]!r}, '
                        f'итог={empty["verdict"]["summary"]!r}')
tl_empty = analysis.timeline(ctx, boss, b1)
note('инженер', 'ФАКТ', f'таймлайн без работ: строк={len(tl_empty["rows"])}, '
                        f'готовность={tl_empty["completion_percent"]}, прогноз={tl_empty["forecast_end"]}')
projects.bulk_toggle(ctx, boss, b1, ids, True)

# Интервал 0 — все снимки одним временем
two = SAMPLES[24:26]
for f in two:
    annotate(f.stem, [('excavator', (0.2, 0.4, 0.4, 0.7))])
r0 = photos.upload_photos(ctx, boss, b1, [(f.name, f.read_bytes()) for f in two],
                          camera_id=cam['id'], start_at=start.isoformat(), interval_min=0)
det = photos.photo_detail(ctx, boss, r0['photo_ids'][-1])['detections']
note('инженер', 'ФАКТ', f'интервал 0 мин: активность={[d["activity"] for d in det]}, '
                        f'простой={[d["idle_minutes"] for d in det]}')

# ----------------------------------------------------------------- 3. Жюри
print('\n=== Роль: жюри хакатона (демо на 5 минут) ===')
emu = cameras.create_camera(ctx, boss, p1, 'Эмулятор', source_type='emulator', building_id=b1,
                            zone='Котлован', tick_seconds=1, emulator_start='2025-06-02T08:00')
frames = SAMPLES[26:29]
for f in frames:
    annotate(f.stem, [('pile_driver', (0.3, 0.1, 0.5, 0.9))])
cameras.upload_emulator_frames(ctx, boss, emu['id'], [(f.name, f.read_bytes()) for f in frames])
cameras.update_camera(ctx, boss, emu['id'], active=True)
t0 = time.perf_counter()
cameras.poll_due(ctx)
note('жюри', 'ЗАМЕР', f'один тик эмулятора: {time.perf_counter() - t0:.2f} с')
t0 = time.perf_counter()
html = render_report(ctx, boss, p1)
note('жюри', 'ЗАМЕР', f'HTML-отчёт: {time.perf_counter() - t0:.2f} с, размер {len(html) // 1024} КБ')
t0 = time.perf_counter()
ov_all = analysis.project_overview(ctx, boss, p1)
note('жюри', 'ЗАМЕР', f'сводка стройки (её фронт дёргает каждые 5 с при активной камере): '
                      f'{time.perf_counter() - t0:.2f} с')

# ----------------------------------------------------------------- 4. Интегратор
print('\n=== Роль: интегратор (развёртывание, перезапуск, ошибки) ===')
token = projects.login(ctx, 'boss@stroy.ru', 'secret123')['token']
ctx2 = AppContext(Settings(), detector=MockDetector(str(ANN)))
try:
    uid = projects.user_from_token(ctx2, token)
    note('интегратор', 'ФАКТ', f'токен пережил перезапуск процесса: пользователь {uid}')
except ServiceError as e:
    note('интегратор', 'ПРОБЛЕМА', f'после перезапуска токены недействительны: {e.detail}')

for bad, label in [('2025-13-01', 'месяц 13'), ('', 'пустая дата'), ('вчера', 'текст')]:
    try:
        projects.create_project(ctx, boss, 'X', '', bad, '2026-01-01')
        note('интегратор', 'ПРОБЛЕМА', f'принята некорректная дата: {label}')
    except ServiceError as e:
        note('интегратор', 'ФАКТ', f'дата {label}: {e.status} {e.detail!r}')

try:
    photos.upload_photos(ctx, boss, b1, [('big.jpg', b'x' * (30 * 1024 * 1024))], camera_id=cam['id'])
except ServiceError as e:
    note('интегратор', 'ФАКТ', f'файл 30 МБ: {e.status} {e.detail!r}')
huge = TMP / 'huge.png'
Image.new('RGB', (6000, 4000), (90, 80, 70)).save(huge)
t0 = time.perf_counter()
r = photos.upload_photos(ctx, boss, b1, [('huge.png', huge.read_bytes())], camera_id=cam['id'],
                         start_at=start.isoformat())
note('интегратор', 'ЗАМЕР', f'снимок 6000×4000: {time.perf_counter() - t0:.2f} с, принят={bool(r["uploaded"])}')

# Параллельная работа: опрос камеры и загрузка одновременно
errors: list[str] = []
def worker():
    try:
        cameras.poll_due(ctx)
    except Exception as exc:                                  # noqa: BLE001
        errors.append(repr(exc))
threads = [threading.Thread(target=worker) for _ in range(4)]
[t.start() for t in threads]
try:
    photos.upload_photos(ctx, boss, b1, [(SAMPLES[30].name, SAMPLES[30].read_bytes())],
                         camera_id=cam['id'], start_at=start.isoformat())
except ServiceError as exc:
    errors.append(exc.detail)
[t.join() for t in threads]
note('интегратор', 'ФАКТ' if not errors else 'ПРОБЛЕМА',
     f'параллельный опрос камер и загрузка: ошибок {len(errors)} {errors[:2]}')

# Осиротевшие файлы после удаления объекта
b_tmp = projects.create_building(ctx, boss, p1, 'Времянка', 'housing')['id']
photos.upload_photos(ctx, boss, b_tmp, [(SAMPLES[31].name, SAMPLES[31].read_bytes())], start_at=start.isoformat())
folder = Settings().photos_dir / str(b_tmp)
before = len(list(folder.glob('*')))
projects.delete_building(ctx, boss, b_tmp)
after = len(list(folder.glob('*'))) if folder.exists() else 0
note('интегратор', 'ФАКТ' if after == 0 else 'ПРОБЛЕМА',
     f'после удаления объекта файлов на диске: было {before}, осталось {after}')

# ----------------------------------------------------------------- 5. Злоумышленник
print('\n=== Роль: злоумышленник ===')
evil = projects.register(ctx, 'evil@x.ru', 'secret123', 'Чужой')['user']['id']
for call, what in [(lambda: projects.get_plan(ctx, evil, b1), 'план чужого объекта'),
                   (lambda: photos.list_photos(ctx, evil, b1), 'снимки чужого объекта'),
                   (lambda: cameras.poll_now(ctx, evil, cam['id']), 'опрос чужой камеры'),
                   (lambda: render_report(ctx, evil, p1), 'отчёт чужой стройки')]:
    try:
        call()
        note('злоумышленник', 'ПРОБЛЕМА', f'доступ получен: {what}')
    except ServiceError as e:
        note('злоумышленник', 'ФАКТ', f'{what}: {e.status}')

p_evil = projects.create_project(ctx, evil, 'Свой', '', '2025-01-01', '2026-01-01')['id']
b_evil = projects.create_building(ctx, evil, p_evil, 'Объект', 'housing')['id']
for url, what in [('http://169.254.169.254/latest/meta-data/', 'метаданные облака'),
                  ('http://127.0.0.1:8000/api/health', 'localhost сервиса'),
                  ('file:///etc/passwd', 'локальный файл')]:
    try:
        c = cameras.create_camera(ctx, evil, p_evil, 'SSRF', source_type='http', url=url, building_id=b_evil)
        try:
            cameras.poll_now(ctx, evil, c['id'])
            note('злоумышленник', 'ПРОБЛЕМА', f'камера обратилась к {what} и приняла ответ')
        except ServiceError as e:
            note('злоумышленник', 'ФАКТ' if 'http' not in url else 'ВНИМАНИЕ',
                 f'опрос {what}: {e.status} {e.detail[:60]!r}')
    except ServiceError as e:
        note('злоумышленник', 'ФАКТ', f'адрес {what} отклонён при создании: {e.detail!r}')

trav = photos.upload_photos(ctx, evil, b_evil, [('../../../../etc/cron.d/evil.png', SAMPLES[0].read_bytes())],
                            start_at='2025-02-01T10:00')
stored = ctx.db.one('SELECT file_name FROM photos WHERE id = ?', (trav['photo_ids'][0],))['file_name']
note('злоумышленник', 'ФАКТ' if '/' not in stored else 'ПРОБЛЕМА', f'имя файла с ../: сохранено как {stored!r}')

xss = projects.create_project(ctx, evil, '<script>alert(1)</script>', '"><img src=x onerror=alert(1)>',
                              '2025-01-01', '2026-01-01')
html_evil = render_report(ctx, evil, xss['id'])
note('злоумышленник', 'ФАКТ' if '<script>alert(1)</script>' not in html_evil else 'ПРОБЛЕМА',
     f'XSS в названии стройки: экранировано={"<script>alert(1)</script>" not in html_evil}')

forged = token[:-4] + ('0000' if not token.endswith('0000') else '1111')
try:
    projects.user_from_token(ctx, forged)
    note('злоумышленник', 'ПРОБЛЕМА', 'подделанный токен принят')
except ServiceError:
    note('злоумышленник', 'ФАКТ', 'подделанный токен отклонён')

try:
    projects.register(ctx, 'weak@x.ru', '123456', 'W')
    note('злоумышленник', 'ВНИМАНИЕ', 'пароль «123456» принят (проверяется только длина ≥ 6)')
except ServiceError as e:
    note('злоумышленник', 'ФАКТ', f'слабый пароль отклонён: {e.detail}')

print('\n=== ИТОГ ===')
for sev in ('ПРОБЛЕМА', 'ВНИМАНИЕ'):
    for role, s, text in findings:
        if s == sev:
            print(f'{sev} [{role}] {text}')
shutil.rmtree(TMP, ignore_errors=True)
