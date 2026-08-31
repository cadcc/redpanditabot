import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from permissions import admin_only

logger = logging.getLogger(__name__)

PIN_NO_REPLY_MESSAGE = "Responde al mensaje que quieres fijar con /pin."
PIN_ERROR_MESSAGE = (
    "No pude fijar el mensaje. ¿Soy administrador con permiso para fijar mensajes?"
)
UNPIN_ERROR_MESSAGE = (
    "No pude desfijar el mensaje. ¿Soy administrador con permiso para fijar mensajes?"
)


@admin_only
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.effective_message.reply_to_message
    if replied is None:
        await update.effective_message.reply_text(PIN_NO_REPLY_MESSAGE)
        return

    urgent = len(context.args) > 0 and context.args[0] == "!"

    try:
        await context.bot.pin_chat_message(
            update.effective_chat.id, replied.message_id, disable_notification=not urgent
        )
    except TelegramError:
        logger.exception("Failed to pin message in chat %s", update.effective_chat.id)
        await update.effective_message.reply_text(PIN_ERROR_MESSAGE)
        return

    await update.effective_message.reply_text(
        "Mensaje fijado" + (" (con notificación)." if urgent else ".")
    )


@admin_only
async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
    except TelegramError:
        logger.exception("Failed to unpin message in chat %s", update.effective_chat.id)
        await update.effective_message.reply_text(UNPIN_ERROR_MESSAGE)
        return

    await update.effective_message.reply_text("Mensaje desfijado.")
