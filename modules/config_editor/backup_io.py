from datetime import UTC, datetime
from pathlib import Path

from modules.config_tools import get_config_path, get_raw_config

BACKUP_DIR = Path(__file__).parent.parent / "config-backups"

def _ts_for_backupname() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d_%H-%M-%S")

def write_snapshot(previous_raw: str, reason: str, version: str | None = None) -> Path:
    config_path = get_config_path()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = _ts_for_backupname()
    safe_reason = "".join(ch if ch.isalnum() else "-" for ch in reason).strip("-") or "save"
    version_part = ""
    if version:
        safe_version = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in version).strip(
            "-",
        )
        if safe_version:
            version_part = f"_v{safe_version}"

    backup_name = f"{config_path.stem}_{timestamp}{version_part}_{safe_reason}{config_path.suffix}"
    backup_path = BACKUP_DIR / backup_name

    backup_path.write_text(previous_raw, encoding="utf-8")
    return backup_path

def write_global_blocklist_backup(previous_items: list[str]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _ts_for_backupname()
    backup_path = BACKUP_DIR / f"global_blocklist_{timestamp}_save.txt"
    backup_path.write_text("\n".join(previous_items) + "\n", encoding="utf-8")

    return backup_path

def create_manual_backup(reason: str = "manual") -> Path:
    return write_snapshot(previous_raw=get_raw_config(), reason=reason)
