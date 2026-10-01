"""Point d'entrée du bot dans le cloud (GitHub Actions).

  python -m kraken_assistant.cloud.run scan       → scan complet + envoi au site + suivi des trades membres
  python -m kraken_assistant.cloud.run track      → suivi des trades membres uniquement
  python -m kraken_assistant.cloud.run optimize   → optimisation sur l'historique + envoi des résultats

Variables d'environnement requises : SUPABASE_URL, SUPABASE_SERVICE_KEY (secrets GitHub).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..api.errors import DataUnavailable
from ..app import App
from ..backtest.optimizer import load_edges
from ..commands import execute
from ..config import Settings
from ..market.candles import drop_unclosed, futures_rows_to_df, spot_rows_to_df
from ..market.instruments import tradable_universe
from ..portfolio.management import advise
from ..portfolio.positions import Position
from ..scanner.formatter import format_report
from ..scanner.scan import scan
from .supabase_rest import Supabase, SupabaseError
from .tracker import advance_trade

log = logging.getLogger("cloud")

# Réglages modifiables depuis le site → (type, min, max). Les bornes sont revérifiées ici (défense en profondeur).
EDITABLE = {
    "score_trade": (int, 45, 85), "score_watch": (int, 25, 70), "min_rr_tp2": (float, 1.0, 4.0),
    "min_net_rr_tp2": (float, 0.8, 3.0), "max_spread_pct": (float, 0.05, 1.0), "min_sl_atr15": (float, 0.3, 2.0),
    "max_extension_atr15": (float, 1.0, 5.0), "universe_max_crypto": (int, 5, 40),
    "universe_max_xstocks": (int, 0, 20), "universe_max_commodities": (int, 0, 15),
    "disabled_strategies": (list, None, None), "news_enabled": (bool, None, None),
    "use_optimized_params": (bool, None, None),
    "quote_currencies": (list, None, None),
}


def settings_overrides(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        k, v = r.get("key"), r.get("value")
        if k not in EDITABLE:
            continue
        typ, lo, hi = EDITABLE[k]
        try:
            if typ is bool:
                out[k] = bool(v)
            elif typ is list and k == "quote_currencies":
                q = [str(x).upper() for x in (v or []) if str(x).upper() in ("USD", "EUR")]
                if q:
                    out[k] = q
            elif typ is list:
                out[k] = [str(x) for x in (v or [])]
            else:
                x = typ(v)
                out[k] = min(max(x, typ(lo)), typ(hi))
        except (TypeError, ValueError):
            log.warning("réglage %s ignoré (valeur invalide : %r)", k, v)
    return out


def build(sb: Supabase | None) -> App:
    base = Settings()
    upd = {"scheduler_enabled": False, "live_trading": False}  # le cloud n'envoie JAMAIS d'ordre réel
    if sb:
        try:
            upd.update(settings_overrides(sb.select("bot_settings")))
        except SupabaseError as e:
            log.warning("réglages du site illisibles, valeurs par défaut utilisées : %s", e)
    return App.build(base.model_copy(update=upd))


def _candles(a, n: int = 96) -> list:
    df = a.frames["15m"].iloc[-n:]
    return [[int(ts.timestamp()), round(float(r.open), 10), round(float(r.high), 10), round(float(r.low), 10),
             round(float(r.close), 10)] for ts, r in df.iterrows()]


def signal_rows(rep, scan_id: int) -> list[dict]:
    rows = []
    exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    for sig in rep.trades:
        st, p, inst = sig.setup, sig.plan, sig.inst
        a = rep.analyses.get(st.inst_key)
        rows.append(_row(st, inst, a, rep, scan_id, "TRADE", exp) | {
            "leverage_ref": p.leverage, "rr_net": p.r_multiples_net, "warnings": sig.warnings,
            "catalyst": sig.catalyst_label, "fee_taker_pct": sig.fee_pct, "fee_maker_pct": sig.maker_fee_pct,
            "sources": [{"source": n.source, "title": n.title, "url": n.url, "published": n.published_at.isoformat(),
                         "fact": n.fact, "interpretation": n.interpretation} for n in sig.news]})
    for w in rep.watch:
        a = rep.analyses.get(w.inst_key)
        if a:
            rows.append(_row(w, a.inst, a, rep, scan_id, "WATCH", exp) | {"warnings": w.rejections[:3]})
    return rows


def _row(st, inst, a, rep, scan_id, status, exp) -> dict:
    return {
        "scan_id": scan_id, "status": status, "instrument_key": st.inst_key, "display": st.display,
        "venue": inst.venue, "api_symbol": inst.symbol, "api_asset_class": inst.api_asset_class,
        "asset_class": inst.asset_class, "quote": inst.quote, "direction": st.direction, "strategy": st.strategy,
        "score": st.score, "entry_low": st.entry_low, "entry_high": st.entry_high, "sl": st.sl,
        "tp1": st.tps[0] if len(st.tps) > 0 else None, "tp2": st.tps[1] if len(st.tps) > 1 else None,
        "tp3": st.tps[2] if len(st.tps) > 2 else None, "rr": st.r_multiples(), "action": st.action,
        "invalidation": st.invalidation_text, "reasons": st.reasons, "trigger_text": st.trigger,
        "edge_note": st.edge_note, "eur_per_quote": rep.fx.get(inst.quote), "catalyst": a.catalyst.label() if a else None,
        "candles": _candles(a) if a else [], "expires_at": exp,
    }


def push_scan(sb: Supabase, rep) -> int:
    d = rep.to_dict()
    row = sb.insert("scans", {
        "mode": rep.mode, "verdict": rep.verdict, "report_text": format_report(rep),
        "reasons": rep.no_trade_reasons, "counts": rep.counts, "opportunities": rep.opportunities[:60],
        "news": [{k: n[k] for k in ("title", "source", "url", "published_at", "fetched_at", "assets", "impact_label",
                                    "verified", "is_rumor", "fact", "interpretation", "categories")} for n in d["news"]],
        "data_issues": rep.data_issues[:30], "duration_s": rep.duration_s})[0]
    rows = signal_rows(rep, row["id"])
    if rows:
        sb.insert("signals", rows, returning=False)
    return row["id"]


def push_instruments(sb: Supabase, app: App) -> None:
    rows = [{"key": i.key, "display": i.display, "venue": i.venue, "api_symbol": i.symbol,
             "api_asset_class": i.api_asset_class, "asset_class": i.asset_class, "base": i.base, "quote": i.quote,
             "can_long": i.can_long, "can_short": i.can_short,
             "max_leverage": max(i.max_leverage_long, i.max_leverage_short), "ordermin": i.ordermin,
             "lot_decimals": i.lot_decimals, "pair_decimals": i.pair_decimals,
             "updated_at": datetime.now(timezone.utc).isoformat()}
            for i in tradable_universe(app.discovery.discover())]
    sb.upsert("instruments", rows, "key")


def _bars5(app: App, t: dict) -> pd.DataFrame:
    if t.get("venue") == "futures":
        df = futures_rows_to_df(app.futures.candles(t["api_symbol"], 5))
    else:
        df = spot_rows_to_df(app.spot.ohlc(t["api_symbol"], 5, t.get("api_asset_class")))
    return drop_unclosed(df, 5)


def track_trades(sb: Supabase, app: App) -> int:
    """Met à jour les trades ouverts des membres (TP/SL réels) et calcule un conseil de gestion."""
    trades = sb.select("trades", {"status": "eq.ouvert"})
    insts = {i.key: i for i in app.discovery.discover()}
    cache: dict[str, tuple] = {}
    n = 0
    for t in trades:
        key = t["instrument_key"]
        try:
            if key not in cache:
                inst = insts.get(key)
                frames = app.candles.frames(inst) if inst else None
                cache[key] = (_bars5(app, t), frames)
            bars5, frames = cache[key]
        except (DataUnavailable, KeyError, ValueError) as e:
            log.warning("trade %s (%s) : bougies indisponibles (%s)", t["id"], t["display"], e)
            continue
        upd: dict = {}
        if t.get("auto_track", True):
            upd, events = advance_trade(t, bars5, app.settings.tp_split)
            for e in events:
                log.info("trade #%s %s : %s", t["id"], t["display"], e)
        merged = {**t, **upd}
        if merged.get("status") == "ouvert" and frames is not None:
            pos = Position(id=t["id"], source=t["mode"], instrument_key=key, display=t["display"], base="",
                           venue=t.get("venue") or "", asset_class=t.get("asset_class") or "",
                           direction=t["direction"], entry=float(t["entry_price"]), qty_initial=float(t["qty"]),
                           qty_remaining=float(merged["qty_remaining"]), sl=float(t["sl"]),
                           tp1=t.get("tp1"), tp2=t.get("tp2"), tp3=t.get("tp3"), tp1_hit=merged["tp1_hit"],
                           tp2_hit=merged["tp2_hit"], tp3_hit=merged["tp3_hit"], status="open",
                           eur_per_quote=float(t.get("eur_per_quote") or 1), fee_rate_pct=float(t.get("fee_pct") or 0),
                           realized_pnl_eur=float(merged.get("realized_pnl_eur") or 0))
            adv = advise(pos, frames, float(frames["5m"]["close"].iloc[-1]), app.settings.tp_split)
            text = adv.action + (f" → SL {adv.new_sl:.6g}" if adv.new_sl else "") + " — " + " ; ".join(adv.details)
            upd.update(advice=text[:500], advice_at=datetime.now(timezone.utc).isoformat())
            # En paper, le bot applique lui-même le déplacement de SL conseillé (break-even confirmé, suiveur).
            if t["mode"] == "paper" and adv.new_sl is not None:
                upd["sl"] = adv.new_sl
                upd["events"] = list(merged.get("events") or []) + [
                    {"at": datetime.now(timezone.utc).isoformat(), "by": "bot", "text": f"SL déplacé à {adv.new_sl:.6g}"}]
        if upd:
            sb.update("trades", {"id": f"eq.{t['id']}"}, upd)
            n += 1
    log.info("trades membres suivis : %d/%d", n, len(trades))
    return n


def cleanup(sb: Supabase, days: int = 60) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb.delete("scans", {"created_at": f"lt.{cutoff}"})  # supprime aussi les signaux liés (cascade)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    cmd = (argv or sys.argv[1:] or ["scan"])[0]
    try:
        return _main(cmd)
    except SupabaseError as e:
        sys.stdout.flush()
        log.error("ÉCHEC envoi vers Supabase : %s", e)
        print(f"\n🛑 ERREUR SUPABASE\n{e}\n👉 {e.hint()}", flush=True)
        return 1


def _main(cmd: str) -> int:
    sb = Supabase(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", ""))
    app = build(sb)
    if cmd == "scan":
        rep = scan(app, mode=os.environ.get("SCAN_MODE", "normal"))
        print(format_report(rep), flush=True)
        sid = push_scan(sb, rep)
        log.info("scan %s envoyé au site (verdict %s)", sid, rep.verdict)
        try:
            push_instruments(sb, app)
        except (DataUnavailable, SupabaseError) as e:
            log.warning("liste des instruments non envoyée : %s", e)
        track_trades(sb, app)
        cleanup(sb)
    elif cmd == "track":
        track_trades(sb, app)
    elif cmd == "optimize":
        print(execute(app, "OPTIMISER"))
        rows = [{"asset_class": e.asset_class, "strategy": e.strategy, "status": e.status,
                 "score_threshold": e.score_threshold, "min_rr_tp2": e.min_rr_tp2, "oos_trades": e.oos_trades,
                 "oos_expectancy": e.oos_expectancy, "oos_win_rate": e.oos_win_rate, "oos_pf": e.oos_pf,
                 "period": e.period, "updated_at": e.updated_at} for e in load_edges(app.db).values()]
        sb.upsert("bot_edges", rows, "asset_class,strategy")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
