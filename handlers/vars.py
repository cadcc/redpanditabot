import logging

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import Session, get_or_create_chat
from models import Chat, Variable
from permissions import admin_only, group_only
from templating import (
    DATE_KINDS,
    VARIABLE_KINDS,
    invalid_name_message,
    is_valid_variable_name,
)

logger = logging.getLogger(__name__)

KIND_COMMANDS = {
    "text": "text",
    "years": "year",
    "months": "month",
    "weeks": "week",
    "days": "day",
    "hours": "hour",
    "minutes": "minute",
    "seconds": "second",
    "recursive": "fragment",
}

RM_VAR_USAGE = "Uso: /rm_var <id> | /rm_var <nombre> | /rm_var all_fragments"


def _usage_for(kind: str) -> str:
    cmd = KIND_COMMANDS[kind]
    if kind == "text":
        return f"Uso: /{cmd} <nombre> <valor...>"
    if kind == "recursive":
        return f"Uso: /{cmd} <nombre> <template...>"
    return f"Uso: /{cmd} <nombre> <fecha>"


def _store_variable(session, chat: Chat, name: str, kind: str, raw_value: str) -> Variable:
    """Parses raw_value with the kind's validator (raises ValueError on bad
    input) and stores it. Non-recursive kinds replace any existing
    variable(s) sharing this name; recursive/fragment vars always accumulate."""
    parsed_value = VARIABLE_KINDS[kind].parse(raw_value)

    if kind != "recursive":
        session.execute(
            delete(Variable).where(Variable.chat_id == chat.id, Variable.name == name)
        )

    variable = Variable(chat_id=chat.id, name=name, type=kind, value=parsed_value)
    session.add(variable)
    session.commit()
    return variable


async def add_var(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text(_usage_for(kind))
        return

    name = context.args[0]
    raw_value = " ".join(context.args[1:])

    if not is_valid_variable_name(name):
        await update.effective_message.reply_text(invalid_name_message(name))
        return

    with Session() as session:
        chat = get_or_create_chat(
            session, update.effective_chat.id, update.effective_chat.type
        )
        try:
            _store_variable(session, chat, name, kind, raw_value)
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return

    if kind == "recursive":
        await update.effective_message.reply_text(f"Fragment '{name}' agregado.")
    elif kind in DATE_KINDS:
        # Date variables confirm with the number they render right now.
        current = VARIABLE_KINDS[kind].render(raw_value, None)
        await update.effective_message.reply_text(
            f"Variable '{name}' ({kind}) guardada. Valor actual: {current} {kind}"
        )
    else:
        await update.effective_message.reply_text(
            f"Variable '{name}' ({kind}) guardada."
        )


def _make_add_var_handler(kind: str):
    @admin_only
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await add_var(update, context, kind)

    return handler


text = _make_add_var_handler("text")
year = _make_add_var_handler("years")
month = _make_add_var_handler("months")
week = _make_add_var_handler("weeks")
day = _make_add_var_handler("days")
hour = _make_add_var_handler("hours")
minute = _make_add_var_handler("minutes")
second = _make_add_var_handler("seconds")
fragment = _make_add_var_handler("recursive")


@group_only
async def list_vars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name_filter = context.args[0] if context.args else None

    with Session() as session:
        chat = get_or_create_chat(
            session, update.effective_chat.id, update.effective_chat.type
        )
        query = select(Variable).where(Variable.chat_id == chat.id)
        if name_filter:
            query = query.where(Variable.name == name_filter)
        query = query.order_by(Variable.name, Variable.created_at)
        rows = list(session.scalars(query))

    if not rows:
        if name_filter:
            await update.effective_message.reply_text(
                f"No hay variables con el nombre '{name_filter}'."
            )
        else:
            await update.effective_message.reply_text("Este grupo no tiene variables.")
        return

    lines = [f"#{row.id} [{row.type}] {row.name} = {row.value}" for row in rows]
    await update.effective_message.reply_text("\n".join(lines))


def parse_rm_var_target(args: list[str]) -> tuple[str, int | str | None]:
    """The target as (kind, value). Ids and names can't be confused: a name
    never starts with a digit. "all_fragments" stays the reserved wipe token,
    so a variable actually named that has to be removed by id."""
    if len(args) != 1:
        raise ValueError(RM_VAR_USAGE)
    token = args[0]
    if token == "all_fragments":
        return ("all_fragments", None)
    if token.lstrip("-").isdigit():
        return ("id", int(token))
    if is_valid_variable_name(token):
        return ("name", token)
    raise ValueError(RM_VAR_USAGE)


@admin_only
async def rm_var(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        target_type, target = parse_rm_var_target(context.args)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    with Session() as session:
        chat = get_or_create_chat(
            session, update.effective_chat.id, update.effective_chat.type
        )

        if target_type == "id":
            variable = session.get(Variable, target)
            if variable is None or variable.chat_id != chat.id:
                await update.effective_message.reply_text(
                    f"No existe una variable con id {target} en este grupo."
                )
                return
            name = variable.name
            session.delete(variable)
            session.commit()
            await update.effective_message.reply_text(
                f"Variable #{target} ('{name}') eliminada."
            )
            return

        if target_type == "name":
            # A name can hold several rows (fragments accumulate), so this
            # removes every one of them.
            result = session.execute(
                delete(Variable).where(
                    Variable.chat_id == chat.id, Variable.name == target
                )
            )
            session.commit()
            deleted = result.rowcount
            if not deleted:
                await update.effective_message.reply_text(
                    f"No existe una variable con el nombre '{target}' en este grupo."
                )
            elif deleted == 1:
                await update.effective_message.reply_text(
                    f"Variable '{target}' eliminada."
                )
            else:
                await update.effective_message.reply_text(
                    f"Se eliminaron {deleted} variables con el nombre '{target}'."
                )
            return

        count = session.scalar(
            select(func.count())
            .select_from(Variable)
            .where(Variable.chat_id == chat.id, Variable.type == "recursive")
        )
        if not count:
            await update.effective_message.reply_text("No hay fragments para eliminar.")
            return

        requester_id = update.effective_user.id
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Sí", callback_data=f"rmvar_confirm:{chat.id}:{requester_id}"
                    ),
                    InlineKeyboardButton(
                        "No", callback_data=f"rmvar_cancel:{chat.id}:{requester_id}"
                    ),
                ]
            ]
        )
        await update.effective_message.reply_text(
            f"¿Seguro que quieres borrar todos los fragments ({count})? Sí / No",
            reply_markup=keyboard,
        )


RM_VAR_CALLBACK_PATTERN = r"^rmvar_(confirm|cancel):(-?\d+):(-?\d+)$"


async def rm_var_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, chat_id_str, requester_id_str = query.data.split(":")
    chat_id, requester_id = int(chat_id_str), int(requester_id_str)

    if query.from_user.id != requester_id:
        await query.answer(
            "Solo quien pidió el borrado puede confirmar.", show_alert=True
        )
        return

    await query.answer()

    if action == "rmvar_cancel":
        await query.edit_message_text("Cancelado, no se eliminó nada.")
        return

    with Session() as session:
        result = session.execute(
            delete(Variable).where(Variable.chat_id == chat_id, Variable.type == "recursive")
        )
        session.commit()
        deleted = result.rowcount

    await query.edit_message_text(f"Se eliminaron {deleted} fragments.")
