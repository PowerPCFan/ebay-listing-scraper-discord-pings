import asyncio
import hashlib
import hmac
import secrets
import textwrap
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import discord
from aiohttp import ClientSession, web

from modules import global_vars as gv
from modules.bot import bot as discord_bot
from modules.config_tools import get_parsed_config
from modules.logger import logger

from . import session_control, session_signals

AUTH_COOKIE_NAME = "config_editor_auth"
DISCORD_AUTH_COOKIE_NAME = "config_editor_discord_auth"
OAUTH_STATE_TTL_SECONDS = 60 * 10

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"  # noqa: S105
DISCORD_USER_URL = "https://discord.com/api/users/@me"
DISCORD_USER_GUILDS_URL = "https://discord.com/api/users/@me/guilds"


@dataclass(slots=True)
class AuthIdentity:
    kind: str
    user_id: str | None = None


_pending_states: dict[str, tuple[float, str]] = {}


def _get_password() -> str | None:
    password = get_parsed_config().get("config_editor_password")
    return password.strip() if isinstance(password, str) and password.strip() else None


def _get_client_id() -> str | None:
    client_id = get_parsed_config().get("config_editor_discord_client_id")
    return client_id.strip() if isinstance(client_id, str) and client_id.strip() else None


def _get_client_secret() -> str | None:
    client_secret = get_parsed_config().get("config_editor_discord_client_secret")
    return (
        client_secret.strip() if isinstance(client_secret, str) and client_secret.strip() else None
    )


def _oauth_enabled() -> bool:
    return bool(_get_client_id() and _get_client_secret())


def _build_redirect_uri(request: web.Request) -> str:
    configured_redirect_uri = get_parsed_config().get("config_editor_discord_redirect_uri")
    if isinstance(configured_redirect_uri, str) and configured_redirect_uri.strip():
        return configured_redirect_uri.strip()

    fallback_uri = f"{request.scheme}://{request.host}/oauth/discord/callback"
    logger.debug("Using fallback Discord redirect URI: %s", fallback_uri)
    return fallback_uri


def _password_fingerprint(password: str, session_version: int) -> str:
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"{session_version}:{password_hash}"


def _discord_session_signature(user_id: str, session_version: int) -> str:
    client_secret = _get_client_secret()
    if not client_secret:
        return ""
    return hmac.new(
        client_secret.encode("utf-8"),
        f"{session_version}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _build_discord_session_value(user_id: str, session_version: int) -> str:
    return f"{session_version}:{user_id}:{_discord_session_signature(user_id, session_version)}"


def _parse_discord_session_value(cookie_value: str) -> str | None:  # noqa: PLR0911
    if not cookie_value:
        return None

    version_text, separator, remainder = cookie_value.partition(":")
    if not separator or not version_text or not remainder:
        return None

    user_id, separator, signature = remainder.partition(":")
    if not separator or not user_id or not signature:
        return None

    try:
        session_version = int(version_text)
    except ValueError:
        return None

    current_version = session_control.get_session_version()
    if session_version != current_version:
        return None

    expected = _discord_session_signature(user_id, session_version)
    if not expected:
        return None

    if not hmac.compare_digest(signature, expected):
        return None

    return user_id


def _clear_login_cookies(response: web.StreamResponse) -> None:
    response.del_cookie(AUTH_COOKIE_NAME, path="/")
    response.del_cookie(DISCORD_AUTH_COOKIE_NAME, path="/")


def _set_password_cookie(response: web.StreamResponse, request: web.Request) -> None:
    password = _get_password()
    if not password:
        return

    session_length_seconds = session_control.get_config_editor_session_length_seconds()
    session_version = session_control.get_session_version()
    session_control.refresh_session_expires_at(session_length_seconds)

    response.set_cookie(
        AUTH_COOKIE_NAME,
        _password_fingerprint(password, session_version),
        httponly=True,
        samesite="Lax",
        secure=request.scheme == "https",
        max_age=session_length_seconds,
        path="/",
    )
    logger.debug("Set password session cookie with session version %s.", session_version)


def _set_discord_cookie(response: web.StreamResponse, request: web.Request, user_id: str) -> None:
    session_length_seconds = session_control.get_config_editor_session_length_seconds()
    session_version = session_control.get_session_version()
    session_control.refresh_session_expires_at(session_length_seconds)
    response.set_cookie(
        DISCORD_AUTH_COOKIE_NAME,
        _build_discord_session_value(user_id, session_version),
        httponly=True,
        samesite="Lax",
        secure=request.scheme == "https",
        max_age=session_length_seconds,
        path="/",
    )
    # discord cookie set


def _get_current_auth_identity(request: web.Request) -> AuthIdentity | None:
    if not session_control.is_session_active():
        logger.debug("Session expired according to server-side session state.")
        return None

    password = _get_password()
    if password:
        cookie_value = request.cookies.get(AUTH_COOKIE_NAME)
        expected = _password_fingerprint(password, session_control.get_session_version())
        if cookie_value and hmac.compare_digest(cookie_value, expected):
            logger.debug("Authenticated request via password session cookie.")
            return AuthIdentity(kind="password")

    cookie_value = request.cookies.get(DISCORD_AUTH_COOKIE_NAME)
    if cookie_value:
        user_id = _parse_discord_session_value(cookie_value)
        if user_id:
            logger.debug("Authenticated request via Discord session cookie for user %s.", user_id)
            return AuthIdentity(kind="discord", user_id=user_id)

    return None


async def _get_authorized_member(user_id: str) -> discord.Member | None:
    if not hasattr(discord_bot, "is_ready") or not discord_bot.is_ready():
        logger.warning("Discord bot is not ready; cannot verify guild member %s yet.", user_id)
        return None

    guild_id = gv.config.discord_guild_id
    guild = discord_bot.get_guild(guild_id)
    if guild is None:
        logger.debug("Configured guild %s was not found on the Discord bot.", guild_id)
        return None

    try:
        member = await guild.fetch_member(int(user_id))
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError):
        logger.warning("Failed to fetch guild member %s from Discord API.", user_id)
        return None

    if member is None:
        logger.debug("User %s is not a member of configured guild %s.", user_id, guild_id)
        return None

    logger.debug("Verified user %s is a member of configured guild %s.", user_id, guild_id)
    return member


def _is_member_authorized(member: discord.Member) -> bool:
    admin_role = member.guild.get_role(gv.config.admin_role_id)
    if admin_role and admin_role in member.roles:
        logger.debug(
            "Member %s has admin role %s in guild %s.",
            member.id,
            gv.config.admin_role_id,
            member.guild.id,
        )
        return True

    logger.debug(
        "Member %s missing admin role %s in guild %s.",
        member.id,
        gv.config.admin_role_id,
        member.guild.id,
    )
    return False


def login_page(error_message: str = "") -> web.Response:
    password = _get_password()
    oauth_enabled = _oauth_enabled()

    error_block = ""
    if error_message:
        error_block = f'<p style="color: #fca5a5; margin: 0 0 16px;">{error_message}</p>'

    oauth_block = ""
    if oauth_enabled:
        oauth_block = textwrap.dedent(
            """
            <a href="/login/discord" style="display:flex; margin-top: 12px; padding: 10px 14px; border-radius: 10px; background: #5865f2; color: white; text-decoration: none; font-weight: 600; justify-content: center; align-items: center; gap: 8px; width: fit-content; margin-inline: auto;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" fill="#FFFFFF" width="24px" height="24px"><path d="M524.5 133.8C524.3 133.5 524.1 133.2 523.7 133.1C485.6 115.6 445.3 103.1 404 96C403.6 95.9 403.2 96 402.9 96.1C402.6 96.2 402.3 96.5 402.1 96.9C396.6 106.8 391.6 117.1 387.2 127.5C342.6 120.7 297.3 120.7 252.8 127.5C248.3 117 243.3 106.8 237.7 96.9C237.5 96.6 237.2 96.3 236.9 96.1C236.6 95.9 236.2 95.9 235.8 95.9C194.5 103 154.2 115.5 116.1 133C115.8 133.1 115.5 133.4 115.3 133.7C39.1 247.5 18.2 358.6 28.4 468.2C28.4 468.5 28.5 468.7 28.6 469C28.7 469.3 28.9 469.4 29.1 469.6C73.5 502.5 123.1 527.6 175.9 543.8C176.3 543.9 176.7 543.9 177 543.8C177.3 543.7 177.7 543.4 177.9 543.1C189.2 527.7 199.3 511.3 207.9 494.3C208 494.1 208.1 493.8 208.1 493.5C208.1 493.2 208.1 493 208 492.7C207.9 492.4 207.8 492.2 207.6 492.1C207.4 492 207.2 491.8 206.9 491.7C191.1 485.6 175.7 478.3 161 469.8C160.7 469.6 160.5 469.4 160.3 469.2C160.1 469 160 468.6 160 468.3C160 468 160 467.7 160.2 467.4C160.4 467.1 160.5 466.9 160.8 466.7C163.9 464.4 167 462 169.9 459.6C170.2 459.4 170.5 459.2 170.8 459.2C171.1 459.2 171.5 459.2 171.8 459.3C268 503.2 372.2 503.2 467.3 459.3C467.6 459.2 468 459.1 468.3 459.1C468.6 459.1 469 459.3 469.2 459.5C472.1 461.9 475.2 464.4 478.3 466.7C478.5 466.9 478.7 467.1 478.9 467.4C479.1 467.7 479.1 468 479.1 468.3C479.1 468.6 479 468.9 478.8 469.2C478.6 469.5 478.4 469.7 478.2 469.8C463.5 478.4 448.2 485.7 432.3 491.6C432.1 491.7 431.8 491.8 431.6 492C431.4 492.2 431.3 492.4 431.2 492.7C431.1 493 431.1 493.2 431.1 493.5C431.1 493.8 431.2 494 431.3 494.3C440.1 511.3 450.1 527.6 461.3 543.1C461.5 543.4 461.9 543.7 462.2 543.8C462.5 543.9 463 543.9 463.3 543.8C516.2 527.6 565.9 502.5 610.4 469.6C610.6 469.4 610.8 469.2 610.9 469C611 468.8 611.1 468.5 611.1 468.2C623.4 341.4 590.6 231.3 524.2 133.7zM222.5 401.5C193.5 401.5 169.7 374.9 169.7 342.3C169.7 309.7 193.1 283.1 222.5 283.1C252.2 283.1 275.8 309.9 275.3 342.3C275.3 375 251.9 401.5 222.5 401.5zM417.9 401.5C388.9 401.5 365.1 374.9 365.1 342.3C365.1 309.7 388.5 283.1 417.9 283.1C447.6 283.1 471.2 309.9 470.7 342.3C470.7 375 447.5 401.5 417.9 401.5z"/></svg>
            Continue with Discord
            </a>
            """,  # noqa: E501
        ).strip()

    password_block = ""
    if password and not oauth_enabled:
        password_block = textwrap.dedent(
            """
            <form method="post" action="/login" style="display:grid; gap: 12px; margin-top: 18px;">
                <label for="password" style="display:grid; gap: 6px; text-align: left;">
                    <span>Password</span>
                    <input id="password" name="password" type="password" autocomplete="current-password" required style="padding: 10px 12px; border-radius: 10px; border: 1px solid #374151; background: #111827; color: #f9fafb;" />
                </label>
                <button type="submit" style="padding: 10px 14px; border: 0; border-radius: 10px; background: #e5e7eb; color: #111827; font-weight: 600; cursor: pointer;">Log in</button>
            </form>
            """,  # noqa: E501
        ).strip()

    fallback_block = ""
    if not password and not oauth_enabled:
        fallback_block = '<p style="margin: 0; color: #fbbf24;">No login method is configured. Add a password or Discord OAuth settings to the config.</p>'  # noqa: E501

    body = textwrap.dedent(
        f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>Log in</title>
        </head>
        <body style="margin:0; min-height:100vh; display:grid; place-items:center; background: linear-gradient(180deg, #0f172a, #111827); color:#f9fafb; font-family: system-ui, sans-serif;">
          <main style="width:min(92vw, 420px); padding: 28px; border-radius: 18px; background: rgba(17, 24, 39, 0.94); border: 1px solid rgba(148, 163, 184, 0.2);">
            <h1 style="margin: 0 0 8px; font-size: 1.5rem; text-align: center; width: 100%">Log in</h1>
            {error_block}
            {oauth_block}
            {password_block}
            {fallback_block}
          </main>
        </body>
        </html>
        """,  # noqa: E501
    ).strip()

    return web.Response(text=body, content_type="text/html")


def editor_authenticated(request: web.Request) -> bool:
    identity = _get_current_auth_identity(request)

    cookies = list(request.cookies.keys())
    if not cookies:
        cookies = None
    kind = identity.kind if identity else None
    logger.debug(f"Editor authentication check: cookies: {cookies!r}; identity: {kind!r}")

    return identity is not None


async def handle_login(request: web.Request) -> web.Response:
    password = _get_password()
    oauth_enabled = _oauth_enabled()

    logger.debug(
        f"Login requested; OAuth2 Enabled: {oauth_enabled!r}, Password Auth Enabled: {password is not None and not oauth_enabled!r}.",  # noqa: E501
    )

    if oauth_enabled:
        logger.debug("Redirecting password login to Discord OAuth because OAuth is configured.")
        raise web.HTTPFound(location="/login/discord")

    if not password:
        logger.debug("No password configured and OAuth is disabled; redirecting to root.")
        raise web.HTTPFound(location="/")

    data = await request.post()
    submitted = str(data.get("password", "")).strip()

    if hmac.compare_digest(submitted, password):
        logger.info("Password login succeeded.")
        response = web.HTTPFound("/")
        _set_password_cookie(response, request)
        await session_signals.notify_session_extended()
        return response

    logger.warning("Password login failed: invalid password supplied.")
    return login_page("Invalid password.")


async def handle_discord_login(request: web.Request) -> web.Response:
    if not _oauth_enabled():
        logger.warning("Discord OAuth login requested but OAuth is not configured.")
        return login_page("Discord OAuth is not configured.")

    state = secrets.token_urlsafe(32)
    next_path = request.query.get("next", "/")
    _pending_states[state] = (time.time() + OAUTH_STATE_TTL_SECONDS, next_path)

    redirect_uri = _build_redirect_uri(request)
    client_id = _get_client_id() or ""
    logger.debug(
        "Starting Discord OAuth flow (client_id=%s, redirect_uri=%s, next=%s, state_len=%s).",
        client_id,
        redirect_uri,
        next_path,
        len(state),
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    logger.debug("Discord OAuth authorize URL prepared.")
    return web.HTTPFound(f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}")


async def _exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id = _get_client_id()
    client_secret = _get_client_secret()
    if not client_id or not client_secret:
        msg = "Discord OAuth is not configured."
        raise RuntimeError(msg)

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    logger.debug(
        "Exchanging Discord OAuth code for token (client_id=%s, redirect_uri=%s, code_len=%s).",
        client_id,
        redirect_uri,
        len(code),
    )

    async with (
        ClientSession() as session,
        session.post(DISCORD_TOKEN_URL, data=data) as response,
    ):
        token_data = await response.json(content_type=None)
        if response.status >= 400:  # noqa: PLR2004
            logger.error("Discord token exchange failed: %s", token_data)
            msg = "Discord token exchange failed."
            raise RuntimeError(msg)
        logger.debug("Discord token exchange succeeded.")
        return token_data


async def _fetch_discord_user(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.debug("Fetching Discord user profile from /users/@me.")
    async with (
        ClientSession() as session,
        session.get(DISCORD_USER_URL, headers=headers) as response,
    ):
        user_data = await response.json(content_type=None)
        if response.status >= 400:  # noqa: PLR2004
            logger.error("Discord user lookup failed: %s", user_data)
            msg = "Discord user lookup failed."
            raise RuntimeError(msg)
        logger.debug("Discord user profile fetch succeeded for user %s.", user_data.get("id"))
        return user_data


async def _fetch_discord_user_guild_ids(access_token: str) -> set[str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.debug("Fetching Discord guild list from /users/@me/guilds.")
    async with (
        ClientSession() as session,
        session.get(DISCORD_USER_GUILDS_URL, headers=headers) as response,
    ):
        guilds_data = await response.json(content_type=None)
        if response.status >= 400:  # noqa: PLR2004
            logger.error("Discord guild lookup failed: %s", guilds_data)
            msg = "Discord guild lookup failed."
            raise RuntimeError(msg)

        guild_ids: set[str] = set()
        if isinstance(guilds_data, list):
            for guild in guilds_data:
                if isinstance(guild, dict):
                    guild_id = str(guild.get("id", "")).strip()
                    if guild_id:
                        guild_ids.add(guild_id)
        logger.debug("Discord guild lookup succeeded; found %s guilds.", len(guild_ids))
        return guild_ids


def _consume_pending_state(state: str) -> str | None:
    entry = _pending_states.pop(state, None)
    if not entry:
        logger.warning("Discord OAuth callback received unknown or already-used state.")
        return None

    expires_at, next_path = entry
    if time.time() > expires_at:
        logger.warning("Discord OAuth callback state expired before use.")
        return None

    return next_path or "/"


async def handle_discord_callback(request: web.Request) -> web.Response:  # noqa: C901, PLR0911
    if not _oauth_enabled():
        logger.warning("Discord OAuth callback reached but OAuth is not configured.")
        return login_page("Discord OAuth is not configured.")

    oauth_error = request.query.get("error")
    if oauth_error:
        logger.warning("Discord OAuth callback returned error: %s", oauth_error)
        return login_page(f"Discord sign-in was cancelled or failed: {oauth_error}")

    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state:
        logger.warning("Discord OAuth callback missing code or state.")
        return login_page("Discord sign-in response was incomplete.")

    next_path = _consume_pending_state(state)
    if not next_path:
        logger.warning("Discord OAuth callback rejected because state could not be validated.")
        return login_page("Discord sign-in expired. Please try again.")

    redirect_uri = _build_redirect_uri(request)
    logger.debug("Processing Discord OAuth callback for next path %s.", next_path)

    try:
        token_data = await _exchange_code_for_token(code, redirect_uri)
        access_token = str(token_data.get("access_token", "")).strip()
        if not access_token:
            msg = "Discord OAuth response did not include an access token."
            raise RuntimeError(msg)  # noqa: TRY301

        user_guild_ids = await _fetch_discord_user_guild_ids(access_token)
        configured_guild_id = str(gv.config.discord_guild_id).strip()
        logger.debug(
            "Configured guild membership check: required=%s present=%s.",
            configured_guild_id,
            configured_guild_id in user_guild_ids,
        )
        if configured_guild_id not in user_guild_ids:
            logger.info(
                "Discord OAuth authentication failed: user is not in configured guild %s.",
                configured_guild_id,
            )
            return login_page(
                "Your Discord account is not in the configured guild for this editor.",
            )

        user_data = await _fetch_discord_user(access_token)
        user_id = str(user_data.get("id", "")).strip()
        if not user_id:
            msg_0 = "Discord OAuth response did not include a user id."
            raise RuntimeError(msg_0)  # noqa: TRY301

        logger.debug("Discord OAuth user id resolved to %s.", user_id)

        member = await _get_authorized_member(user_id)
        if not member or not _is_member_authorized(member):
            logger.info("Discord OAuth authentication failed: user %s is not authorized.", user_id)
            return login_page(
                "Your Discord account is not authorized to use the config editor.",
            )

        response = web.HTTPFound(next_path)
        _set_discord_cookie(response, request, user_id)
        await session_signals.notify_session_extended()
        logger.info("Discord OAuth authentication succeeded for user %s.", user_id)
        return response
    except web.HTTPFound:
        raise
    except Exception as exc:
        logger.exception("Discord OAuth callback failed:")
        return login_page(f"Discord sign-in failed: {type(exc).__name__}")


async def handle_extend_session(request: web.Request) -> web.Response:
    identity = _get_current_auth_identity(request)
    if identity is None:
        logger.warning("Session extension requested without a valid session.")
        return web.json_response({"message": "Not authenticated"}, status=401)

    session_length_seconds = session_control.get_config_editor_session_length_seconds()

    response = web.Response(text="Session extended")
    if identity.kind == "password":
        logger.debug("Extending password-based session.")
        _set_password_cookie(response, request)
        await session_signals.notify_session_extended()
        expires_at = session_control.get_session_expires_at()
        return web.json_response(
            {
                "message": (
                    f"Session extended by {session_length_seconds // 60} "
                    f"minute{'s' if session_length_seconds // 60 != 1 else ''}."
                ),
                "expires_at": int(expires_at * 1000),
                "warning_seconds": session_control.get_config_editor_warning_seconds(),
                "session_length_seconds": session_length_seconds,
            },
        )

    if identity.kind == "discord" and identity.user_id:
        logger.debug("Extending Discord-based session for user %s.", identity.user_id)
        member = await _get_authorized_member(identity.user_id)
        if not member or not _is_member_authorized(member):
            logger.warning(
                "Session extension rejected because the Discord user is no longer authorized.",
            )
            return web.json_response({"message": "Not authenticated"}, status=401)
        _set_discord_cookie(response, request, identity.user_id)
        await session_signals.notify_session_extended()
        expires_at = session_control.get_session_expires_at()
        return web.json_response(
            {
                "message": (
                    f"Session extended by {session_length_seconds // 60} "
                    f"minute{'s' if session_length_seconds // 60 != 1 else ''}."
                ),
                "expires_at": int(expires_at * 1000),
                "warning_seconds": session_control.get_config_editor_warning_seconds(),
                "session_length_seconds": session_length_seconds,
            },
        )

    return web.json_response({"message": "Not authenticated"}, status=401)


async def handle_logout(_request: web.Request) -> web.Response:
    reset_all_sessions()
    response = web.HTTPFound("/")
    _clear_login_cookies(response)
    return response


NOTIFY_SESSION_RESET_TASK = set()


def reset_all_sessions() -> int:
    next_version = session_control.bump_session_version()
    logger.warning(
        "All config editor sessions invalidated; new session version is %s.",
        next_version,
    )
    try:
        task = asyncio.create_task(session_signals.notify_session_reset())
        NOTIFY_SESSION_RESET_TASK.add(task)
        task.add_done_callback(NOTIFY_SESSION_RESET_TASK.discard)
    except Exception:
        logger.exception("Failed to broadcast session reset notification.")
    return next_version
