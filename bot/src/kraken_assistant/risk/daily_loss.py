"""Perte journalière (jour calendaire Europe/Paris) à partir des exécutions enregistrées."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from ..database.db import Database


def day_start_utc(tz: str, now: datetime | None = None) -> datetime:
    z = ZoneInfo(tz)
    local = (now or datetime.now(timezone.utc)).astimezone(z)
    return datetime.combine(local.date(), time(0, 0), tzinfo=z).astimezone(timezone.utc)


def realized_pnl_today(db: Database, tz: str, now: datetime | None = None, sources: tuple[str, ...] = ("paper",)) -> float:
    start = day_start_utc(tz, now).isoformat(timespec="seconds")
    ph = ",".join("?" * len(sources))
    row = db.one(
        f"SELECT COALESCE(SUM(f.pnl_eur), 0) AS pnl FROM fills f JOIN positions p ON p.id=f.position_id "
        f"WHERE f.ts >= ? AND p.source IN ({ph})", (start, *sources))
    return float(row["pnl"]) if row else 0.0
