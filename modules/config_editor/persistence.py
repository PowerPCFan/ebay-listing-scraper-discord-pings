import json
from typing import Any

from modules import global_vars as gv
from modules.config_tools import (
    get_config_path,
    get_parsed_config,
    get_raw_config,
    reload_config,
    reload_global_blocklist,
)
from modules.logger import logger

from . import backup_io


def _validate_discord_id_string_fields(  # noqa: C901
    candidate_data: dict[str, Any],
    reason: str = "save",
) -> None:
    if not isinstance(candidate_data, dict):
        msg = "Config root must be an object when validating Discord ID fields."
        raise TypeError(msg)

    invalid_paths: list[str] = []

    def _check_string_field(container: dict[str, Any], key: str, path: str) -> None:
        if not isinstance(container, dict):
            return
        if key not in container:
            return
        value = container.get(key)
        if value is None:
            return
        if not isinstance(value, str):
            invalid_paths.append(f"{path} (got {type(value).__name__})")

    _check_string_field(candidate_data, "discord_guild_id", "discord_guild_id")
    _check_string_field(candidate_data, "admin_role_id", "admin_role_id")
    _check_string_field(candidate_data, "logger_webhook_ping", "logger_webhook_ping")

    pings = candidate_data.get("pings")
    if isinstance(pings, list):
        for p_idx, ping in enumerate(pings):
            if not isinstance(ping, dict):
                invalid_paths.append(f"pings[{p_idx}] (got {type(ping).__name__})")
                continue
            _check_string_field(ping, "channel_id", f"pings[{p_idx}].channel_id")
            _check_string_field(ping, "role", f"pings[{p_idx}].role")

    self_roles = candidate_data.get("self_roles")
    if isinstance(self_roles, list):
        for g_idx, group in enumerate(self_roles):
            if not isinstance(group, dict):
                invalid_paths.append(f"self_roles[{g_idx}] (got {type(group).__name__})")
                continue
            roles = group.get("roles")
            if not isinstance(roles, list):
                continue
            for r_idx, role in enumerate(roles):
                if not isinstance(role, dict):
                    invalid_paths.append(
                        f"self_roles[{g_idx}].roles[{r_idx}] (got {type(role).__name__})",
                    )
                    continue
                _check_string_field(role, "id", f"self_roles[{g_idx}].roles[{r_idx}].id")

    if invalid_paths:
        details = ", ".join(invalid_paths)
        logger.critical(
            f"Blocked config write ({reason}): Discord ID fields must be strings. "
            f"Invalid fields: {details}",
        )
        msg = (
            "Blocked save: one or more Discord ID fields are not strings. "
            f"Invalid fields: {details}"
        )
        raise ValueError(msg)


def apply_candidate_raw(candidate_raw: str, reason: str = "save") -> dict[str, Any]:
    config_path = get_config_path()
    previous_raw = get_raw_config()

    parsed_candidate = json.loads(candidate_raw)
    _validate_discord_id_string_fields(parsed_candidate, reason=reason)  # pyright: ignore[reportArgumentType]

    version_value = parsed_candidate.get("config_version")
    version = str(version_value).strip() if version_value else None
    backup_io.write_snapshot(previous_raw=previous_raw, reason=reason, version=version)
    config_path.write_text(candidate_raw, encoding="utf-8")

    try:
        gv.config = reload_config()
    except Exception:
        config_path.write_text(previous_raw, encoding="utf-8")
        gv.config = reload_config()
        raise

    logger.info(f"Saved config to {config_path} and reloaded runtime config.")

    return get_parsed_config()


def apply_candidate_parsed(candidate_data: dict[str, Any]) -> str:
    if not isinstance(candidate_data, dict):
        msg = "Parsed config payload must be an object."
        raise TypeError(msg)

    _validate_discord_id_string_fields(candidate_data, reason="save_parsed")
    serialized = json.dumps(candidate_data, indent=4, ensure_ascii=False)
    apply_candidate_raw(serialized)
    return serialized


def build_export_json() -> str:
    parsed = get_parsed_config()
    return json.dumps(parsed, indent=4, ensure_ascii=False)


def save_global_blocklist(items: list[str]) -> list[str]:
    normalized: list[str] = []
    seen_lower: set[str] = set()

    for item in items:
        value = item.strip().lower()
        if not value or value in seen_lower:
            continue
        seen_lower.add(value)
        normalized.append(value)

    previous_items = list(gv.global_blocklist.items)
    backup_io.write_global_blocklist_backup(previous_items)

    gv.global_blocklist.items = normalized
    gv.global_blocklist.save()
    logger.info("Saved global blocklist.")
    gv.global_blocklist = reload_global_blocklist()

    return list(gv.global_blocklist.items)
