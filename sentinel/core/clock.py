"""Fonte única de horário. Todo timestamp persistido é UTC com fuso explícito."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    """Serializa em ISO-8601 UTC. Rejeita datetimes sem fuso para evitar ambiguidade."""
    if value.tzinfo is None:
        raise ValueError("datetime sem fuso horário não pode ser persistido")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def br_number(value: float, decimals: int = 1) -> str:
    """Formata número no padrão brasileiro para textos exibidos ao usuário (1.234,5)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
