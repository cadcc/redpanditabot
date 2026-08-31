import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Variable

DATE_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d%m%Y",
]

INVALID_DATE_HINT = (
    "Formatos aceptados: DD/MM/YYYY, DD-MM-YYYY, DDMMYYYY, "
    "opcionalmente seguido de HH:MM o HH:MM:SS."
)

DATE_KINDS = ("years", "months", "weeks", "days", "hours", "minutes", "seconds")

TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?:\(([^)]*)\))?")


class TemplateError(Exception):
    """Raised when a template can't be rendered: unknown variable, bad
    argument, circular fragment reference, etc."""


def parse_date_value(value: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def invalid_date_message(value: str) -> str:
    return f"Fecha inválida '{value}'. {INVALID_DATE_HINT}"


def _elapsed_years(date: datetime, now: datetime) -> int:
    years = now.year - date.year
    if (now.month, now.day) < (date.month, date.day):
        years -= 1
    return years


def _elapsed_months(date: datetime, now: datetime) -> int:
    months = (now.year - date.year) * 12 + (now.month - date.month)
    if now.day < date.day:
        months -= 1
    return months


_ELAPSED_FUNCS: dict[str, Callable[[datetime, datetime], int]] = {
    "years": _elapsed_years,
    "months": _elapsed_months,
    "weeks": lambda date, now: (now - date).days // 7,
    "days": lambda date, now: (now - date).days,
    "hours": lambda date, now: int((now - date).total_seconds() // 3600),
    "minutes": lambda date, now: int((now - date).total_seconds() // 60),
    "seconds": lambda date, now: int((now - date).total_seconds()),
}


def _parse_offset(arg: str | None) -> int:
    if arg is None:
        return 0
    try:
        return int(arg.strip())
    except ValueError:
        raise TemplateError(
            f"El argumento '{arg}' debe ser un número entero (offset)."
        ) from None


def _make_date_kind(unit: str) -> "VariableKind":
    def parse(raw: str) -> str:
        if parse_date_value(raw) is None:
            raise ValueError(invalid_date_message(raw))
        return raw

    def render(value: str, arg: str | None) -> str:
        date = parse_date_value(value)
        if date is None:
            raise TemplateError(invalid_date_message(value))
        offset = _parse_offset(arg)
        count = _ELAPSED_FUNCS[unit](date, datetime.now()) + offset
        return str(count)

    return VariableKind(parse=parse, render=render)


def _text_parse(raw: str) -> str:
    return raw


def _text_render(value: str, arg: str | None) -> str:
    if arg is not None:
        raise TemplateError(
            "La variable de tipo 'text' no acepta argumentos: usa solo {name}."
        )
    return value


def _recursive_parse(raw: str) -> str:
    return raw


def _recursive_render(value: str, arg: str | None) -> str:
    # Recursive/fragment variables are never rendered through this function
    # directly: interpolate() special-cases type "recursive" to join every
    # row sharing a name and re-interpolate each fragment. This entry exists
    # only so VARIABLE_KINDS stays the single source of truth for valid types.
    raise TemplateError("Las variables 'recursive' no se renderizan individualmente.")


@dataclass(frozen=True)
class VariableKind:
    parse: Callable[[str], str]
    render: Callable[[str, str | None], str]


VARIABLE_KINDS: dict[str, VariableKind] = {
    "text": VariableKind(parse=_text_parse, render=_text_render),
    "recursive": VariableKind(parse=_recursive_parse, render=_recursive_render),
    **{unit: _make_date_kind(unit) for unit in DATE_KINDS},
}


def resolve_variable(session: Session, chat_id: int, name: str) -> Variable | None:
    return session.scalars(
        select(Variable)
        .where(Variable.chat_id == chat_id, Variable.name == name)
        .order_by(Variable.created_at.desc())
        .limit(1)
    ).first()


def resolve_variables_by_name(session: Session, chat_id: int, name: str) -> list[Variable]:
    return list(
        session.scalars(
            select(Variable)
            .where(Variable.chat_id == chat_id, Variable.name == name)
            .order_by(Variable.created_at.asc())
        )
    )


def _render_recursive(
    session: Session, chat_id: int, name: str, arg: str | None, seen: frozenset[str]
) -> str:
    separator = arg if arg is not None else ""
    new_seen = seen | {name}
    parts = []
    for row in resolve_variables_by_name(session, chat_id, name):
        if row.type == "recursive":
            parts.append(_interpolate_string(session, chat_id, row.value, new_seen))
        else:
            kind = VARIABLE_KINDS.get(row.type)
            if kind is None:
                raise TemplateError(f"Tipo de variable desconocido: '{row.type}'.")
            parts.append(kind.render(row.value, None))
    return separator.join(parts)


def _render_name(
    session: Session, chat_id: int, name: str, arg: str | None, seen: frozenset[str]
) -> str:
    if name in seen:
        raise TemplateError(f"Referencia circular detectada en la variable '{name}'.")

    variable = resolve_variable(session, chat_id, name)
    if variable is None:
        raise TemplateError(f"La variable '{name}' no existe.")

    if variable.type == "recursive":
        return _render_recursive(session, chat_id, name, arg, seen)

    kind = VARIABLE_KINDS.get(variable.type)
    if kind is None:
        raise TemplateError(f"Tipo de variable desconocido: '{variable.type}'.")
    return kind.render(variable.value, arg)


def _interpolate_string(
    session: Session, chat_id: int, template: str, seen: frozenset[str]
) -> str:
    def replace(match: re.Match) -> str:
        name, arg = match.group(1), match.group(2)
        return _render_name(session, chat_id, name, arg, seen)

    return TOKEN_RE.sub(replace, template)


def interpolate(session: Session, chat, template: str | None = None) -> str:
    """Render a chat's title template. Pass `template` explicitly to
    validate/preview a candidate template before it's stored on `chat`."""
    tmpl = chat.chat_title if template is None else template
    if tmpl is None:
        raise TemplateError("No hay un template configurado para este grupo.")
    return _interpolate_string(session, chat.id, tmpl, frozenset())
