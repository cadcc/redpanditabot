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
