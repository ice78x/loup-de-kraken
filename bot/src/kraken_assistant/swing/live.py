"""Moteur SWING en direct (19/10) : une fois par jour, juste après la clôture journalière (00:00 UTC).

1. Positions ouvertes du bot : chaque jour clôturé est rejoué (stop touché ? sinon stop suiveur remonté, jamais reculé).
2. Nouveaux signaux : seulement pour une classe d'actifs PROUVÉE par le dernier backtest swing (hors « étude »),
   avec la variante retenue par ce backtest ; règle du club : risque ouvert cumulé ≤ 2 % (1 % par position).
3. Telegram : nouvelle position, stop à remonter, position terminée.
Paper uniquement : aucun ordre réel. Aucun prix inventé : sans bougie journalière clôturée d'hier, on attend.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ..api.errors import DataUnavailable
from ..market.candles import drop_unclosed, futures_rows_to_df
from . import rules as R

log = logging.getLogger(__name__)
TABLE = "swing_positions"
DAY_KEY = "swing_last_day"
FEE = 0.0005                 # taker Kraken Futures par côté (grille par défaut), compté dans le R affiché
ZONE_N = 0.25                # zone d'entrée : clôture du signal ± 0,25 × ATR (on ne court pas après)
PAUSE_MIN_CLOSED, PAUSE_AVG_R = 10, -0.3


# ------------------------------------------------------------------------------------------------ preuve
def swing_proof(sb) -> dict[str, dict]:
    """{classe: {"variante", "prouve", "stats", "oos"}} du dernier backtest swing (les « études » sont ignorées)."""
    try:
        runs = sb.select("backtest_runs", {"select": "id,created_at,report", "order": "created_at.desc", "limit": "10"}) or []
    except Exception as e:  # noqa: BLE001
        log.warning("backtest swing illisible : %s — aucun signal swing", e)
        return {}
    for r in runs:
        rep = r.get("report") or {}
        if rep.get("type") == "swing" and not rep.get("etude") and rep.get("par_classe"):
            return {cls: {"variante": c.get("variante_retenue"), "prouve": bool(c.get("prouve")),
                          # 21/10 : toutes les variantes prouvées SEULES (ex. canal 20 et 55 jours) ; sinon la retenue
                          "variantes": [v for v in (c.get("variantes_prouvees") or []) if v] or
                                       ([c["variante_retenue"]] if c.get("variante_retenue") else []),
                          "stats": c.get("stats_variante"), "oos": (c.get("walk_forward") or {}).get("oos"),
                          "backtest_id": r.get("id")}
                    for cls, c in rep["par_classe"].items()}
    return {}


# ------------------------------------------------------------------------------------------------ calculs purs
def _d(x) -> date:
    return x if isinstance(x, date) and not isinstance(x, datetime) else pd.Timestamp(x).date()


def risk_of(p: dict) -> float:
    entry = float(p.get("entry_price") or p["signal_close"])
    return abs(entry - float(p["stop_initial"]))


def open_risk_units(positions: list[dict]) -> float:
    """Risque encore exposé, en « positions à 1 % » : 1 = stop initial, 0 = stop au point mort ou mieux."""
    tot = 0.0
    for p in positions:
        if p.get("status") != "ouvert":
            continue
        sign = 1 if p["direction"] == "LONG" else -1
        entry, risk = float(p.get("entry_price") or p["signal_close"]), risk_of(p)
        tot += min(1.0, max(0.0, sign * (entry - float(p["stop_current"])) / risk)) if risk > 0 else 1.0
    return tot


def advance_position(p: dict, df: pd.DataFrame) -> tuple[dict, list[str]]:
    """Rejoue les jours CLÔTURÉS après le dernier jour traité. Retourne (champs à mettre à jour, évènements)."""
    if p.get("status") != "ouvert" or df is None or df.empty:
        return {}, []
    sign = 1 if p["direction"] == "LONG" else -1
    exit_days = R.VARIANTS[R.parse_combo(p["variant"])[0]]["exit"]
    hist = list(p.get("history") or [])
    last = _d(hist[-1]["date"]) if hist else _d(p["signal_date"])
    entry = float(p["entry_price"]) if p.get("entry_price") is not None else None
    stop = float(p["stop_current"])
    max_r = float(p.get("max_r") or 0.0)
    upd: dict = {}
    events: list[str] = []
    for i, ts in enumerate(df.index):
        d = ts.date()
        if d <= last:
            continue
        o, h, lo, c = (float(df[k].iloc[i]) for k in ("open", "high", "low", "close"))
        if entry is None:
            entry = o                                         # entrée = ouverture du lendemain du signal (comme le backtest)
            upd["entry_price"] = entry
        risk = abs(entry - float(p["stop_initial"])) or 1e-12
        if sign * ((lo if sign > 0 else h) - stop) <= 0:
            px = min(o, stop) if sign > 0 else max(o, stop)
            r = (sign * (px - entry) - FEE * (entry + px)) / risk
            upd.update(status="clos", exit_price=px, exit_date=d.isoformat(), r=round(r, 3),
                       days=(d - _d(p["signal_date"])).days, max_r=round(max_r, 2))
            hist.append({"date": d.isoformat(), "stop": stop, "close": c, "evt": "stop"})
            events.append(f"stop touché vers {px:.6g} → {r:+.2f} R")
            break
        max_r = max(max_r, sign * ((h if sign > 0 else lo) - entry) / risk)
        win = df.iloc[max(0, i - exit_days + 1): i + 1]
        trail = float(win["low"].min()) if sign > 0 else float(win["high"].max())
        new = max(stop, trail) if sign > 0 else min(stop, trail)
        if new != stop:
            events.append(f"stop remonté de {stop:.6g} à {new:.6g}" if sign > 0 else f"stop abaissé de {stop:.6g} à {new:.6g}")
        stop = new
        hist.append({"date": d.isoformat(), "stop": stop, "close": c})
        upd.update(stop_current=stop, max_r=round(max_r, 2), days=(d - _d(p["signal_date"])).days)
    if hist != list(p.get("history") or []):
        upd["history"] = hist[-400:]
        upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    return upd, events


def signal_row(inst, sig: R.SwingSignal, variant: str) -> dict:
    sign = 1 if sig.direction == "LONG" else -1
    lo, hi = sorted((sig.close - ZONE_N * sig.atr, sig.close + ZONE_N * sig.atr))
    return {"instrument_key": inst.key, "display": inst.display, "asset_class": inst.asset_class, "quote": inst.quote,
            "direction": sig.direction, "variant": variant, "signal_date": sig.signal_ts.date().isoformat(),
            "signal_close": sig.close, "atr": sig.atr, "entry_low": lo, "entry_high": hi,
            "stop_initial": sig.close - sign * R.STOP_N * sig.atr, "stop_current": sig.close - sign * R.STOP_N * sig.atr,
            "status": "ouvert", "history": []}


# ------------------------------------------------------------------------------------------------ messages
def _px(x) -> str:
    x = float(x)
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") if x >= 100 else f"{x:.6g}".replace(".", ",")


def _name(p: dict) -> str:
    d = str(p["display"]).replace("PF_", "")
    b = d[:-3] if d.endswith("USD") else d
    return "BTC" if b == "XBT" else b


CONFIANCE = {1: "1/4 (faible)", 2: "2/4", 3: "3/4", 4: "4/4 (forte)"}


def msg_new(p: dict, risk_pct: float = 1.0, palier: int | None = None) -> str:
    sign = 1 if p["direction"] == "LONG" else -1
    pct = abs(float(p["entry_high" if sign > 0 else "entry_low"]) - float(p["stop_initial"])) / float(p["signal_close"]) * 100
    dist, rk = f"{pct:.1f}".replace(".", ","), f"{risk_pct:g}".replace(".", ",")
    return (f"🟢 <b>SWING {p['direction']} {_name(p)}</b> — trade de plusieurs jours\n"
            f"Entrée : vers {_px(p['signal_close'])} (zone {_px(p['entry_low'])} – {_px(p['entry_high'])})\n"
            f"Stop : {_px(p['stop_initial'])} (≈ {dist} % : taille petite, perte au stop = {rk} %)\n"
            + (f"Confiance : <b>{CONFIANCE.get(palier, '?')}</b> (cassure 55 j, tendance de fond, BTC porteur)\n" if palier else "")
            + "Pas d'objectif fixe : le stop suit la tendance. Je t'envoie le nouveau stop chaque matin.\n"
            "Calcule ta taille sur le site avant d'entrer.\n<i>Probabilité, pas garantie. Paper d'abord.</i>")


def msg_update(p: dict, events: list[str]) -> str:
    return f"🔧 <b>SWING {_name(p)} {p['direction']}</b> : {events[-1]}.\nMets ton stop à <b>{_px(p['stop_current'])}</b> sur Kraken."


def msg_close(p: dict) -> str:
    r = float(p.get("r") or 0)
    return f"🏁 <b>SWING {_name(p)} {p['direction']} terminé</b> : stop touché vers {_px(p['exit_price'])} → <b>{r:+.2f} R</b>."


# ------------------------------------------------------------------------------------------------ orchestration
def _daily(app, inst) -> pd.DataFrame:
    df = futures_rows_to_df(app.futures.candles(inst.symbol, 1440, 320))   # 200 j pour la moyenne longue (palier)
    return drop_unclosed(df, 1440)


def _notify(sb, texts: list[str], client=None) -> int:
    from ..cloud import notify
    tok = notify.token()
    if not tok or not texts:
        return 0
    chats = notify.recipients(sb)
    gone: set[str] = set()
    sent = sum(notify.send(t, tok, [c for c in chats if c not in gone], client, gone) for t in texts)
    if gone:
        notify._forget(sb, gone)
    return sent


def daily_job(sb, app, now: datetime | None = None, client=None) -> dict:
    """À appeler à chaque scan : ne travaille qu'une fois par jour, quand la bougie journalière d'hier est clôturée."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)
    try:
        done = sb.select("bot_settings", {"select": "value", "key": f"eq.{DAY_KEY}"}) or []
    except Exception as e:  # noqa: BLE001
        log.warning("swing : réglages illisibles (%s)", e)
        return {"statut": "illisible"}
    if done and str(done[0].get("value")) == today.isoformat():
        return {"statut": "déjà fait"}
    out = {"statut": "ok", "mises_a_jour": 0, "nouvelles": 0, "refusees": 0, "messages": 0}
    texts: list[str] = []
    insts = {i.key: i for i in app.discovery.discover()}
    ref = insts.get("futures:PF_XBTUSD") or next((i for i in insts.values() if i.venue == "futures"), None)
    try:
        ref_df = _daily(app, ref) if ref else None
    except DataUnavailable as e:
        log.warning("swing : bougies journalières indisponibles (%s) — on réessaie au prochain scan", e)
        return {"statut": "données indisponibles"}
    if ref_df is None or not len(ref_df) or ref_df.index[-1].date() < yesterday:
        return {"statut": "attente bougie"}
    try:
        positions = sb.select(TABLE, {"status": "eq.ouvert"}) or []
    except Exception as e:  # noqa: BLE001 — table absente : schema.sql pas encore relancé
        log.warning("swing : table %s illisible (%s) — relance supabase/schema.sql", TABLE, e)
        return {"statut": "table absente"}
    # 1. positions ouvertes
    for p in positions:
        inst = insts.get(p["instrument_key"])
        if inst is None:
            continue
        try:
            df = _daily(app, inst)
        except DataUnavailable as e:
            log.warning("swing %s : bougies indisponibles (%s)", p["display"], e)
            continue
        if not len(df) or df.index[-1].date() < yesterday:
            log.info("swing : bougie journalière d'hier pas encore disponible (%s) — on réessaie au prochain scan", p["display"])
            return {"statut": "attente bougie"}
        upd, events = advance_position(p, df)
        if upd:
            sb.update(TABLE, {"id": f"eq.{p['id']}"}, upd)
            p.update(upd)
            out["mises_a_jour"] += 1
        if p.get("status") == "clos":
            texts.append(msg_close(p))
        elif any(e.startswith("stop") for e in events):
            texts.append(msg_update(p, events))
    sync_member_stops(sb, positions)
    # 2. nouveaux signaux (classes prouvées seulement)
    proof = swing_proof(sb)
    proven = {cls: v for cls, v in proof.items() if v.get("prouve") and v.get("variante")}
    paused = _paused(sb)
    if proven and not paused:
        from ..backtest.runner import pick_universe
        cfg = getattr(app, "settings", None)
        risk = float(getattr(cfg, "swing_risk_pct", 1.0) or 1.0)
        n_univ = int(getattr(cfg, "swing_universe", 40) or 40)
        cap = float(getattr(cfg, "swing_risk_cap", 2.0) or 2.0)
        btc_ok = R.above_sma(ref_df) if ref is not None and ref.key.endswith("PF_XBTUSD") else None
        universe = [i for i in pick_universe(app, n_univ, {c: 12 for c in proven if c != "crypto"}) if i.asset_class in proven]
        open_now = [p for p in positions if p.get("status") == "ouvert"]
        busy = {p["instrument_key"] for p in open_now}
        for inst in universe:
            if inst.key in busy:
                continue
            try:
                df = _daily(app, inst)
            except DataUnavailable:
                continue
            if not len(df) or df.index[-1].date() != yesterday:
                continue
            # Canal le plus long d'abord (55 puis 20 jours) : une seule position par actif.
            sig, variant = None, None
            for name in sorted(proven[inst.asset_class]["variantes"], key=lambda n: -R.VARIANTS[R.parse_combo(n)[0]]["entry"]):
                v, _, sides = R.parse_combo(name)
                sig = R.last_signal(df, v, sides)
                if sig is not None:
                    variant = name
                    break
            if sig is None:
                continue
            row = signal_row(inst, sig, variant)
            palier = int(R.tier_series(df, btc_ok)[-1]) if sig.direction == "LONG" else 1
            row["history"] = [{"date": row["signal_date"], "stop": row["stop_initial"], "close": row["signal_close"],
                               "risque_pct": risk, "palier": palier}]
            if (open_risk_units(open_now) + 1.0) * risk > cap + 1e-9:
                row.update(status="refuse", refus=f"{cap:g} % de risque déjà engagé sur les positions ouvertes (règle du club)".replace(".", ","))
                out["refusees"] += 1
            try:
                ins = sb.insert(TABLE, row, returning=True)
            except Exception as e:  # noqa: BLE001 — doublon (même signal déjà enregistré) ou table absente
                log.info("swing %s : signal non enregistré (%s)", inst.display, type(e).__name__)
                continue
            if row["status"] == "ouvert":
                rec = (ins or [row])[0]
                open_now.append(rec)
                busy.add(inst.key)
                texts.append(msg_new(rec, risk, palier))
                out["nouvelles"] += 1
    elif paused:
        out["pause"] = paused
    out["classes_prouvees"] = sorted(proven)
    out["messages"] = _notify(sb, texts, client)
    sb.upsert("bot_settings", [{"key": DAY_KEY, "value": today.isoformat(), "label": "Swing : dernier jour traité"}], "key")
    log.info("swing : %s", out)
    return out


def sync_member_stops(sb, positions: list[dict]) -> int:
    """Trades des membres liés à une position swing (trades.swing_id) : leur stop suit celui du bot, jamais reculé.
    Le bot ne passe aucun ordre : le membre déplace lui-même son stop sur Kraken (message Telegram)."""
    by_id = {p["id"]: p for p in positions if p.get("id") is not None}
    if not by_id:
        return 0
    try:
        trades = sb.select("trades", {"status": "eq.ouvert", "swing_id": "not.is.null"}) or []
    except Exception as e:  # noqa: BLE001 — colonne absente tant que schema.sql n'est pas relancé
        log.info("swing : trades liés non lus (%s)", type(e).__name__)
        return 0
    n = 0
    now = datetime.now(timezone.utc).isoformat()
    for t in trades:
        p = by_id.get(t.get("swing_id"))
        if not p or p.get("status") != "ouvert":
            continue
        sign = 1 if t["direction"] == "LONG" else -1
        new, old = float(p["stop_current"]), (float(t["sl"]) if t.get("sl") is not None else None)
        if old is not None and sign * (new - old) <= 0:
            continue
        ev = list(t.get("events") or []) + [{"at": now, "by": "bot", "text": f"stop suiveur swing : {old if old is not None else '—'} → {new:.6g}"}]
        sb.update("trades", {"id": f"eq.{t['id']}"}, {"sl": new, "events": ev})
        n += 1
    return n


def _paused(sb) -> str | None:
    """Coupe-circuit réel : après 10 positions swing terminées, une moyenne < −0,3 R suspend les nouvelles entrées."""
    try:
        rows = sb.select(TABLE, {"select": "r", "status": "eq.clos", "order": "exit_date.desc", "limit": "30"}) or []
    except Exception:  # noqa: BLE001
        return None
    rs = [float(r["r"]) for r in rows if r.get("r") is not None]
    if len(rs) >= PAUSE_MIN_CLOSED and sum(rs) / len(rs) < PAUSE_AVG_R:
        return f"swing en pause : {len(rs)} positions terminées, {sum(rs) / len(rs):+.2f} R en moyenne"
    return None
