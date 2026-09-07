import re
from calendar import monthrange
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

# Units that denote a whole day or more. When the stored value carries no
# time, these count between calendar dates so they flip at midnight; the
# finer units still need an instant, and use midnight of that date.
DAY_OR_COARSER = ("years", "months", "weeks", "days")

INVALID_DATE_HINT = (
    "Formatos aceptados: DD/MM/YYYY, DD-MM-YYYY, DDMMYYYY, "
    "opcionalmente seguido de HH:MM o HH:MM:SS."
)

DATE_KINDS = ("years", "months", "weeks", "days", "hours", "minutes", "seconds")

# A variable name and the {name}(arg) token that reads it back share one
# character class, so a name that can't be written as a token is rejected at
# creation time instead of quietly never rendering.
NAME_PATTERN = r"[a-zA-Z_][a-zA-Z0-9_]*"
NAME_RE = re.compile(NAME_PATTERN)
TOKEN_RE = re.compile(r"\{(" + NAME_PATTERN + r")\}(?:\(([^)]*)\))?")

INVALID_NAME_HINT = (
    "Debe empezar con una letra (a-z, sin tildes) o guion bajo, "
    "y seguir con letras, números o guiones bajos."
)


class TemplateError(Exception):
    """Raised when a template can't be rendered: unknown variable, bad
    argument, circular fragment reference, etc."""


def parse_date_input(value: str) -> tuple[datetime, bool] | None:
    """The parsed date plus whether the input carried no time of day (in
    which case strptime defaulted it to midnight)."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt), "%H" not in fmt
        except ValueError:
            continue
    return None


def parse_date_value(value: str) -> datetime | None:
    parsed = parse_date_input(value)
    return None if parsed is None else parsed[0]


def is_valid_variable_name(name: str) -> bool:
    return NAME_RE.fullmatch(name) is not None


def invalid_name_message(name: str) -> str:
    return f"Nombre inválido '{name}'. {INVALID_NAME_HINT}"


def invalid_date_message(value: str) -> str:
    return f"Fecha inválida '{value}'. {INVALID_DATE_HINT}"


# Every date variable answers the same question: how many whole periods of
# this unit separate the date from now. Direction doesn't matter (a past date
# and a future one the same distance away render the same number), and a unit
# only reaches 1 once a full period has actually passed, counted from the
# date's own time of day -- or from midnight when the value carries no time,
# so "01/01/2000" ticks at midnight in both directions.


def _shift_months(date: datetime, months: int) -> datetime:
    """`date` moved by `months` calendar months, clamping the day to the end
    of the target month (31/01 + 1 month -> 28/02, or 29/02 on a leap year)."""
    total = date.month - 1 + months
    year = date.year + total // 12
    month = total % 12 + 1
    day = min(date.day, monthrange(year, month)[1])
    return date.replace(year=year, month=month, day=day)


def _elapsed_months(date: datetime, now: datetime) -> int:
    if date > now:
        date, now = now, date
    months = (now.year - date.year) * 12 + (now.month - date.month)
    if _shift_months(date, months) > now:
        months -= 1
    return months


def _elapsed_by_seconds(seconds_per_unit: int) -> Callable[[datetime, datetime], int]:
    return lambda date, now: int(abs(now - date).total_seconds()) // seconds_per_unit


_ELAPSED_FUNCS: dict[str, Callable[[datetime, datetime], int]] = {
    "years": lambda date, now: _elapsed_months(date, now) // 12,
    "months": _elapsed_months,
    "weeks": _elapsed_by_seconds(7 * 86400),
    "days": _elapsed_by_seconds(86400),
    "hours": _elapsed_by_seconds(3600),
    "minutes": _elapsed_by_seconds(60),
    "seconds": _elapsed_by_seconds(1),
}


def elapsed(unit: str, date: datetime, now: datetime, date_only: bool) -> int:
    if date_only and unit in DAY_OR_COARSER:
        # `date` is already midnight; anchoring `now` there too makes the
        # count a difference of calendar dates, which is what a value with
        # no time of day means -- and what makes it flip at midnight even
        # when the date is in the future.
        now = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _ELAPSED_FUNCS[unit](date, now)


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
        if parse_date_input(raw) is None:
            raise ValueError(invalid_date_message(raw))
        return raw

    def render(value: str, arg: str | None) -> str:
        parsed = parse_date_input(value)
        if parsed is None:
            raise TemplateError(invalid_date_message(value))
        date, date_only = parsed
        offset = _parse_offset(arg)
        count = elapsed(unit, date, datetime.now(), date_only) + offset
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
