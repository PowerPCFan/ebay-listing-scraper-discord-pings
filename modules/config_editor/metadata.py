import json
from pathlib import Path
from typing import Any, TypedDict

from modules import global_vars as gv
from modules.bot import bot as discord_bot
from modules.logger import logger

EDITOR_METADATA_PATH = Path(__file__).parent.parent.parent / "config-editor-metadata.json"


class ChannelOrRoleMetadata(TypedDict):
    id: str
    name: str


class GuildsMetadata(TypedDict):
    id: str
    name: str
    channels: list[ChannelOrRoleMetadata]
    roles: list[ChannelOrRoleMetadata]


class Metadata(TypedDict):
    ready: bool
    guilds: list[GuildsMetadata]


def get_discord_meta() -> Metadata:
    metadata: Metadata = {"ready": True, "guilds": []}

    try:
        if (
            hasattr(discord_bot, "is_ready")
            and discord_bot.is_ready()
            and (guild := discord_bot.get_guild(gv.config.discord_guild_id))
        ):
            g_data: GuildsMetadata = {
                "id": str(guild.id),
                "name": guild.name,
                "channels": [],
                "roles": [],
            }
            for channel in guild.text_channels:
                g_data["channels"].append({"id": str(channel.id), "name": channel.name})

            roles = [role for role in guild.roles if not role.is_default()]
            roles.reverse()

            for role in roles:
                g_data["roles"].append({"id": str(role.id), "name": role.name})

            metadata["guilds"].append(g_data)
    except Exception:
        logger.exception("Error fetching Discord metadata:")
        metadata["ready"] = False

    return metadata


def reconcile(metadata: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
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
        ping_items = ping.get("items") if isinstance(ping, dict) else []
        if not isinstance(ping_items, list):
            ping_items = []

        existing_ping_meta = (
            existing_pings[ping_idx]
            if ping_idx < len(existing_pings) and isinstance(existing_pings[ping_idx], dict)
            else {}
        )
        existing_items_meta = existing_ping_meta.get("items")

        if not isinstance(existing_items_meta, list):
            existing_items_meta = []

        items_meta: list[dict[str, Any]] = []
        for item_idx, _ in enumerate(ping_items):
            existing_item_meta = (
                existing_items_meta[item_idx]
                if item_idx < len(existing_items_meta)
                and isinstance(existing_items_meta[item_idx], dict)
                else {}
            )

            mode = existing_item_meta.get("mode")
            if mode not in ("manual", "typed"):
                mode = "manual"

            component_type = existing_item_meta.get("component_type")
            if component_type is not None and not isinstance(component_type, str):
                component_type = None

            component_data = existing_item_meta.get("component_data")
            if not isinstance(component_data, dict):
                component_data = {}

            items_meta.append({
                "mode": mode,
                "component_type": component_type,
                "component_data": component_data,
            })

        reconciled_pings.append({"items": items_meta})

    return {
        "version": 1,
        "pings": reconciled_pings,
    }


def load(parsed: dict[str, Any]) -> dict[str, Any]:
    if EDITOR_METADATA_PATH.exists():
        try:
            loaded = json.loads(EDITOR_METADATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
    else:
        loaded = {}

    return reconcile(loaded, parsed)


def save(metadata: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    reconciled = reconcile(metadata, parsed)

    EDITOR_METADATA_PATH.write_text(
        json.dumps(reconciled, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return reconciled
