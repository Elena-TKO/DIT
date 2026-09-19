"""Точка входа FastAPI: ``uvicorn app.main:app``."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_core, routes_media
from app.config import Settings
from app.services import cameras
from app.services.common import AppContext, ServiceError

log = logging.getLogger("stroykontrol")

ROOT_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>СтройКонтроль API</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px;color:#22282D}}
a{{color:#22282D}}.btn{{display:inline-block;background:#F2B705;padding:10px 18px;text-decoration:none;font-weight:600;border-radius:3px}}</style>
</head><body><h1>СтройКонтроль — API</h1>
<p>Это адрес сервера API. Интерфейс приложения открывается отдельно:</p>
<p><a class="btn" href="{url}">Открыть интерфейс</a></p>
<p><a href="/docs">Документация API (Swagger)</a> · <a href="/api/health">Состояние сервиса и детектора</a></p>
</body></html>"""


async def camera_poller(ctx: AppContext):
    """Фоновый опрос камер и эмуляторов."""
    while True:
        await asyncio.sleep(ctx.settings.camera_poll_seconds)
        try:
            result = await asyncio.to_thread(cameras.poll_due, ctx)
            if result["polled"] or result["failed"]:
                log.info("Опрос камер: %s", result)
        except Exception:
            log.exception("Сбой фонового опроса камер")


def create_app(settings: Settings | None = None, detector=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = AppContext(settings, detector)
        app.state.ctx = ctx
        tasks = [asyncio.create_task(asyncio.to_thread(lambda: ctx.detector))]   # прогрев модели
        log.info("Интерфейс: %s · API: http://localhost:8000/docs", os.environ.get("FRONTEND_URL", "http://localhost:8080"))
        if settings.enable_poller:
            tasks.append(asyncio.create_task(camera_poller(ctx)))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="СтройКонтроль API", version="1.0",
                  description="Мониторинг строительной площадки по снимкам камер", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    app.include_router(routes_core.router)
    app.include_router(routes_media.router)

    # Собранный фронтенд можно отдавать самим бэкендом (одним контейнером)
    dist = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Не найдено"})
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        # Интерфейс отдаёт отдельный контейнер (nginx); на корне API — подсказка, куда идти
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:8080")

        @app.get("/", include_in_schema=False)
        def root():
            return HTMLResponse(ROOT_PAGE.format(url=frontend_url))

    return app


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
app = create_app()
