"""
pa/tools/datetime_tool.py — Datetime atual + cálculos relativos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def current_datetime(tz: str = "UTC") -> dict:
    """
    Retorna o datetime atual formatado.

    Args:
        tz: timezone — "UTC" ou offset como "UTC-3", "UTC+1"

    Returns:
        dict com iso, date, time, weekday, timezone
    """
    now = datetime.now(timezone.utc)

    if tz != "UTC" and tz.startswith("UTC"):
        try:
            offset_str = tz[3:]
            sign = 1 if offset_str.startswith("+") else -1
            hours = int(offset_str.lstrip("+-"))
            offset = timezone(timedelta(hours=sign * hours))
            now = now.astimezone(offset)
        except (ValueError, IndexError):
            pass

    return {
        "iso":      now.isoformat(),
        "date":     now.strftime("%Y-%m-%d"),
        "time":     now.strftime("%H:%M:%S"),
        "weekday":  now.strftime("%A"),
        "timezone": tz,
    }


def add_days(date_str: str, days: int) -> str:
    """
    Adiciona ou subtrai dias de uma data.

    Args:
        date_str: data no formato YYYY-MM-DD (ou "today")
        days:     número de dias (negativo = subtrair)

    Returns:
        str — data resultante em YYYY-MM-DD
    """
    if date_str.lower() == "today":
        base = datetime.now(timezone.utc)
    else:
        base = datetime.fromisoformat(date_str)

    result = base + timedelta(days=days)
    return result.strftime("%Y-%m-%d")


def days_between(date_a: str, date_b: str) -> int:
    """
    Calcula a diferença em dias entre duas datas.

    Args:
        date_a: data inicial em YYYY-MM-DD
        date_b: data final em YYYY-MM-DD

    Returns:
        int — número de dias (positivo se date_b > date_a)
    """
    a = datetime.fromisoformat(date_a)
    b = datetime.fromisoformat(date_b)
    return (b - a).days