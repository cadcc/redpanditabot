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
    if date > now:
        date, now = now, date
    years = now.year - date.year
    if (now.month, now.day) < (date.month, date.day):
        years -= 1
    return years


def _elapsed_months(date: datetime, now: datetime) -> int:
    if date > now:
        date, now = now, date
    months = (now.year - date.year) * 12 + (now.month - date.month)
    if now.day < date.day:
        months -= 1
    return months


_ELAPSED_FUNCS: dict[str, Callable[[datetime, datetime], int]] = {
    "years": _elapsed_years,
    "months": _elapsed_months,
    "weeks": lambda date, now: abs(now - date).days // 7,
    "days": lambda date, now: abs(now - date).days,
    "hours": lambda date, now: int(abs(now - date).total_seconds() // 3600),
    "minutes": lambda date, now: int(abs(now - date).total_seconds() // 60),
    "seconds": lambda date, now: int(abs(now - date).total_seconds()),
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


@dataclass(frozen=True)
class TextSpan:
    """The rendered-string offsets [start, end) produced by a single {name}
    token backed by a 'text' variable, plus that variable's id. Only 'text'
    variables get a span: their rendered output equals their stored value
    verbatim, so a position in the rendered string maps back to an editable
    slice of the variable."""

    start: int
    end: int
    variable_id: int


def _render_recursive_with_spans(
    session: Session, chat_id: int, name: str, arg: str | None, seen: frozenset[str],
    offset: int,
) -> tuple[str, list[TextSpan]]:
    separator = arg if arg is not None else ""
    new_seen = seen | {name}
    parts = []
    spans: list[TextSpan] = []
    cur_offset = offset
    for i, row in enumerate(resolve_variables_by_name(session, chat_id, name)):
        if i > 0:
            cur_offset += len(separator)
        if row.type == "recursive":
            rendered, sub_spans = _interpolate_string_with_spans(
                session, chat_id, row.value, new_seen, cur_offset
            )
        else:
            kind = VARIABLE_KINDS.get(row.type)
            if kind is None:
                raise TemplateError(f"Tipo de variable desconocido: '{row.type}'.")
            rendered = kind.render(row.value, None)
            sub_spans = (
                [TextSpan(cur_offset, cur_offset + len(rendered), row.id)]
                if row.type == "text"
                else []
            )
        parts.append(rendered)
        spans.extend(sub_spans)
        cur_offset += len(rendered)
    return separator.join(parts), spans


def _render_name_with_spans(
    session: Session, chat_id: int, name: str, arg: str | None, seen: frozenset[str],
    offset: int,
) -> tuple[str, list[TextSpan]]:
    if name in seen:
        raise TemplateError(f"Referencia circular detectada en la variable '{name}'.")

    variable = resolve_variable(session, chat_id, name)
    if variable is None:
        raise TemplateError(f"La variable '{name}' no existe.")

    if variable.type == "recursive":
        return _render_recursive_with_spans(session, chat_id, name, arg, seen, offset)

    kind = VARIABLE_KINDS.get(variable.type)
    if kind is None:
        raise TemplateError(f"Tipo de variable desconocido: '{variable.type}'.")
    rendered = kind.render(variable.value, arg)
    if variable.type == "text":
        return rendered, [TextSpan(offset, offset + len(rendered), variable.id)]
    return rendered, []


def _interpolate_string_with_spans(
    session: Session, chat_id: int, template: str, seen: frozenset[str], offset: int = 0
) -> tuple[str, list[TextSpan]]:
    parts = []
    spans: list[TextSpan] = []
    pos = 0
    cur_offset = offset
    for match in TOKEN_RE.finditer(template):
        literal = template[pos:match.start()]
        parts.append(literal)
        cur_offset += len(literal)
        name, arg = match.group(1), match.group(2)
        rendered, sub_spans = _render_name_with_spans(
            session, chat_id, name, arg, seen, cur_offset
        )
        parts.append(rendered)
        spans.extend(sub_spans)
        cur_offset += len(rendered)
        pos = match.end()
    parts.append(template[pos:])
    return "".join(parts), spans


def interpolate_with_spans(
    session: Session, chat, template: str | None = None
) -> tuple[str, list[TextSpan]]:
    """Like interpolate(), but also returns a TextSpan per {name} token
    backed by a 'text' variable, giving the offsets that token's rendered
    output occupies in the returned string."""
    tmpl = chat.chat_title if template is None else template
    if tmpl is None:
        raise TemplateError("No hay un template configurado para este grupo.")
    return _interpolate_string_with_spans(session, chat.id, tmpl, frozenset())


def interpolate(session: Session, chat, template: str | None = None) -> str:
    """Render a chat's title template. Pass `template` explicitly to
    validate/preview a candidate template before it's stored on `chat`."""
    rendered, _ = interpolate_with_spans(session, chat, template=template)
    return rendered
