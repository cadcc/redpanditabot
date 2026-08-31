import logging

from sqlalchemy import select
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from db import Session
from handlers.title import verify_applied_title
from models import Chat
from templating import TemplateError, interpolate

logger = logging.getLogger(__name__)


async def refresh_titles(context: ContextTypes.DEFAULT_TYPE) -> None:
    with Session() as session:
        chats = list(
            session.scalars(select(Chat).where(Chat.type.in_(("group", "supergroup"))))
        )
        for chat in chats:
            if not chat.chat_title:
                continue

            try:
                new_title = interpolate(session, chat)
            except TemplateError:
                logger.exception("Failed to interpolate title for chat %s", chat.id)
                continue

            if new_title == chat.last_applied_title:
                continue

            try:
                await context.bot.set_chat_title(chat.id, new_title)
            except TelegramError:
                logger.exception("Failed to update title for chat %s", chat.id)
                continue

            mismatch_message = await verify_applied_title(
                context.bot, session, chat, new_title
            )
            if mismatch_message:
                try:
                    await context.bot.send_message(chat.id, mismatch_message)
                except TelegramError:
                    logger.exception(
                        "Failed to notify chat %s about title mismatch", chat.id
                    )
