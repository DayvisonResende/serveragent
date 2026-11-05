"""Fonte única de horário. Todo timestamp persistido é UTC com fuso explícito."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    """Serializa em ISO-8601 UTC. Rejeita datetimes sem fuso para evitar ambiguidade."""
    if value.tzinfo is None:
        raise ValueError("datetime sem fuso horário não pode ser persistido")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
