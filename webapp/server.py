"""Веб-сервер мини-приложения: API + отдача самой страницы.

Работает в том же процессе, что и бот, на локальном порту. Наружу его
выставляет Caddy — он же получает HTTPS-сертификат (см. setup-webapp.sh).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

import config
from webapp.api import add_routes, auth_middleware, error_middleware

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


# Файлы, к ссылкам на которые дописывается версия.
VERSIONED = ("styles.css", "app.js")


def asset_version() -> str:
    """Короткая метка версии статики — меняется, когда меняются файлы.

    Telegram кэширует app.js и styles.css очень цепко и без метки в адресе
    может неделями показывать старое приложение. Метка в ссылке — это новый
    адрес, мимо любого кэша.
    """
    stamp = 0.0
    for name in VERSIONED:
        path = STATIC_DIR / name
        if path.exists():
            stamp = max(stamp, path.stat().st_mtime)
    return f"{int(stamp)}"


async def index(request: web.Request) -> web.Response:
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    version = asset_version()
    for name in VERSIONED:
        page = page.replace(f"/static/{name}", f"/static/{name}?v={version}")

    return web.Response(
        text=page,
        content_type="text/html",
        charset="utf-8",
        # Саму страницу не кэшируем никогда: она и раздаёт новые версии
        # остальных файлов.
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def legal_page(request: web.Request) -> web.Response:
    """Оферта, политика и согласия — открытые страницы без авторизации.

    Ссылки на них лежат в кнопках бота, и человек должен открыть их до того,
    как согласится: требовать для этого вход было бы бессмысленно.
    """
    from services.legal import render

    page = render(request.match_info.get("slug", ""))
    if page is None:
        raise web.HTTPNotFound(text="Документ не найден")
    return web.Response(text=page, content_type="text/html", charset="utf-8")


def create_app() -> web.Application:
    # Порядок важен: ошибки ловим снаружи, авторизацию проверяем внутри.
    app = web.Application(middlewares=[error_middleware, auth_middleware])
    add_routes(app)
    app.router.add_get("/", index)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/legal/{slug}", legal_page)
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
