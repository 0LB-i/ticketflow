"""Datas, tempo relativo e duração como a SPA mostra (`composables/formato.ts`).

O fuso é sempre o de São Paulo (docs/13 §13.6). Os textos imitam o `Intl` do navegador no
estilo curto, para as duas interfaces mostrarem o mesmo enquanto convivem (ADR 0011).
"""

from datetime import datetime
from math import floor
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/Sao_Paulo")


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
