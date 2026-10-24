"""Datas, tempo relativo, duração e números das telas (como a SPA mostrava, ADR 0011).

O fuso é o da máquina (core/timezone.py). Os textos imitam o `Intl` do navegador no
estilo curto.
"""

from datetime import date, datetime
from math import floor

from chamados.core.timezone import LOCAL_TZ

TIMEZONE = LOCAL_TZ


def format_datetime(locale: str, value: datetime | None) -> str:
    """Data e hora curtas: "17/10/2026, 14:05" ou "10/17/26, 2:05 PM"."""
    if value is None:
        return "—"
    t = value.astimezone(TIMEZONE)
    if locale == "en":
        period = "AM" if t.hour < 12 else "PM"
        return f"{t.month}/{t.day}/{t.year % 100:02d}, {t.hour % 12 or 12}:{t.minute:02d} {period}"
    return t.strftime("%d/%m/%Y, %H:%M")


def format_ago(locale: str, value: datetime, now: datetime) -> str:
    """Há quanto tempo, na maior unidade que couber ("há 3 dias", "há 15 min.")."""
    seconds = max(0.0, (now - value).total_seconds())
    if seconds >= 86_400:
        days = floor(seconds / 86_400)
        if locale == "en":
            return "yesterday" if days == 1 else f"{days} days ago"
        return {1: "ontem", 2: "anteontem"}.get(days, f"há {days} dias")
    if seconds >= 3_600:
        hours = floor(seconds / 3_600)
        return f"{hours} hr. ago" if locale == "en" else f"há {hours} h"
    minutes = floor(seconds / 60)
    if locale == "en":
        return "this minute" if minutes == 0 else f"{minutes} min. ago"
    return "este minuto" if minutes == 0 else f"há {minutes} min."


def format_duration(minutes: int) -> str:
    """Tempo gasto como "1h30", "2h" ou "45min"."""
    h, m = divmod(minutes, 60)
    if not h:
        return f"{m}min"
    return f"{h}h{m:02d}" if m else f"{h}h"


def format_hours(locale: str, minutes: int) -> str:
    """Tempo em horas decimais: "7,5 h", "0,25 h" (vírgula decimal em português)."""
    text = f"{minutes / 60:.2f}".rstrip("0").rstrip(".")
    return f"{text if locale == 'en' else text.replace('.', ',')} h"


def format_date(locale: str, value: date | datetime) -> str:
    """Data com o ano: "05/10/2026" ou "2026-10-05" (um momento, no fuso da máquina)."""
    if isinstance(value, datetime):
        value = value.astimezone(TIMEZONE).date()
    return value.strftime("%d/%m/%Y" if locale == "pt-BR" else "%Y-%m-%d")


def format_elapsed(minutes: int) -> str:
    """Tempo corrido longo (até a conclusão): "3d 4h", "2d", ou como format_duration abaixo de um
    dia."""
    days, rest = divmod(minutes, 24 * 60)
    if not days:
        return format_duration(rest)
    hours = rest // 60
    return f"{days}d {hours}h" if hours else f"{days}d"


def format_percent(locale: str, hundredths: int) -> str:
    """Porcentagem guardada em centésimos de ponto: 1250 → "12,5%", 3300 → "33%"."""
    text = f"{hundredths / 100:.1f}".removesuffix(".0")
    return f"{text if locale == 'en' else text.replace('.', ',')}%"


def format_number(locale: str, value: int) -> str:
    """Inteiro com separador de milhar: "1.234" ou "1,234"."""
    text = f"{value:,}"
    return text if locale == "en" else text.replace(",", ".")


def format_size(locale: str, size: int) -> str:
    """Tamanho de arquivo: "512 B", "1,5 KB", "12 MB" (vírgula decimal em português)."""
    if size < 1024:
        return f"{size} B"
    value, unit = (size / 1024, "KB") if size < 1024 * 1024 else (size / 1024 / 1024, "MB")
    text = f"{value:.1f}".removesuffix(".0")
    return f"{text.replace('.', ',') if locale == 'pt-BR' else text} {unit}"


MONTHS = {
    "pt-BR": [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}  # fmt: skip


def format_month(locale: str, value: date) -> str:
    """Mês e ano: "outubro de 2026" ou "October 2026"."""
    name = MONTHS["en" if locale == "en" else "pt-BR"][value.month - 1]
    return f"{name} {value.year}" if locale == "en" else f"{name} de {value.year}"


def format_day(locale: str, value: date) -> str:
    """Dia e mês curtos, como no eixo dos gráficos: "05/10" ou "10/05"."""
    return f"{value:%m/%d}" if locale == "en" else f"{value:%d/%m}"


def local_parts(value: datetime) -> tuple[str, str]:
    """Data ("2026-10-17") e hora ("14:05") no fuso da máquina, como os campos usam."""
    t = value.astimezone(TIMEZONE)
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def parse_local(date: str, time: str) -> datetime | None:
    """O instante de uma data e hora digitadas no fuso da máquina; inválidas dão None."""
    try:
        return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE)
    except ValueError:
        return None


def parse_duration(text: str) -> int | None:
    """Minutos de um "hh:mm" (vazio dá None). Minutos acima de 59 ou zero dão ValueError."""
    if not text:
        return None
    hours, sep, minutes = text.partition(":")
    if not (sep and len(hours) == len(minutes) == 2 and hours.isdigit() and minutes.isdigit()):
        raise ValueError(text)
    total = int(hours) * 60 + int(minutes)
    if int(minutes) > 59 or total == 0:
        raise ValueError(text)
    return total


# Horários sugeridos no campo de tempo: 20 e 30 min, de 15 em 15 até 3 h, de hora em hora
# até 24 h (como TEMPOS_SUGERIDOS do formato.ts).
SUGGESTED_TIMES = [
    f"{m // 60:02d}:{m % 60:02d}"
    for m in [20, 30, *range(45, 181, 15), *range(4 * 60, 24 * 60 + 1, 60)]
]


# --- documentos dos clientes (como o documentos.ts da SPA; o banco guarda só os dígitos) -----


def format_document(value: str | None, kind: str) -> str:
    """CPF "000.000.000-00" ou CNPJ "00.000.000/0000-00" (o alfanumérico também)."""
    if not value:
        return ""
    if kind == "person":
        d = "".join(c for c in value if c.isdigit())[:11]
        parts = [d[:3], d[3:6], d[6:9]]
        text = ".".join(p for p in parts if p)
        return f"{text}-{d[9:]}" if len(d) > 9 else text
    c = "".join(ch for ch in value.upper() if ch.isascii() and ch.isalnum())[:14]
    text = ".".join(p for p in (c[:2], c[2:5], c[5:8]) if p)
    if len(c) > 8:
        text += f"/{c[8:12]}"
    if len(c) > 12:
        text += f"-{c[12:]}"
    return text


def format_phone(value: str) -> str:
    """ "(11) 3333-4444" ou "(11) 98765-4321"."""
    d = "".join(c for c in value if c.isdigit())
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    d = d[:11]
    if len(d) <= 2:
        return d
    middle = 5 if len(d) == 11 else 4
    number = d[2:]
    if len(number) > middle:
        return f"({d[:2]}) {number[:middle]}-{number[middle:]}"
    return f"({d[:2]}) {number}"


def format_postal_code(value: str | None) -> str:
    """ "01310-100"."""
    d = "".join(c for c in (value or "") if c.isdigit())[:8]
    return f"{d[:5]}-{d[5:]}" if len(d) > 5 else d
