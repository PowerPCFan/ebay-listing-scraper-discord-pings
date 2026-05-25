import asyncio
import contextlib
from pathlib import Path
from typing import TypedDict

from aiohttp import web

from modules import global_vars as gv
from modules.logger import logger

from . import authentication as auth
from . import websocket as ws

HOST = gv.config.config_editor_host or "127.0.0.1"
PORT = gv.config.config_editor_port or 8080
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
CONFIG_EDITOR_INDEX = STATIC_DIR / "config-editor" / "index.html"


class ConfigEditorRuntime(TypedDict):
    task: asyncio.Task[None] | None
    stop_event: asyncio.Event | None
    runner: web.AppRunner | None


runtime: ConfigEditorRuntime = {
    "task": None,
    "stop_event": None,
    "runner": None,
}


async def root(request: web.Request) -> web.Response | web.FileResponse:
    authenticated = auth.editor_authenticated(request)
    cookiect = len(list(request.cookies.keys()))
    logger.debug(f"Config editor root requested ({'un' if not authenticated else ''}authenticated; {cookiect} cookie{'' if cookiect == 1 else 's'})")  # noqa: E501

    if not authenticated:
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
    current_task = asyncio.current_task()
    if current_task is not None:
        runtime["task"] = current_task

    if runtime["stop_event"] is not None:
        logger.warning("Config editor web server is already running.")
        return

    stop_event = asyncio.Event()
    runtime["stop_event"] = stop_event

    logger.info("Starting config editor...")
    logger.debug("Setting up application, runner, and site...")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/login", auth.handle_login)
    app.router.add_get("/login/discord", auth.handle_discord_login)
    app.router.add_get("/oauth/discord/callback", auth.handle_discord_callback)
    app.router.add_get("/logout", auth.handle_logout)
    app.router.add_post("/extend_session", auth.handle_extend_session)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ws", ws.handler)
    app.router.add_static("/static", str(STATIC_DIR))

    runner = web.AppRunner(app)
    runtime["runner"] = runner
    await runner.setup()

    site = web.TCPSite(runner, host=host, port=port)

    try:
        logger.debug("Starting web server...")
        await site.start()
        logger.info(f"Config editor running at http://{host}:{port}")
        await stop_event.wait()
    except Exception:
        logger.exception(f"Failed to start config editor server on {host}:{port}")
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
        runtime["runner"] = None
        runtime["stop_event"] = None
        runtime["task"] = None


async def stop() -> None:
    stop_event = runtime["stop_event"]
    if not isinstance(stop_event, asyncio.Event):
        return

    await ws.session_signals.close_all_websockets(
        reason="shutdown",
        message="Config editor is stopping.",
    )
    stop_event.set()

    task = runtime["task"]
    if isinstance(task, asyncio.Task) and task is not asyncio.current_task():
        with contextlib.suppress(asyncio.CancelledError):
            await task
