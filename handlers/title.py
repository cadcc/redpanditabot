import logging

from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session as SessionType

from db import Session, get_or_create_chat
from models import Chat, Variable
from permissions import admin_only, group_only
from templating import TemplateError, interpolate, interpolate_with_spans

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
    "El template fue truncado o modificado por Telegram al aplicarlo; "
    "Telegram dejó el título como: {actual}. El template configurado no "
    "cambió, así que se reintentará en la próxima actualización."
)
ADJUSTED_MESSAGE_TEMPLATE = (
    "Telegram modificó el título al aplicarlo, dejándolo como: {actual}. "
    "Se ajustó la variable de texto correspondiente para que coincida, "
    "así que el título no debería volver a cambiar solo."
)


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _common_suffix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[-1 - i] == b[-1 - i]:
        i += 1
    return i


def _adjust_truncated_variable(
    session: SessionType, chat: Chat, requested_title: str, actual_title: str
) -> bool:
    """If Telegram rendered requested_title differently (truncated it,
    dropped/altered characters at the edges of a token, etc.) and the whole
    differing region falls inside a single {name} token backed by a 'text'
    variable, rewrite that variable's stored value so it already matches
    what Telegram actually shows. This keeps the template itself untouched
    but makes the next render already match Telegram's output, instead of
    re-detecting the same mismatch (and re-alerting) forever. Returns True
    if a variable was adjusted."""
    if chat.chat_title is None or requested_title == actual_title:
        return False

    prefix = _common_prefix_len(requested_title, actual_title)
    suffix = _common_suffix_len(requested_title[prefix:], actual_title[prefix:])
    diff_start = prefix
    diff_end = len(requested_title) - suffix

    try:
        _, spans = interpolate_with_spans(session, chat, template=chat.chat_title)
    except TemplateError:
        return False

    for span in spans:
        if span.start <= diff_start and diff_end <= span.end:
            variable = session.get(Variable, span.variable_id)
            if variable is None:
                break
            replacement = actual_title[prefix : len(actual_title) - suffix]
            local_start = diff_start - span.start
            local_end = diff_end - span.start
            variable.value = (
                variable.value[:local_start] + replacement + variable.value[local_end:]
            )
            return True
    return False


async def verify_applied_title(
    bot: Bot, session: SessionType, chat: Chat, requested_title: str
) -> str | None:
    """Re-fetch the live chat title and compare it to what was just sent
    via setChatTitle. If Telegram truncated/altered it, sync
    last_applied_title to the live title and return a notification message
    to post to the chat. Returns None if they match.

    Never overwrites the stored template (chat.chat_title): that must stay
    exactly what the admin configured with /set_title, unresolved
    {variable} tokens included, regardless of what Telegram does with the
    rendered text it's given. When the whole mismatch falls inside a
    'text' variable's rendered output, that variable's value is rewritten
    to match instead, so future renders stay in sync with what Telegram
    actually shows.
    """
    live_chat = await bot.get_chat(chat.id)
    actual_title = live_chat.title
    if actual_title == requested_title:
        chat.last_applied_title = requested_title
        session.commit()
        return None
    chat.last_applied_title = actual_title
    adjusted = _adjust_truncated_variable(session, chat, requested_title, actual_title)
    session.commit()
    if adjusted:
        return ADJUSTED_MESSAGE_TEMPLATE.format(actual=actual_title)
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
