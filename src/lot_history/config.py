"""Налаштування: читаються один раз зі змінних оточення (і з локального `.env`, якщо він є)."""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(".env")


def load_env_file(path: Path = ENV_FILE) -> None:
    """Читає рядки KEY=VALUE у змінні оточення. Уже задана змінна має перевагу, тож значення,
    передане через systemd або оболонку, файл не перезаписує."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    api_base: str = "https://procedure.prozorro.sale/api"
    site_base: str = "https://prozorro.sale"
    db_path: Path = Path("data/lots.sqlite3")
    page_size: int = 100
    # пауза між запитами: API не публікує ліміту, тому збирач навмисно повільний
    request_delay: float = 0.5
    timeout: float = 30.0
    max_retries: int = 4
    user_agent: str = "prozorro-sale-lot-history/0.1"
    airtable_token: str | None = None
    airtable_base_id: str | None = None
    airtable_table: str = "Lots"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        defaults = cls()
        return cls(
            db_path=Path(env.get("LOT_HISTORY_DB", defaults.db_path)),
            page_size=int(env.get("LOT_HISTORY_PAGE_SIZE", defaults.page_size)),
            request_delay=float(env.get("LOT_HISTORY_DELAY", defaults.request_delay)),
            airtable_token=env.get("AIRTABLE_TOKEN") or None,
            airtable_base_id=env.get("AIRTABLE_BASE_ID") or None,
            airtable_table=env.get("AIRTABLE_TABLE") or defaults.airtable_table,
        )
