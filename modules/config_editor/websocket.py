import json
import time
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.client_exceptions import ClientConnectionResetError

from modules import global_vars as gv
from modules.config_editor import persistence
from modules.config_tools import (
    Config,
    get_config_path,
    get_parsed_config,
    get_raw_config,
    reload_global_blocklist,
)
from modules.logger import logger

from . import authentication as auth
from . import backup, backup_io, metadata, session_control, session_signals


def _ws_state_payload() -> dict[str, Any]:
    config_path = str(get_config_path())
    raw = get_raw_config()
    parsed = get_parsed_config()
    editor_metadata = metadata.load(parsed)

    metadata.save(editor_metadata, parsed)

    gv.global_blocklist = reload_global_blocklist()
    blocklist_items = list(gv.global_blocklist.items)

    normalized_parsed = Config.from_dict(parsed).to_dict()
    expires_at = session_control.get_session_expires_at()

    return {
        "type": "state",
        "config_path": config_path,
        "raw": raw,
        "parsed": normalized_parsed,
        "editor_metadata": editor_metadata,
        "global_blocklist": blocklist_items,
        "backups": backup.list_backups(),
        "discord_metadata": metadata.get_discord_meta(),
        "session_state": {
            "expires_at": int(expires_at * 1000),
            "session_length_seconds": session_control.get_config_editor_session_length_seconds(),
            "warning_seconds": session_control.get_config_editor_warning_seconds(),
            "remaining_seconds": max(0, round(expires_at - time.time())),
        },
    }


async def _safe_ws_send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> bool:
    if ws.closed:
        return False

    try:
        await ws.send_json(payload)
        return True
    except (ClientConnectionResetError, ConnectionResetError):
        # Client disconnected while a message was being sent.
        return False
    except RuntimeError as exc:
        # aiohttp may raise RuntimeError when the transport is already closing.
        if "closing transport" in str(exc).lower() or "closed" in str(exc).lower():
            return False
        raise


async def handler(request: web.Request) -> web.WebSocketResponse:  # noqa: C901, PLR0912, PLR0915
    logger.debug("Incoming WebSocket connection")

    if not auth.editor_authenticated(request):
        raise web.HTTPUnauthorized(text="Config editor authentication required.")

    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    session_signals.register(ws)

    if not await _safe_ws_send_json(ws, _ws_state_payload()):
        session_signals.unregister(ws)
        return ws

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                if session_signals.is_invalidated(ws) or not session_control.is_session_active():
                    await _safe_ws_send_json(ws, {
                        "type": "session_logout",
                        "reason": "reset",
                        "message": "All sessions were reset. Please log in again.",
                    })
                    session_signals.invalidate(ws)
                    continue

                payload = json.loads(msg.data)
                action = payload.get("action")

                logger.debug(f"Received WebSocket message with action `{action}`")

                if action == "get_state":
                    if not await _safe_ws_send_json(ws, _ws_state_payload()):
                        break

                elif action == "validate_raw":
                    raw = payload.get("raw", "")
                    json.loads(raw)
                    if not await _safe_ws_send_json(
                        ws,
                        {"type": "validated", "message": "JSON is valid."},
                    ):
                        break

                elif action == "save_raw":
                    raw = payload.get("raw", "")
                    parsed = persistence.apply_candidate_raw(raw)
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "saved",
                            "message": "Saved raw JSON and reloaded runtime config.",
                            "raw": raw,
                            "parsed": parsed,
                        },
                    ):
                        break

                elif action == "save_parsed":
                    parsed_payload = payload.get("parsed")
                    if not isinstance(parsed_payload, dict):
                        msg_0 = "Expected parsed payload to be an object."
                        raise ValueError(msg_0)  # noqa: TRY301
                    editor_metadata_payload = payload.get("editor_metadata")
                    if editor_metadata_payload is not None and not isinstance(
                        editor_metadata_payload,
                        dict,
                    ):
                        msg_1 = "Expected editor_metadata to be an object when provided."
                        raise ValueError(msg_1)  # noqa: TRY301

                    raw = persistence.apply_candidate_parsed(parsed_payload)
                    parsed = get_parsed_config()
                    current_editor_metadata = metadata.load(parsed)
                    if isinstance(editor_metadata_payload, dict):
                        current_editor_metadata = editor_metadata_payload
                    saved_editor_metadata = metadata.save(current_editor_metadata, parsed)
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "saved",
                            "message": "Saved structured config and reloaded runtime config.",
                            "raw": raw,
                            "parsed": parsed,
                            "editor_metadata": saved_editor_metadata,
                        },
                    ):
                        break

                elif action == "export_json":
                    export_content = persistence.build_export_json()
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "export_json",
                            "filename": "config.json",
                            "content": export_content,
                        },
                    ):
                        break

                elif action == "save_global_blocklist":
                    items = payload.get("items", [])
                    if not isinstance(items, list):
                        msg_2 = "Expected items to be a list of strings."
                        raise ValueError(msg_2)  # noqa: TRY301

                    saved_items = persistence.save_global_blocklist([str(item) for item in items])
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "saved_blocklist",
                            "message": "Saved global blocklist and reloaded runtime blocklist.",
                            "items": saved_items,
                            "backups": backup.list_backups(),
                        },
                    ):
                        break

                elif action == "get_backups":
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "backups",
                            "items": backup.list_backups(),
                        },
                    ):
                        break

                elif action == "restore_backup":
                    filename = payload.get("filename")
                    if not isinstance(filename, str) or not filename.strip():
                        msg_3 = "Expected a backup filename."
                        raise ValueError(msg_3)  # noqa: TRY301

                    restored = backup.restore(filename)
                    state_payload = _ws_state_payload()
                    state_payload["type"] = "restored_backup"
                    state_payload["message"] = f"Restored backup: {restored['filename']}"
                    if not await _safe_ws_send_json(ws, state_payload):
                        break

                elif action == "delete_backup":
                    filename = payload.get("filename")
                    if not isinstance(filename, str) or not filename.strip():
                        msg_4 = "Expected a backup filename."
                        raise ValueError(msg_4)  # noqa: TRY301

                    deleted = backup.delete(filename)
                    if deleted and not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "backup_deleted",
                            "message": f"Deleted backup: {filename}",
                            "backups": backup.list_backups(),
                        },
                    ):
                        break
                    break

                elif action == "create_manual_backup":
                    reason = payload.get("reason", "manual")
                    try:
                        backup_path = backup_io.create_manual_backup(reason)
                        if not await _safe_ws_send_json(
                            ws,
                            {
                                "type": "backup_created",
                                "message": f"Created manual backup: {backup_path.name}",
                                "backups": backup.list_backups(),
                            },
                        ):
                            break
                    except Exception as e:
                        if not await _safe_ws_send_json(
                            ws,
                            {
                                "type": "error",
                                "message": f"Failed to create backup: {e}",
                            },
                        ):
                            break
                    break

                elif action == "extend_session":
                    # Session extension handled via cookie refresh
                    if not await _safe_ws_send_json(ws, {"type": "session_extended"}):
                        break

                else:
                    msg_5 = f"Unknown action: {action}"
                    raise ValueError(msg_5)  # noqa: TRY301

            except Exception as exc:
                if not await _safe_ws_send_json(
                    ws,
                    {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
                ):
                    break

        elif msg.type == WSMsgType.ERROR:
            logger.error(f"WebSocket connection closed with exception: {ws.exception()}")

    session_signals.unregister(ws)
    return ws
