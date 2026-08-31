import logging
from functools import wraps

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

ADMIN_STATUSES = ("administrator", "creator")

GROUP_ONLY_MESSAGE = (
    "Este comando solo funciona en grupos o supergrupos."
)
ADMIN_ONLY_MESSAGE = "Solo los administradores del grupo pueden hacer eso."


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    if member.status not in ADMIN_STATUSES:
        await update.effective_message.reply_text(
            ADMIN_ONLY_MESSAGE, parse_mode=ParseMode.HTML
        )
        return False
    return True


def require_group_chat(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    )


def group_only(handler):
    """Decorator: politely refuse private chats and channels."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not require_group_chat(update):
            await update.effective_message.reply_text(GROUP_ONLY_MESSAGE)
            return
        return await handler(update, context)

    return wrapper


def admin_only(handler):
    """Decorator: require group chat + admin caller. Combine with
    @group_only or use directly since it also enforces the group check."""

    @wraps(handler)
    @group_only
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await require_admin(update, context):
            return
        return await handler(update, context)

    return wrapper
