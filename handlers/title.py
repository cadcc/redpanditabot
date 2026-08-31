import logging

from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session as SessionType

from db import Session, get_or_create_chat
from models import Chat
from permissions import admin_only, group_only
from templating import TemplateError, interpolate

logger = logging.getLogger(__name__)

NO_TEMPLATE_MESSAGE = (
    "Este grupo no tiene un template de título configurado. Usa /set_title "
    "para definir uno."
)
SET_TITLE_USAGE = "Uso: /set_title <texto del template>"
SET_TITLE_APPLY_ERROR = (
    "No pude aplicar el título. ¿Soy administrador del grupo con permiso "
    "para cambiar el título?"
)
SET_TITLE_SUCCESS = "Listo, el título del grupo quedó en: {title}"
MISMATCH_MESSAGE_TEMPLATE = (
    "El template fue truncado o modificado por Telegram al aplicarlo; el "
    "template quedó ajustado a lo que Telegram realmente puso como título: "
    "{actual}. Usa /set_title para definir uno nuevo."
)


async def verify_applied_title(
    bot: Bot, session: SessionType, chat: Chat, requested_title: str
) -> str | None:
    """Re-fetch the live chat title and compare it to what was just sent
    via setChatTitle. If Telegram truncated/altered it, sync the stored
    template + last_applied_title to the live title and return a
    notification message to post to the chat. Returns None if they match."""
    live_chat = await bot.get_chat(chat.id)
    actual_title = live_chat.title
    if actual_title == requested_title:
        chat.last_applied_title = requested_title
        session.commit()
        return None
    chat.chat_title = actual_title
    chat.last_applied_title = actual_title
    session.commit()
    return MISMATCH_MESSAGE_TEMPLATE.format(actual=actual_title)


@group_only
async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with Session() as session:
        chat = get_or_create_chat(
            session, update.effective_chat.id, update.effective_chat.type
        )
        if not chat.chat_title:
            await update.effective_message.reply_text(NO_TEMPLATE_MESSAGE)
            return
        await update.effective_message.reply_text(chat.chat_title)


@admin_only
async def set_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(SET_TITLE_USAGE)
        return

    new_template = " ".join(context.args)

    with Session() as session:
        chat = get_or_create_chat(
            session, update.effective_chat.id, update.effective_chat.type
        )

        try:
            rendered = interpolate(session, chat, template=new_template)
        except TemplateError as exc:
            await update.effective_message.reply_text(f"Template inválido: {exc}")
            return

        try:
            await context.bot.set_chat_title(chat.id, rendered)
        except TelegramError:
            logger.exception("Failed to set chat title for chat %s", chat.id)
            await update.effective_message.reply_text(SET_TITLE_APPLY_ERROR)
            return

        chat.chat_title = new_template
        chat.last_applied_title = rendered
        session.commit()

        mismatch_message = await verify_applied_title(context.bot, session, chat, rendered)
        if mismatch_message:
            await update.effective_message.reply_text(mismatch_message)
        else:
            await update.effective_message.reply_text(
                SET_TITLE_SUCCESS.format(title=rendered)
            )
