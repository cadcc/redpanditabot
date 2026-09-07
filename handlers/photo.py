import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from permissions import admin_only

logger = logging.getLogger(__name__)

PHOTO_CAPTION_PATTERN = r"^/photo"
PHOTO_ERROR_MESSAGE = (
    "No pude cambiar la foto del grupo. ¿Soy administrador con permiso para "
    "cambiar la foto?"
)


@admin_only
async def set_photo_from_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    largest_photo = update.effective_message.photo[-1]

    try:
        file = await context.bot.get_file(largest_photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        await context.bot.set_chat_photo(update.effective_chat.id, photo=bytes(photo_bytes))
    except TelegramError:
        logger.exception("Failed to set chat photo for chat %s", update.effective_chat.id)
        await update.effective_message.reply_text(PHOTO_ERROR_MESSAGE)
        return

    await update.effective_message.reply_text("Foto del grupo actualizada.")
