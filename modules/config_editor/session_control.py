import json
import math
import re as regexp
import time
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple, Self

from modules import global_vars as gv
from modules.logger import logger

SESSION_STATE_PATH = Path(__file__).parent.parent.parent / "config-editor-session-state.json"
DEFAULT_SESSION_VERSION = 1
DEFAULT_SESSION_LENGTH_SECONDS = 30 * 60
DEFAULT_SHOW_EXTEND_POPUP_SECONDS = 5 * 60


def get_compat(data: dict, key: str) -> int | float | None:
    res = data.get(key)
    if res is None:
        res = data.get(f"session_{key}")
    return res if isinstance(res, (int, float)) else None


UNIT_MAP: dict[str, tuple[str, int]] = {}

for abbr in ["s", "sec", "secs", "second", "seconds"]:
    UNIT_MAP[abbr] = ("seconds", 1)
for abbr in ["m", "min", "mins", "minute", "minutes"]:
    UNIT_MAP[abbr] = ("minutes", 1)
for abbr in ["h", "hr", "hrs", "hour", "hours"]:
    UNIT_MAP[abbr] = ("hours", 1)
for abbr in ["d", "day", "days"]:
    UNIT_MAP[abbr] = ("days", 1)
for abbr in ["w", "week", "weeks"]:
    UNIT_MAP[abbr] = ("weeks", 1)
for abbr in ["month", "months"]:
    UNIT_MAP[abbr] = ("days", 30)
for abbr in ["year", "years"]:
    UNIT_MAP[abbr] = ("days", 365)


def parse_duration(text: str) -> timedelta:
    text = str(text).strip().lower()
    m = regexp.fullmatch(r"([a-z]+|\d+(?:\.\d+)?)\s+([a-z]+)", text)

    if not m:
        msg = f"Invalid duration: {text!r}"
        raise ValueError(msg)

    amount_str, unit = m.groups()
    amount = float(amount_str)

    if unit not in UNIT_MAP:
        msg_0 = f"Unknown unit: {unit}"
        raise ValueError(msg_0)

    td_unit, multiplier = UNIT_MAP[unit]

    return timedelta(**{td_unit: amount * multiplier})


def _parse_iso8601_duration_seconds(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None

    try:
        duration = parse_duration(text)
    except Exception:
        logger.exception(f"Failed to parse duration '{text}':")
        return None

    if isinstance(duration, timedelta):
        seconds = duration.total_seconds()
        if seconds > 0:
            return max(1, math.ceil(seconds))
        return None

    return None


class SessionState(NamedTuple):
    version: int
    expires_at: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "version": self.version,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int | float]) -> Self:
        version = get_compat(data, "version")
        if not version or not isinstance(version, int) or version < 1:
            version = DEFAULT_SESSION_VERSION

        expires_at = get_compat(data, "expires_at")
        if not expires_at or not isinstance(expires_at, (int, float)):
            expires_at = 0.0

        return cls(
            version=int(version),
            expires_at=float(expires_at),
        )


DEFAULT_STATE = SessionState(
    version=DEFAULT_SESSION_VERSION,
    expires_at=0.0,
)


def _read_state() -> SessionState:
    if not SESSION_STATE_PATH.exists():
        return DEFAULT_STATE

    try:
        data = json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_STATE

    if not isinstance(data, dict):
        return DEFAULT_STATE

    return SessionState.from_dict(data)


def _write_state(state: SessionState) -> None:
    SESSION_STATE_PATH.write_text(
        json.dumps(state.to_dict(), indent=4) + "\n",
        encoding="utf-8",
    )
    logger.info(f"Saved config editor session state to {SESSION_STATE_PATH}.")


def _read_session_version() -> int:
    state = _read_state()
    version = state.version
    return version if version >= 1 else DEFAULT_SESSION_VERSION


def get_session_version() -> int:
    return _read_session_version()


def get_session_expires_at() -> float:
    return float(_read_state().expires_at)


def set_session_expires_at(expires_at: float) -> float:
    _write_state(
        SessionState(
            version=get_session_version(),
            expires_at=float(expires_at),
        ),
    )
    return float(expires_at)


def refresh_session_expires_at(ttl_seconds: int) -> float:
    return set_session_expires_at(time.time() + float(ttl_seconds))


def is_session_active() -> bool:
    return get_session_expires_at() > time.time()


def bump_session_version() -> int:
    next_ver = get_session_version() + 1
    _write_state(SessionState(version=next_ver, expires_at=time.time()))
    return next_ver


def get_config_editor_session_length_seconds() -> int:
    raw_value = gv.config.config_editor_session_length

    if raw_value:
        parsed = _parse_iso8601_duration_seconds(raw_value)
        if parsed is not None:
            return parsed

    return DEFAULT_SESSION_LENGTH_SECONDS


def get_config_editor_show_extend_popup_seconds() -> int:
    raw_value = gv.config.config_editor_show_extend_popup

    if raw_value:
        parsed = _parse_iso8601_duration_seconds(raw_value)
        if parsed is not None:
            return parsed

    return DEFAULT_SHOW_EXTEND_POPUP_SECONDS


def get_config_editor_warning_seconds() -> int:
    session_length = get_config_editor_session_length_seconds()
    warning_seconds = get_config_editor_show_extend_popup_seconds()

    if warning_seconds < 1:
        return 1

    if warning_seconds >= session_length:
        return max(1, session_length - 1)

    return warning_seconds
