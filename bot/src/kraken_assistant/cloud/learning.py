"""Apprentissage sur les VRAIS résultats des signaux du bot.

Après chaque scan, les signaux des derniers jours sont rejoués sur les vraies bougies 15 min Kraken :
- entrée : la première bougie qui touche la zone d'entrée avant l'expiration (prix d'entrée = le moins bon de la zone) ;
- ensuite : stop testé AVANT les objectifs dans une même bougie (prudence) ; TP1 30 % / TP2 40 % / TP3 30 % ;
  après le TP1, le stop passe au prix d'entrée (break-even), comme le conseille le site ;
- frais futures déduits (entrée maker + sortie taker) ; durée max 48 h après l'entrée, puis clôture au dernier prix.
Le résultat (en R, net de frais) va dans la table `signal_outcomes`, gardée sans limite de temps.
Les statistiques par stratégie et classe d'actifs (vue `signal_stats`) sont relues à chaque scan :
une combinaison qui perd en vrai (assez de trades, R moyen négatif) ne peut plus donner de 🟢.
Rien n'est inventé : sans bougie réelle, le signal reste « en cours » et sera rejoué plus tard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger(__name__)

FINAUX = ("sl", "tp3", "be", "temps", "non_entre")


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def resolve(sig: dict, bars15: pd.DataFrame, now: datetime | None = None, split=(0.3, 0.4, 0.3),
            fee_entry_pct: float = 0.02, fee_exit_pct: float = 0.05, max_hold_h: float = 48) -> dict | None:
    """Résultat d'un signal rejoué sur des bougies 15 min CLÔTURÉES (index UTC). None = pas encore terminé."""
    now = now or datetime.now(timezone.utc)
    L = sig["direction"] == "LONG"
    sign = 1 if L else -1
    lo, hi, sl = _f(sig.get("entry_low")), _f(sig.get("entry_high")), _f(sig.get("sl"))
    tps = [x for x in (_f(sig.get("tp1")), _f(sig.get("tp2")), _f(sig.get("tp3"))) if x is not None]
    if None in (lo, hi, sl) or not tps:
        return None
    entry = hi if L else lo                         # le moins bon prix de la zone (prudence)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    created = pd.Timestamp(sig["created_at"]).tz_convert("UTC") if pd.Timestamp(sig["created_at"]).tzinfo else \
        pd.Timestamp(sig["created_at"]).tz_localize("UTC")
    expires = pd.Timestamp(sig["expires_at"]) if sig.get("expires_at") else created + pd.Timedelta(hours=4)
    expires = expires.tz_convert("UTC") if expires.tzinfo else expires.tz_localize("UTC")
    bars = bars15[bars15.index >= created.floor("15min") + pd.Timedelta(minutes=15)] if len(bars15) else bars15
    fees_r = (fee_entry_pct + fee_exit_pct) / 100 * entry / risk
    base = {"entry": entry, "risk": risk}

    entered_at = None
    rest, stop, r, hits = 1.0, sl, 0.0, 0
    parts = list(split[:len(tps)])
    parts[-1] = 1.0 - sum(parts[:-1])
    for ts, b in bars.iterrows():
        hi_b, lo_b = float(b["high"]), float(b["low"])
        if entered_at is None:
            if ts >= expires:
                return {**base, "outcome": "non_entre", "r": None, "entered_at": None, "resolved_at": ts.isoformat()}
            if not (lo_b <= hi and hi_b >= lo):
                continue
            entered_at = ts
        adverse = lo_b if L else hi_b
        favorable = hi_b if L else lo_b
        if sign * (adverse - stop) <= 0:            # stop (ou break-even) touché en premier
            r += rest * sign * (stop - entry) / risk
            return {**base, "outcome": "be" if hits else "sl", "r": round(r - fees_r, 3), "tp_hits": hits,
                    "entered_at": entered_at.isoformat(), "resolved_at": ts.isoformat()}
        while hits < len(tps) and sign * (favorable - tps[hits]) >= 0:
            r += parts[hits] * abs(tps[hits] - entry) / risk
            rest -= parts[hits]
            hits += 1
            stop = entry                             # après le TP1 : stop au prix d'entrée
        if hits == len(tps):
            return {**base, "outcome": "tp3", "r": round(r - fees_r, 3), "tp_hits": hits,
                    "entered_at": entered_at.isoformat(), "resolved_at": ts.isoformat()}
        if ts >= entered_at + pd.Timedelta(hours=max_hold_h):
            r += rest * sign * (float(b["close"]) - entry) / risk
            return {**base, "outcome": "temps", "r": round(r - fees_r, 3), "tp_hits": hits,
                    "entered_at": entered_at.isoformat(), "resolved_at": ts.isoformat()}
    if entered_at is None and pd.Timestamp(now) >= expires and len(bars) and bars.index[-1] >= expires:
        return {**base, "outcome": "non_entre", "r": None, "entered_at": None, "resolved_at": bars.index[-1].isoformat()}
    return None


def outcome_row(sig: dict, res: dict) -> dict:
    created = pd.Timestamp(sig["created_at"])
    created = created.tz_convert("Europe/Paris") if created.tzinfo else created.tz_localize("UTC").tz_convert("Europe/Paris")
    return {
        "signal_id": sig["id"], "created_at": sig["created_at"], "instrument_key": sig.get("instrument_key"),
        "display": sig.get("display"), "asset_class": sig.get("asset_class"), "strategy": sig.get("strategy"),
        "direction": sig.get("direction"), "status": sig.get("status"), "score": sig.get("score"),
        "entry_low": sig.get("entry_low"), "entry_high": sig.get("entry_high"), "sl": sig.get("sl"),
        "tp1": sig.get("tp1"), "tp2": sig.get("tp2"), "tp3": sig.get("tp3"),
        "sl_pct": round(res["risk"] / res["entry"] * 100, 4), "outcome": res["outcome"], "r": res.get("r"),
        "tp_hits": res.get("tp_hits", 0), "entered_at": res.get("entered_at"), "resolved_at": res.get("resolved_at"),
        "hour_paris": int(created.hour), "weekday": int(created.weekday()),
    }


def live_edges(rows: list[dict]) -> dict:
    """Vue signal_stats → {"stratégie|classe": {"n", "win_rate", "avg_r"}} (signaux 🟢 entrés seulement)."""
    out = {}
    for x in rows or []:
        if x.get("status") != "TRADE":
            continue
        out[f"{x.get('strategy')}|{x.get('asset_class')}"] = {
            "n": int(x.get("n") or 0), "win_rate": _f(x.get("win_rate")), "avg_r": _f(x.get("avg_r"))}
    return out


def resolve_signals(sb, app, days: int = 4, max_signals: int = 300) -> int:
    """Rejoue les signaux récents pas encore terminés et enregistre leur résultat réel."""
    from ..api.errors import DataUnavailable
    from ..market.candles import drop_unclosed, futures_rows_to_df, spot_rows_to_df

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cols = "id,created_at,expires_at,status,instrument_key,display,venue,api_symbol,api_asset_class,asset_class,strategy," \
           "direction,score,entry_low,entry_high,sl,tp1,tp2,tp3"
    sigs = sb.select("signals", {"select": cols, "created_at": f"gte.{since}", "order": "created_at.asc", "limit": str(max_signals)})
    done = {r["signal_id"] for r in sb.select("signal_outcomes", {"select": "signal_id", "created_at": f"gte.{since}"})}
    todo = [s for s in sigs if s["id"] not in done]
    cache: dict[str, pd.DataFrame | None] = {}
    rows = []
    for s in todo:
        key = f"{s.get('venue')}|{s.get('api_symbol')}"
        if key not in cache:
            try:
                if s.get("venue") == "futures":
                    df = futures_rows_to_df(app.futures.candles(s["api_symbol"], 15, lookback_bars=24 * 4 * (days + 3)))
                else:
                    df = spot_rows_to_df(app.spot.ohlc(s["api_symbol"], 15, s.get("api_asset_class")))
                cache[key] = drop_unclosed(df, 15)
            except (DataUnavailable, KeyError, ValueError, TypeError) as e:
                log.warning("apprentissage : bougies indisponibles pour %s (%s)", s.get("display"), e)
                cache[key] = None
        bars = cache[key]
        if bars is None or not len(bars):
            continue
        res = resolve(s, bars)
        if res:
            rows.append(outcome_row(s, res))
    if rows:
        sb.upsert("signal_outcomes", rows, "signal_id")
    log.info("apprentissage : %d signal(aux) terminé(s) enregistré(s) sur %d à suivre", len(rows), len(todo))
    return len(rows)
