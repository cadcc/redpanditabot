import logging
from pathlib import Path

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import config
from db import init_db
from handlers import core, jobs, photo, pin, title, vars as vars_handlers
from plugins import fun

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

COMMANDS_FILE = Path(__file__).resolve().parent / "commands.txt"


def load_bot_commands(path: Path) -> list[BotCommand]:
    commands = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, description = line.partition(" - ")
        commands.append(BotCommand(name, description))
    return commands


async def post_init(application: Application) -> None:
    commands = load_bot_commands(COMMANDS_FILE)
    await application.bot.set_my_commands(commands)
    logger.info("Registered %d bot commands", len(commands))


def build_application() -> Application:
    application = (
        Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    )

    application.add_handler(CommandHandler("start", core.start))
    application.add_handler(CommandHandler("help", core.help_command))
    application.add_handler(CommandHandler("ping", core.ping))

    application.add_handler(CommandHandler("get_title", title.get_title))
    application.add_handler(CommandHandler("title", title.get_title))
    application.add_handler(CommandHandler("set_title", title.set_title))

    application.add_handler(CommandHandler("text", vars_handlers.text))
    application.add_handler(CommandHandler("year", vars_handlers.year))
    application.add_handler(CommandHandler("month", vars_handlers.month))
    application.add_handler(CommandHandler("week", vars_handlers.week))
    application.add_handler(CommandHandler("day", vars_handlers.day))
    application.add_handler(CommandHandler("hour", vars_handlers.hour))
    application.add_handler(CommandHandler("minute", vars_handlers.minute))
    application.add_handler(CommandHandler("second", vars_handlers.second))
    application.add_handler(CommandHandler("fragment", vars_handlers.fragment))
    application.add_handler(CommandHandler("list_vars", vars_handlers.list_vars))
    application.add_handler(CommandHandler("rm_var", vars_handlers.rm_var))
    application.add_handler(
        CallbackQueryHandler(
            vars_handlers.rm_var_callback, pattern=vars_handlers.RM_VAR_CALLBACK_PATTERN
        )
    )

    application.add_handler(CommandHandler("pin", pin.pin))
    application.add_handler(CommandHandler("unpin", pin.unpin))

    application.add_handler(
        MessageHandler(
            filters.PHOTO & filters.CaptionRegex(photo.PHOTO_CAPTION_PATTERN),
            photo.set_photo_from_caption,
        )
    )

    if config.FUN_COMMANDS_ENABLED:
        application.add_handler(CommandHandler("paro", fun.paro))
        application.add_handler(CommandHandler("toma", fun.toma))
        logger.info("Fun commands plugin enabled")

    application.job_queue.run_repeating(
        jobs.refresh_titles, interval=config.TITLE_REFRESH_INTERVAL_SECONDS, first=0
    )

    return application


def main() -> None:
    init_db()
    application = build_application()
    logger.info("Starting RedPanditaBot")
    application.run_polling()


if __name__ == "__main__":
    main()
