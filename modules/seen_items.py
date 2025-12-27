import sqlite3
import time
from pathlib import Path
from .logger import logger


db_path = Path(__file__).parent.parent / "data" / "processed-listings.db"
db_path.parent.mkdir(parents=True, exist_ok=True)


class SeenItemsDB:
    def __init__(self, db_path=db_path) -> None:
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS seen_items (
                        item_id        INTEGER  PRIMARY KEY,
                        timestamp      INTEGER  NOT NULL,
                        category_name  TEXT,
                        title          TEXT,
                        mode           TEXT
                    )
                """)
                conn.commit()
            logger.debug(f"Database initialized at {self.db_path}")
        except Exception:
            logger.exception("Failed to initialize database:")
            raise

    def is_seen(self, item_id: int) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT 1 FROM seen_items WHERE item_id = ?", (item_id,))
                return cursor.fetchone() is not None
        except Exception:
            logger.exception(f"Error checking if item {item_id} is seen:")
            return False  # Default to False to avoid missing items

    def mark_seen(
        self,
        item_id: int,
        category_name: str | None = None,
        title: str = "",
        mode: str = ""
    ) -> None:
        try:
            current_time = int(time.time())
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO seen_items
                    (item_id, timestamp, category_name, title, mode)
                    VALUES (?, ?, ?, ?, ?)
                """, (item_id, current_time, category_name, title, mode))
                conn.commit()
            logger.debug(f"Marked item {item_id} as seen")
        except Exception:
            logger.exception(f"Error marking item {item_id} as seen:")

    def cleanup_old_items(self, days_old: int = 30) -> int:
        try:
            cutoff_time = int(time.time()) - (days_old * 24 * 60 * 60)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM seen_items WHERE timestamp < ?", (cutoff_time,))
                deleted_count = cursor.rowcount
                conn.commit()
            logger.info(f"Cleaned up {deleted_count} items older than {days_old} days")
            return deleted_count
        except Exception:
            logger.exception("Error cleaning up old items:")
            return 0


# create global DB instance
seen_db = SeenItemsDB()
