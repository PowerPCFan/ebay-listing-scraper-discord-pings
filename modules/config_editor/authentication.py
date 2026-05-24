import hashlib
import hmac
import textwrap

from aiohttp import web

from modules.config_tools import get_parsed_config

AUTH_COOKIE_NAME = "config_editor_auth"
MAX_AGE = 60 * 30  # 30 minutes


async def handle_extend_session(request: web.Request) -> web.Response:
    password = _get_config_editor_password()
    if not password:
        return web.HTTPFound("/")

    if not editor_authenticated(request):
        return web.Response(text="Not authenticated", status=401)

    response = web.Response(text="Session extended")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        _password_fingerprint(password),
        httponly=True,
        samesite="Strict",
        secure=request.scheme == "https",
        max_age=MAX_AGE,
        path="/",
    )
    return response


async def handle_login(request: web.Request) -> web.Response:
    password = _get_config_editor_password()
    if not password:
        raise web.HTTPFound(location="/")

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
            max_age=MAX_AGE,
            path="/",
        )
        return response

    return web.Response(text=_login_html("Invalid password."), content_type="text/html", status=401)


def _password_fingerprint(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _get_config_editor_password() -> str | None:
    direct = get_parsed_config().get("config_editor_password")
    return direct.strip() if direct else None


def _login_html(error_message: str = "") -> str:
    error_block = ""
    if error_message:
        error_block = f'<p style="color: red;">{error_message}</p>'

    return textwrap.dedent(f"""\
        <!DOCTYPE html>
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
        </html>
    """)  # noqa: E501


def login_page() -> web.Response:
    return web.Response(text=_login_html(), content_type="text/html")


def editor_authenticated(request: web.Request) -> bool:
    password = _get_config_editor_password()
    if not password:
        return True

    cookie_value = request.cookies.get(AUTH_COOKIE_NAME)
    if not cookie_value:
        return False

    expected = _password_fingerprint(password)
    return hmac.compare_digest(cookie_value, expected)


async def handle_logout(_request: web.Request) -> web.Response:
    response = web.HTTPFound("/")
    response.del_cookie(AUTH_COOKIE_NAME, path="/")
    return response
