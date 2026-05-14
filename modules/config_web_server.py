# ruff: noqa: E501, C901, ANN401, TRY003, EM101, EM102, TRY301, PLR0915, PLR0912

import asyncio
import contextlib
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import json5
from aiohttp import WSMsgType, web
from aiohttp.client_exceptions import ClientConnectionResetError

from . import global_vars as gv
from .bot import bot as discord_bot
from .config_tools import (
    get_config_path,
    get_parsed_config,
    get_raw_config,
    reload_config,
    reload_global_blocklist,
)
from .logger import logger

HOST = gv.config.config_editor_host or "127.0.0.1"
PORT = gv.config.config_editor_port or 8080
AUTH_COOKIE_NAME = "config_editor_auth"
BACKUP_DIR = Path(__file__).parent.parent / "config-backups"
STATIC_DIR = Path(__file__).parent.parent / "static"
CONFIG_EDITOR_INDEX = STATIC_DIR / "config-editor" / "index.html"
EDITOR_METADATA_PATH = Path(__file__).parent.parent / "config-editor-metadata.json"


def _reconcile_editor_metadata(metadata: Any, parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        metadata = {}

    pings = parsed.get("pings")
    if not isinstance(pings, list):
        pings = []

    existing_pings = metadata.get("pings")
    if not isinstance(existing_pings, list):
        existing_pings = []

    reconciled_pings: list[dict[str, Any]] = []
    for ping_idx, ping in enumerate(pings):
        ping_keywords = ping.get("keywords") if isinstance(ping, dict) else []
        if not isinstance(ping_keywords, list):
            ping_keywords = []

        existing_ping_meta = existing_pings[ping_idx] if ping_idx < len(existing_pings) and isinstance(existing_pings[ping_idx], dict) else {}
        existing_keywords_meta = existing_ping_meta.get("keywords")
        if not isinstance(existing_keywords_meta, list):
            existing_keywords_meta = []

        keywords_meta: list[dict[str, Any]] = []
        for kw_idx, _ in enumerate(ping_keywords):
            existing_kw_meta = existing_keywords_meta[kw_idx] if kw_idx < len(existing_keywords_meta) and isinstance(existing_keywords_meta[kw_idx], dict) else {}
            mode = existing_kw_meta.get("mode")
            if mode not in ("manual", "typed"):
                mode = "manual"
            component_type = existing_kw_meta.get("component_type")
            if component_type is not None and not isinstance(component_type, str):
                component_type = None
            component_data = existing_kw_meta.get("component_data")
            if not isinstance(component_data, dict):
                component_data = {}

            keywords_meta.append({
                "mode": mode,
                "component_type": component_type,
                "component_data": component_data,
            })

        reconciled_pings.append({"keywords": keywords_meta})

    return {
        "version": 1,
        "pings": reconciled_pings,
    }


def _load_editor_metadata(parsed: dict[str, Any]) -> dict[str, Any]:
    if EDITOR_METADATA_PATH.exists():
        try:
            loaded = json.loads(EDITOR_METADATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
    else:
        loaded = {}

    return _reconcile_editor_metadata(loaded, parsed)


def _save_editor_metadata(metadata: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    reconciled = _reconcile_editor_metadata(metadata, parsed)
    EDITOR_METADATA_PATH.write_text(json.dumps(reconciled, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return reconciled


def _timestamp_for_backup_name() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")


def _write_backup_snapshot(previous_raw: str, reason: str) -> Path:
    config_path = get_config_path()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp_for_backup_name()
    safe_reason = "".join(ch if ch.isalnum() else "-" for ch in reason).strip("-") or "save"
    backup_name = f"{config_path.stem}-{timestamp}-{safe_reason}{config_path.suffix}"
    backup_path = BACKUP_DIR / backup_name

    backup_path.write_text(previous_raw, encoding="utf-8")
    return backup_path


def _apply_candidate_raw(candidate_raw: str, reason: str = "save") -> dict[str, Any]:
    config_path = get_config_path()
    previous_raw = get_raw_config()

    json5.loads(candidate_raw)

    _write_backup_snapshot(previous_raw=previous_raw, reason=reason)
    config_path.write_text(candidate_raw, encoding="utf-8")

    try:
        gv.config = reload_config()
    except Exception:
        config_path.write_text(previous_raw, encoding="utf-8")
        gv.config = reload_config()
        raise

    return get_parsed_config()


def _apply_candidate_parsed(candidate_data: dict[str, Any]) -> str:
    if not isinstance(candidate_data, dict):
        raise TypeError("Parsed config payload must be an object.")

    serialized = json.dumps(candidate_data, indent=4, ensure_ascii=False)
    _apply_candidate_raw(serialized)
    return serialized


def _build_export_json() -> str:
    parsed = get_parsed_config()
    return json.dumps(parsed, indent=4, ensure_ascii=False)


def _write_global_blocklist_backup(previous_items: list[str]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp_for_backup_name()
    backup_path = BACKUP_DIR / f"global_blocklist-{timestamp}-save.txt"
    backup_path.write_text("\n".join(previous_items) + "\n", encoding="utf-8")
    return backup_path


def _save_global_blocklist(items: list[str]) -> list[str]:
    normalized: list[str] = []
    seen_lower: set[str] = set()

    for item in items:
        value = item.strip().lower()
        if not value or value in seen_lower:
            continue
        seen_lower.add(value)
        normalized.append(value)

    previous_items = list(gv.global_blocklist.items)
    _write_global_blocklist_backup(previous_items)

    gv.global_blocklist.items = normalized
    gv.global_blocklist.save()
    gv.global_blocklist = reload_global_blocklist()

    return list(gv.global_blocklist.items)


def _list_backups() -> list[dict[str, Any]]:
    if not BACKUP_DIR.exists():
        return []

    backups: list[dict[str, Any]] = []
    for file_path in BACKUP_DIR.iterdir():
        if not file_path.is_file():
            continue

        stat = file_path.stat()
        backups.append({
            "name": file_path.name,
            "kind": "global_blocklist" if file_path.name.startswith("global_blocklist-") else "config",
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat() + "Z",
        })

    backups.sort(key=lambda item: item["modified"], reverse=True)
    return backups


def _resolve_backup_path(filename: str) -> Path:
    if Path(filename).name != filename:
        raise ValueError("Invalid backup filename.")

    backup_path = (BACKUP_DIR / filename).resolve()
    if backup_path.parent != BACKUP_DIR.resolve():
        raise ValueError("Backup path is outside the backup directory.")
    if not backup_path.exists() or not backup_path.is_file():
        raise FileNotFoundError(f"Backup not found: {filename}")

    return backup_path


def _restore_backup(filename: str) -> dict[str, Any]:
    backup_path = _resolve_backup_path(filename)
    backup_text = backup_path.read_text(encoding="utf-8")

    if backup_path.name.startswith("global_blocklist-"):
        items = [line.strip() for line in backup_text.splitlines() if line.strip()]
        saved_items = _save_global_blocklist(items)
        return {
            "kind": "global_blocklist",
            "filename": backup_path.name,
            "items": saved_items,
        }

    parsed = _apply_candidate_raw(backup_text, reason="restore")
    return {
        "kind": "config",
        "filename": backup_path.name,
        "parsed": parsed,
        "raw": backup_text,
    }


def _delete_backup(filename: str) -> bool:
    """Delete a backup file. Returns True if successful."""
    backup_path = _resolve_backup_path(filename)
    try:
        backup_path.unlink()
        return True
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Backup not found: {filename}") from e
    except PermissionError as e:
        raise PermissionError(f"Permission denied to delete: {filename}") from e


def _create_manual_backup(reason: str = "manual") -> Path:
    """Create a manual backup snapshot of the current config."""
    # config_path = get_config_path()
    previous_raw = get_raw_config()

    return _write_backup_snapshot(previous_raw=previous_raw, reason=reason)


def _password_fingerprint(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _get_config_editor_password() -> str | None:
    parsed = get_parsed_config()

    candidate: str | None = None
    direct = parsed.get("config_editor_password")
    if isinstance(direct, str):
        candidate = direct

    editor_obj = parsed.get("config_editor")
    if isinstance(editor_obj, dict):
        nested = editor_obj.get("password")
        if isinstance(nested, str):
            candidate = nested

    if candidate is None:
        return None

    normalized = candidate.strip()
    return normalized or None


def _is_editor_authenticated(request: web.Request) -> bool:
    password = _get_config_editor_password()
    if not password:
        return True

    cookie_value = request.cookies.get(AUTH_COOKIE_NAME)
    if not cookie_value:
        return False

    expected = _password_fingerprint(password)
    return hmac.compare_digest(cookie_value, expected)


def _login_html(error_message: str = "") -> str:
    error_block = ""
    if error_message:
        error_block = f'<p style="color: red;">{error_message}</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Log in</title>
</head>
<body style="background: #1c1c1c; color: #ebebeb; font-family: system-ui;">
  <form method="post" action="/login">
    <h1>Config Editor</h1>
    {error_block}
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required />
    <button type="submit">Log in</button>
  </form>
</body>
</html>"""


async def handle_index(request: web.Request) -> web.Response | web.FileResponse:
    if not _is_editor_authenticated(request):
        return web.Response(text=_login_html(), content_type="text/html")

    if not CONFIG_EDITOR_INDEX.exists():
        return web.Response(
            text="Config editor assets not found. Expected static/config-editor/index.html",
            status=500,
            content_type="text/plain",
        )
    return web.FileResponse(CONFIG_EDITOR_INDEX)


async def handle_login(request: web.Request) -> web.Response:
    password = _get_config_editor_password()
    if not password:
        raise web.HTTPFound("/")

    data = await request.post()
    submitted = str(data.get("password", "")).strip()

    if hmac.compare_digest(submitted, password):
        response = web.HTTPFound("/")
        response.set_cookie(
            AUTH_COOKIE_NAME,
            _password_fingerprint(password),
            httponly=True,
            samesite="Strict",
            secure=request.scheme == "https",
            max_age=60 * 30,
            path="/",
        )
        return response

    return web.Response(text=_login_html("Invalid password."), content_type="text/html", status=401)


async def handle_logout(_request: web.Request) -> web.Response:
    response = web.HTTPFound("/")
    response.del_cookie(AUTH_COOKIE_NAME, path="/")
    return response


async def handle_extend_session(request: web.Request) -> web.Response:
    """Extend the session by 30 minutes."""
    password = _get_config_editor_password()
    if not password:
        return web.HTTPFound("/")

    # Check if currently authenticated
    if not _is_editor_authenticated(request):
        return web.Response(text="Not authenticated", status=401)

    response = web.Response(text="Session extended")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        _password_fingerprint(password),
        httponly=True,
        samesite="Strict",
        secure=request.scheme == "https",
        max_age=60 * 30,  # 30 minutes
        path="/",
    )
    return response


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "port": PORT})


def _get_discord_metadata() -> dict[str, Any]:
    metadata = {"ready": True, "guilds": []}
    try:
        if hasattr(discord_bot, "is_ready") and discord_bot.is_ready():
            guild = discord_bot.get_guild(gv.config.discord_guild_id)
            if guild:
                g_data = {
                    "id": str(guild.id),
                    "name": guild.name,
                    "channels": [],
                    "roles": [],
                }
                for channel in guild.text_channels:
                    g_data["channels"].append({"id": str(channel.id), "name": channel.name})
                for role in guild.roles:
                    if role.is_default():
                        continue
                    g_data["roles"].append({"id": str(role.id), "name": role.name})
                metadata["guilds"].append(g_data)
    except Exception as e:
        logger.error(f"Error fetching Discord metadata: {e}")
        metadata["ready"] = False

    return metadata


def _ws_state_payload() -> dict[str, Any]:
    config_path = str(get_config_path())
    raw = get_raw_config()
    parsed = get_parsed_config()
    editor_metadata = _load_editor_metadata(parsed)
    _save_editor_metadata(editor_metadata, parsed)
    gv.global_blocklist = reload_global_blocklist()
    blocklist_items = list(gv.global_blocklist.items)
    return {
        "type": "state",
        "config_path": config_path,
        "raw": raw,
        "parsed": parsed,
        "editor_metadata": editor_metadata,
        "global_blocklist": blocklist_items,
        "backups": _list_backups(),
        "discord_metadata": _get_discord_metadata(),
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


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    if not _is_editor_authenticated(request):
        raise web.HTTPUnauthorized(text="Config editor authentication required.")

    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    if not await _safe_ws_send_json(ws, _ws_state_payload()):
        return ws

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
                action = payload.get("action")

                if action == "get_state":
                    if not await _safe_ws_send_json(ws, _ws_state_payload()):
                        break

                elif action == "validate_raw":
                    raw = payload.get("raw", "")
                    json5.loads(raw)
                    if not await _safe_ws_send_json(ws, {"type": "validated", "message": "JSONC is valid."}):
                        break

                elif action == "save_raw":
                    raw = payload.get("raw", "")
                    parsed = _apply_candidate_raw(raw)
                    if not await _safe_ws_send_json(ws, {
                        "type": "saved",
                        "message": "Saved raw JSONC and reloaded runtime config.",
                        "raw": raw,
                        "parsed": parsed,
                    }):
                        break

                elif action == "save_parsed":
                    parsed_payload = payload.get("parsed")
                    if not isinstance(parsed_payload, dict):
                        raise ValueError("Expected parsed payload to be an object.")
                    editor_metadata_payload = payload.get("editor_metadata")
                    if editor_metadata_payload is not None and not isinstance(editor_metadata_payload, dict):
                        raise ValueError("Expected editor_metadata to be an object when provided.")

                    raw = _apply_candidate_parsed(parsed_payload)
                    parsed = get_parsed_config()
                    current_editor_metadata = _load_editor_metadata(parsed)
                    if isinstance(editor_metadata_payload, dict):
                        current_editor_metadata = editor_metadata_payload
                    saved_editor_metadata = _save_editor_metadata(current_editor_metadata, parsed)
                    if not await _safe_ws_send_json(ws, {
                        "type": "saved",
                        "message": "Saved structured config and reloaded runtime config.",
                        "raw": raw,
                        "parsed": parsed,
                        "editor_metadata": saved_editor_metadata,
                    }):
                        break

                elif action == "export_json":
                    export_content = _build_export_json()
                    if not await _safe_ws_send_json(ws, {
                        "type": "export_json",
                        "filename": "config.json",
                        "content": export_content,
                    }):
                        break

                elif action == "save_global_blocklist":
                    items = payload.get("items", [])
                    if not isinstance(items, list):
                        raise ValueError("Expected items to be a list of strings.")

                    saved_items = _save_global_blocklist([str(item) for item in items])
                    if not await _safe_ws_send_json(ws, {
                        "type": "saved_blocklist",
                        "message": "Saved global blocklist and reloaded runtime blocklist.",
                        "items": saved_items,
                        "backups": _list_backups(),
                    }):
                        break

                elif action == "get_backups":
                    if not await _safe_ws_send_json(ws, {
                        "type": "backups",
                        "items": _list_backups(),
                    }):
                        break

                elif action == "restore_backup":
                    filename = payload.get("filename")
                    if not isinstance(filename, str) or not filename.strip():
                        raise ValueError("Expected a backup filename.")

                    restored = _restore_backup(filename)
                    state_payload = _ws_state_payload()
                    state_payload["type"] = "restored_backup"
                    state_payload["message"] = f"Restored backup: {restored['filename']}"
                    if not await _safe_ws_send_json(ws, state_payload):
                        break

                elif action == "delete_backup":
                    filename = payload.get("filename")
                    if not isinstance(filename, str) or not filename.strip():
                        raise ValueError("Expected a backup filename.")

                    deleted = _delete_backup(filename)
                    if deleted and not await _safe_ws_send_json(ws, {
                        "type": "backup_deleted",
                        "message": f"Deleted backup: {filename}",
                        "backups": _list_backups(),
                    }):
                        break
                    break

                elif action == "create_manual_backup":
                    reason = payload.get("reason", "manual")
                    try:
                        backup_path = _create_manual_backup(reason)
                        if not await _safe_ws_send_json(ws, {
                            "type": "backup_created",
                            "message": f"Created manual backup: {backup_path.name}",
                            "backups": _list_backups(),
                        }):
                            break
                    except Exception as e:
                        if not await _safe_ws_send_json(ws, {
                            "type": "error",
                            "message": f"Failed to create backup: {e}",
                        }):
                            break
                    break

                elif action == "extend_session":
                    # Session extension handled via cookie refresh
                    if not await _safe_ws_send_json(ws, {"type": "session_extended"}):
                        break

                else:
                    raise ValueError(f"Unknown action: {action}")

            except Exception as exc:
                if not await _safe_ws_send_json(ws, {"type": "error", "message": f"{type(exc).__name__}: {exc}"}):
                    break

        elif msg.type == WSMsgType.ERROR:
            logger.error(f"WebSocket connection closed with exception: {ws.exception()}")

    return ws


async def start_config_web_server(host: str = HOST, port: int = PORT) -> None:
    logger.info("Starting config editor...")

    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/login", handle_login)
    app.router.add_get("/logout", handle_logout)
    app.router.add_post("/extend_session", handle_extend_session)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static", str(STATIC_DIR))

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host=host, port=port)

    try:
        await site.start()
        logger.info(f"Config editor running at http://{host}:{port}")

        stop_event = asyncio.Event()
        await stop_event.wait()

    except Exception as exc:
        logger.error(f"Failed to start config editor server on {host}:{port}: {exc}")
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
