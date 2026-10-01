"""Suivi automatique des trades des membres sur les VRAIES bougies 5m Kraken.

Mêmes règles que le paper trading : SL testé avant les TP dans une même bougie (prudence),
TP1 30 % / TP2 40 % / TP3 le reste, frais appliqués à chaque sortie.
Aucun prix n'est inventé : sans bougie réelle, rien ne bouge.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd


def _f(x, default=None):
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def advance_trade(t: dict, bars5: pd.DataFrame, split: tuple[float, float, float] = (0.3, 0.4, 0.3),
                  now: datetime | None = None) -> tuple[dict, list[str]]:
    """Rejoue les bougies 5m clôturées depuis last_checked. Retourne (champs à mettre à jour, évènements)."""
    now = now or datetime.now(timezone.utc)
    upd: dict = {}
    events: list[str] = []
    if t.get("status") != "ouvert":
        return upd, events
    sign = 1 if t["direction"] == "LONG" else -1
    entry, sl = float(t["entry_price"]), float(t["sl"])
    qty, rem = float(t["qty"]), float(t["qty_remaining"])
    epq, fee = float(t.get("eur_per_quote") or 1), float(t.get("fee_pct") or 0) / 100
    realized = float(t.get("realized_pnl_eur") or 0)
    tps = [_f(t.get("tp1")), _f(t.get("tp2")), _f(t.get("tp3"))]
    hit = [bool(t.get("tp1_hit")), bool(t.get("tp2_hit")), bool(t.get("tp3_hit"))]
    since = pd.Timestamp(max(pd.Timestamp(t["last_checked"]), pd.Timestamp(t["opened_at"]))).floor("5min")
    new = bars5[bars5.index >= since] if len(bars5) else bars5
    last_tp = max((i for i, x in enumerate(tps) if x is not None), default=-1)
    closed = False
    for ts, b in new.iterrows():
        adverse = b["low"] if sign > 0 else b["high"]
        if sign * (adverse - sl) <= 0:
            px = min(float(b["open"]), sl) if sign > 0 else max(float(b["open"]), sl)
            realized += sign * (px - entry) * rem * epq - fee * px * rem * epq
            events.append(f"{ts:%d/%m %H:%M} SL touché à {px:g}")
            upd.update(exit_price=px, close_reason="SL" if not any(hit) else "SL ajusté")
            rem, closed = 0.0, True
            break
        fav = b["high"] if sign > 0 else b["low"]
        for i, tp in enumerate(tps):
            if tp is None or hit[i] or sign * (fav - tp) < 0:
                continue
            q = rem if i == last_tp else min(rem, qty * split[i])
            realized += sign * (tp - entry) * q * epq - fee * tp * q * epq
            rem -= q
            hit[i] = True
            events.append(f"{ts:%d/%m %H:%M} TP{i + 1} atteint à {tp:g} ({q:g} clôturé)")
            if rem <= 1e-12:
                upd.update(exit_price=tp, close_reason=f"TP{i + 1}")
                closed = True
                break
        if closed:
            break
    upd.update(qty_remaining=max(0.0, round(rem, 12)), realized_pnl_eur=round(realized, 6),
               tp1_hit=hit[0], tp2_hit=hit[1], tp3_hit=hit[2], last_checked=now.isoformat())
    if closed or rem <= 1e-12:
        risk = float(t.get("risk_eur") or 0)
        upd.update(status="clos", closed_at=now.isoformat(), qty_remaining=0,
                   r_multiple=round(realized / risk, 3) if risk > 0 else None)
    if events:
        upd["events"] = list(t.get("events") or []) + [{"at": now.isoformat(), "by": "bot", "text": e} for e in events]
    return upd, events
