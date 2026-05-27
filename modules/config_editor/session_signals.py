import asyncio
import contextlib
import time
from typing import Any

from aiohttp import WSCloseCode, web
from aiohttp.client_exceptions import ClientConnectionResetError

from modules.logger import logger

from . import session_control

_active_webs: set[web.WebSocketResponse] = set()
_tracking_tasks: dict[int, asyncio.Task[None]] = {}
_invalidated_webs: set[web.WebSocketResponse] = set()


async def _safe_ws_send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> bool:
    if ws.closed:
        return False

    try:
        await ws.send_json(payload)
        return True
    except (ClientConnectionResetError, ConnectionResetError):
        return False
    except RuntimeError as exc:
        if "closing transport" in str(exc).lower() or "closed" in str(exc).lower():
            return False
        raise


async def _send_warning(ws: web.WebSocketResponse, expires_at: float) -> bool:
    warning_seconds = session_control.get_config_editor_warning_seconds()
    remaining_seconds = max(0, round(expires_at - time.time()))
    return await _safe_ws_send_json(ws, {
        "type": "session_warning",
        "message": "Your session will expire soon. Extend it now.",
        "expires_at": int(expires_at * 1000),
        "warning_seconds": warning_seconds,
        "remaining_seconds": remaining_seconds,
    })


async def _send_logout(ws: web.WebSocketResponse, reason: str, message: str) -> bool:
    return await _safe_ws_send_json(ws, {
        "type": "session_logout",
        "reason": reason,
        "message": message,
    })


async def _track_session(ws: web.WebSocketResponse) -> None:
    try:
        expires_at = session_control.get_session_expires_at()
        now = time.time()

        if expires_at <= now:
            await _send_logout(ws, "expired", "Session expired. Please log in again.")
            return

        warning_at = expires_at - session_control.get_config_editor_warning_seconds()
        if warning_at > now:
            await asyncio.sleep(warning_at - now)

            if ws.closed:
                return

        elif ws.closed:
            return

        if not await _send_warning(ws, expires_at):
            return

        sleep_for = max(0.0, expires_at - time.time())
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

        if ws.closed:
            return

        await _send_logout(ws, "expired", "Session expired. Please log in again.")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Session notification task failed:")


def register(ws: web.WebSocketResponse) -> None:
    _active_webs.add(ws)
    _tracking_tasks[id(ws)] = asyncio.create_task(_track_session(ws))


def unregister(ws: web.WebSocketResponse) -> None:
    _active_webs.discard(ws)
    task = _tracking_tasks.pop(id(ws), None)
    if task:
        task.cancel()
        with contextlib.suppress(Exception):
            pass
    _invalidated_webs.discard(ws)


async def broadcast(payload: dict[str, Any]) -> None:
    for ws in list(_active_webs):
        await _safe_ws_send_json(ws, payload)


async def notify_session_extended() -> None:
    expires_at = session_control.get_session_expires_at()
    await broadcast({
        "type": "session_extended",
        "message": "Session extended.",
        "expires_at": int(expires_at * 1000),
        "remaining_seconds": max(0, round(expires_at - time.time())),
        "warning_seconds": session_control.get_config_editor_warning_seconds(),
    })

    for ws in list(_active_webs):
        task = _tracking_tasks.pop(id(ws), None)
        if task:
            task.cancel()
        if not ws.closed:
            _tracking_tasks[id(ws)] = asyncio.create_task(_track_session(ws))


async def notify_session_reset() -> None:
    await notify_session_logout(
        "reset",
        "All sessions were reset. Please log in again.",
    )

    for ws in list(_active_webs):
        task = _tracking_tasks.pop(id(ws), None)
        if task:
            task.cancel()


async def notify_session_logout(reason: str, message: str) -> None:
    await broadcast({
        "type": "session_logout",
        "reason": reason,
        "message": message,
    })

    for ws in list(_active_webs):
        task = _tracking_tasks.pop(id(ws), None)
        if task:
            task.cancel()
        _invalidated_webs.add(ws)


def invalidate(ws: web.WebSocketResponse) -> None:
    _invalidated_webs.add(ws)


def is_invalidated(ws: web.WebSocketResponse) -> bool:
    return ws in _invalidated_webs


async def close_all_websockets(
    reason: str = "shutdown",
    message: str = "Server is shutting down.",
) -> None:
    for ws in list(_active_webs):
        _invalidated_webs.add(ws)

        task = _tracking_tasks.pop(id(ws), None)
        if task:
            task.cancel()

        if ws.closed:
            _active_webs.discard(ws)
            continue

        await _safe_ws_send_json(ws, {
            "type": "session_logout",
            "reason": reason,
            "message": message,
        })

        with contextlib.suppress(Exception):
            await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server_shutdown")

        _active_webs.discard(ws)

