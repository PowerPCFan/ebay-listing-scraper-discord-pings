import asyncio
import contextlib
from pathlib import Path

from aiohttp import web

from modules import global_vars as gv
from modules.logger import logger

from . import authentication as auth
from . import websocket as ws

HOST = gv.config.config_editor_host or "127.0.0.1"
PORT = gv.config.config_editor_port or 8080
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
CONFIG_EDITOR_INDEX = STATIC_DIR / "config-editor" / "index.html"


async def root(request: web.Request) -> web.Response | web.FileResponse:
    if not auth.editor_authenticated(request):
        return auth.login_page()

    if not CONFIG_EDITOR_INDEX.exists():
        return web.Response(
            text="Config editor assets not found. Expected static/config-editor/index.html",
            status=500,
            content_type="text/plain",
        )
    return web.FileResponse(CONFIG_EDITOR_INDEX)


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "port": PORT})


async def start(host: str = HOST, port: int = PORT) -> None:
    logger.info("Starting config editor...")
    logger.debug("Setting up application, runner, and site...")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/login", auth.handle_login)
    app.router.add_get("/logout", auth.handle_logout)
    app.router.add_post("/extend_session", auth.handle_extend_session)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ws", ws.handler)
    app.router.add_static("/static", str(STATIC_DIR))

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host=host, port=port)

    try:
        logger.debug("Starting web server...")
        await site.start()
        logger.info(f"Config editor running at http://{host}:{port}")

        stop_event = asyncio.Event()
        await stop_event.wait()
    except Exception:
        logger.exception(f"Failed to start config editor server on {host}:{port}")
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
