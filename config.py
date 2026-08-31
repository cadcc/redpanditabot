import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not set. Define it in the environment or in a .env file."
    )

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///redpanditabot.sqlite3")
FUN_COMMANDS_ENABLED = _get_bool("FUN_COMMANDS_ENABLED", default=False)
TITLE_REFRESH_INTERVAL_SECONDS = int(os.environ.get("TITLE_REFRESH_INTERVAL_SECONDS", "60"))


def _get_id_set(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    ids = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            raise RuntimeError(f"{name} must be a comma-separated list of Telegram user IDs, got {chunk!r}")
    return frozenset(ids)


SUPERADMIN_USER_IDS = _get_id_set("SUPERADMIN_USER_IDS")
