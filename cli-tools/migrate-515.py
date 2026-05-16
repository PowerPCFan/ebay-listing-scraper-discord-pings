#!/usr/bin/env python3

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def migrate_keyword_value(keyword_value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(keyword_value, dict):
        mode = str(keyword_value.get("mode", "poll")).strip().lower() or "poll"
        filter_value = keyword_value.get("filter")
        query_value = keyword_value.get("query")

        if filter_value is None and isinstance(keyword_value.get("keyword"), str):
            filter_value = keyword_value.get("keyword")

        if mode != "query":
            mode = "poll"
            query_value = None

        return {
            "mode": mode,
            "filter": filter_value if isinstance(filter_value, str) else "",
            "query": query_value if isinstance(query_value, str) else None,
        }

    return {
        "mode": "poll",
        "filter": str(keyword_value or ""),
        "query": None,
    }


def migrate_ping(ping: dict[str, Any]) -> bool:
    changed = False

    old_kw = ping.get("keywords")
    if isinstance(old_kw, list):
        new_items: list[dict[str, Any]] = []

        for entry in old_kw:
            if not isinstance(entry, dict):
                continue

            updated = dict(entry)
            updated["keyword"] = migrate_keyword_value(entry.get("keyword"))  # pyright: ignore[reportArgumentType]
            new_items.append(updated)

        ping["items"] = new_items
        ping.pop("keywords", None)
        changed = True

    items = ping.get("items")
    if isinstance(items, list):
        for entry in items:
            if not isinstance(entry, dict):
                continue

            keyword_value = entry.get("keyword")
            if isinstance(keyword_value, str) or not isinstance(keyword_value, dict):
                entry["keyword"] = migrate_keyword_value(keyword_value)  # pyright: ignore[reportArgumentType]
                changed = True

    return changed


def migrate_document(doc: dict[str, Any]) -> tuple[dict[str, Any], int]:
    pings = doc.get("pings")

    if not isinstance(pings, list):
        return doc, 0

    cc = 0
    for ping in pings:
        if isinstance(ping, dict) and migrate_ping(ping):
            cc += 1

    return doc, cc


parser = argparse.ArgumentParser(description="Migrate config to use new structure as of 5/15/26 (i should really use schema versioning huh...)")  # noqa: E501
parser.add_argument("config", help="Path to config JSON file")
args = parser.parse_args()

config_path = Path(args.config)
backup = Path(
    f"{config_path.name}_{datetime.now(tz=UTC).strftime('%Y-%m-%d_%H-%M-%S')}{config_path.suffix}.bak",
)

backup.write_text(
    config_path.read_text(
        encoding="utf-8",
    ),
    encoding="utf-8",
)

migrated, changed = migrate_document(
    json.loads(
        config_path.read_text(
            encoding="utf-8",
        ),
    ),  # pyright: ignore[reportArgumentType]
)

config_path.write_text(
    json.dumps(migrated, indent=4) + "\n",
    encoding="utf-8",
)
print(f"Migrated {changed} ping block(s). Backup location: {backup}")
