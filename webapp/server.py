"""Веб-сервер мини-приложения: API + отдача самой страницы.

Работает в том же процессе, что и бот, на локальном порту. Наружу его
выставляет Caddy — он же получает HTTPS-сертификат (см. setup-webapp.sh).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

import config
from webapp.api import add_routes, auth_middleware

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


async def index(request: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "index.html")


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    add_routes(app)
    app.router.add_get("/", index)
    app.router.add_get("/health", healthcheck)
    app.router.add_static("/static/", STATIC_DIR, name="static")
    return app


async def start_webapp() -> web.AppRunner | None:
    """Поднять сервер приложения рядом с ботом."""
    runner = web.AppRunner(create_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBAPP_HOST, config.WEBAPP_PORT)
    await site.start()
    logger.info(
        "Мини-приложение слушает %s:%s (публичный адрес: %s)",
        config.WEBAPP_HOST,
        config.WEBAPP_PORT,
        config.WEBAPP_URL or "не задан",
    )
    return runner
