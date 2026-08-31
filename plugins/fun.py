from telegram import Update
from telegram.ext import ContextTypes

PARO_MESSAGE = (
    "🚩 ¡Se decreta paro indefinido! Nadie entra hasta la próxima asamblea."
)
TOMA_MESSAGE = "🏴 ¡Toma declarada! El chat ahora pertenece a la asamblea."


async def paro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(PARO_MESSAGE)


async def toma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(TOMA_MESSAGE)
