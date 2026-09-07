import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

START_MESSAGE = (
    "¡Hola! Soy RedPanditaBot 🐼\n\n"
    "Mantengo el título de tu grupo actualizado automáticamente a partir de "
    "un template con variables de fecha y texto (por ejemplo, \"3 años "
    "desde X\" o \"faltan 12 semanas para Y\").\n\n"
    "Agrégame a un grupo, hazme administrador (necesito poder cambiar el "
    "título y la foto del grupo) y usa /help para ver todos los comandos."
)

HELP_MESSAGE = (
    "<b>Comandos generales</b>\n"
    "/start - Mensaje de bienvenida\n"
    "/help - Este mensaje\n"
    "/ping - Verifica que el bot esté funcionando\n\n"
    "<b>Título del grupo</b>\n"
    "/get_title (o /title) - Muestra el template configurado (no el título "
    "ya interpolado, que ya se ve en el chat)\n"
    "/set_title &lt;texto&gt; - Define el template del título y lo aplica de inmediato\n\n"
    "<b>Variables</b>\n"
    "/text &lt;nombre&gt; &lt;valor...&gt; - Texto literal\n"
    "/year &lt;nombre&gt; &lt;fecha&gt; - Años completos respecto a una fecha\n"
    "/month &lt;nombre&gt; &lt;fecha&gt; - Meses completos\n"
    "/week &lt;nombre&gt; &lt;fecha&gt; - Semanas completas\n"
    "/day &lt;nombre&gt; &lt;fecha&gt; - Días completos\n"
    "/hour &lt;nombre&gt; &lt;fecha&gt; - Horas completas\n"
    "/minute &lt;nombre&gt; &lt;fecha&gt; - Minutos completos\n"
    "/second &lt;nombre&gt; &lt;fecha&gt; - Segundos completos\n"
    "/fragment &lt;nombre&gt; &lt;template...&gt; - Agrega un fragmento combinable "
    "(no reemplaza los anteriores con el mismo nombre, se acumulan)\n"
    "/list_vars [nombre] - Lista las variables del grupo\n"
    "/rm_var (id | nombre | all_fragments) - Elimina una variable por id, "
    "todas las que compartan un nombre, o todos los fragments del grupo "
    "(pide confirmación)\n\n"
    "<b>Fechas aceptadas</b>: DD/MM/YYYY, DD-MM-YYYY, DDMMYYYY, opcionalmente "
    "seguidas de HH:MM o HH:MM:SS.\n\n"
    "<b>Cómo se cuentan las fechas</b>\n"
    "Todas las unidades siguen la misma regla: cuentan los períodos "
    "<i>completos</i> que separan la fecha del momento actual.\n"
    "• 0 significa que aún no pasa un período entero: un /year marca 0 hasta "
    "el aniversario, no hasta el 1 de enero.\n"
    "• La dirección no importa: una fecha futura cuenta igual que una pasada, "
    "así que la misma variable sirve como cuenta regresiva.\n"
    "• Si la fecha no incluye hora, se cuentan días completos de calendario: "
    "/day, /week, /month y /year cambian a medianoche, hacia el pasado y "
    "hacia el futuro.\n"
    "• Si la fecha incluye hora, el número avanza a esa hora: con "
    "07/09/2025 12:00, el /year marca 1 recién a las 12:00 del "
    "07/09/2026.\n"
    "• /hour, /minute y /second siempre cuentan tiempo real; si la fecha no "
    "trae hora, cuentan desde su medianoche.\n\n"
    "<b>Otros</b>\n"
    "/pin [!] - Fija el mensaje respondido (usa \"!\" para notificar)\n"
    "/unpin - Desfija el mensaje actualmente fijado\n"
    "Envía una foto con el caption exactamente \"/photo\" para usarla como "
    "foto del grupo.\n\n"
    "<b>Sintaxis de templates</b>\n"
    "En /set_title y en los fragments de /fragment puedes usar:\n"
    "• <code>{nombre}</code> - el valor de la variable, tal cual\n"
    "• <code>{nombre}(arg)</code> - el valor, con un argumento extra:\n"
    "  - para variables de fecha (year/month/week/day/hour/minute/second), "
    "arg es un offset entero que se suma a la cuenta calculada, ej. "
    "<code>{dias}(5)</code> muestra los días completos más 5\n"
    "  - para variables de /fragment, arg es el separador usado para unir "
    "todos los fragments que comparten ese nombre, ej. "
    "<code>{saludo}(, )</code>\n\n"
    "<b>Regla de resolución de nombres</b>: si varias variables comparten un "
    "nombre, <code>{nombre}</code> sin argumento usa la más reciente. Esto "
    "solo importa en la práctica para los fragments, ya que crear una "
    "variable de cualquier otro tipo reemplaza a la anterior con el mismo "
    "nombre en vez de agregar una nueva.\n\n"
    "Todos los comandos que modifican algo requieren ser administrador del "
    "grupo."
)

PING_MESSAGE = "¡Buena Onda! 🐼"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(START_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(HELP_MESSAGE)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(PING_MESSAGE)
