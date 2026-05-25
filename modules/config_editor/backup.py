from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import persistence

BACKUP_DIR = Path(__file__).parent.parent.parent / "config-backups"


def list_backups() -> list[dict[str, Any]]:
    if not BACKUP_DIR.exists():
        return []

    backups: list[dict[str, Any]] = []
    for file_path in BACKUP_DIR.iterdir():
        if not file_path.is_file():
            continue

        stat = file_path.stat()
        backups.append({
            "name": file_path.name,
            "kind": "global_blocklist" if file_path.name.startswith("global_blocklist-") else "config",  # noqa: E501
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat() + "Z",
        })

    backups.sort(key=lambda item: item["modified"], reverse=True)
    return backups


def _resolve_backup_path(filename: str) -> Path:
    if Path(filename).name != filename:
        msg = "Invalid backup filename."
        raise ValueError(msg)

    backup_path = (BACKUP_DIR / filename).resolve()

    if backup_path.parent != BACKUP_DIR.resolve():
        msg_0 = "Backup path is outside the backup directory."
        raise ValueError(msg_0)
    if not backup_path.exists() or not backup_path.is_file():
        msg_1 = f"Backup not found: {filename}"
        raise FileNotFoundError(msg_1)

    return backup_path


def restore(filename: str) -> dict[str, Any]:
    backup_path = _resolve_backup_path(filename)
    backup_text = backup_path.read_text(encoding="utf-8")

    if backup_path.name.startswith("global_blocklist-"):
        items = [line.strip() for line in backup_text.splitlines() if line.strip()]
        saved_items = persistence.save_global_blocklist(items)

        return {
            "kind": "global_blocklist",
            "filename": backup_path.name,
            "items": saved_items,
        }

    return {
        "kind": "config",
        "filename": backup_path.name,
        "parsed": persistence.apply_candidate_raw(backup_text, reason="restore"),
        "raw": backup_text,
    }


def delete(filename: str) -> bool:
    backup_path = _resolve_backup_path(filename)

    try:
        backup_path.unlink()
        return True
    except FileNotFoundError as e:
        msg = f"Backup not found: {filename}"
        raise FileNotFoundError(msg) from e
    except PermissionError as e:
        msg_0 = f"Permission denied to delete: {filename}"
        raise PermissionError(msg_0) from e
