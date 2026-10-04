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
from ..news.translate import Translator, explain
from .supabase_rest import Supabase, SupabaseError
from .learning import degraded_strategies, live_edges, pending_rows, resolve_signals
from .tracker import advance_trade

log = logging.getLogger("cloud")

# Réglages modifiables depuis le site → (type, min, max). Les bornes sont revérifiées ici (défense en profondeur).
EDITABLE = {
    "score_trade": (int, 60, 95), "score_watch": (int, 40, 90), "require_proven_edge": (bool, None, None), "min_rr_tp2": (float, 1.0, 4.0),
    "min_net_rr_tp2": (float, 0.8, 3.0), "max_spread_pct": (float, 0.05, 1.0), "min_sl_atr15": (float, 0.3, 2.0), "min_sl_pct": (float, 0.1, 1.5),
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
        try:
            upd["live_edges"] = live_edges(sb.select("signal_stats"))
        except SupabaseError as e:
            log.warning("statistiques réelles des signaux indisponibles (lance supabase/schema.sql) : %s", e)
        upd.update(v2_inputs(sb))
    return App.build(base.model_copy(update=upd))


def v2_inputs(sb: Supabase) -> dict:
    """Moteur v2 : combinaisons prouvées du dernier backtest walk-forward + stratégies en série de pertes (réel)."""
    out: dict = {}
    try:
        runs = sb.select("backtest_runs", {"select": "id,created_at,report", "order": "created_at.desc", "limit": "1"})
        edges = ((runs[0].get("report") or {}).get("edges") or {}) if runs else {}
        out["v2_edges"] = {k: v for k, v in edges.items() if isinstance(v, dict)}
        log.info("moteur v2 : %d combinaison(s) testée(s), %d prouvée(s)", len(edges),
                 sum(1 for v in edges.values() if isinstance(v, dict) and v.get("prouve")))
    except SupabaseError as e:
        log.warning("résultats de backtest illisibles (lance supabase/schema.sql) : %s — aucun 🟢 sans preuve", e)
    try:
        rows = sb.select("signal_outcomes", {"select": "strategy,status,r,created_at", "features->>moteur": "eq.v2",
                                             "r": "not.is.null", "order": "created_at.desc", "limit": "400"})
        bad = degraded_strategies(rows)
        out["degraded_strategies"] = sorted(bad)
        for k, why in bad.items():
            log.warning("stratégie %s suspendue : %s", k, why)
    except SupabaseError as e:
        log.warning("dégradation non vérifiée : %s", e)
    return out


def _candles(a, n: int = 96) -> list:
    df = a.frames["15m"].iloc[-n:]
    return [[int(ts.timestamp()), round(float(r.open), 10), round(float(r.high), 10), round(float(r.low), 10),
             round(float(r.close), 10)] for ts, r in df.iterrows()]


def news_row(n, tr=None, translate: bool = True) -> dict:
    """News pour le site : faits (titre original, source, heure) + titre en français + explication simple."""
    return {"title": n.title, "title_fr": tr.fr(n.title) if (tr and translate) else None, "explain": explain(n),
            "source": n.source, "url": n.url, "published_at": n.published_at.isoformat(), "fetched_at": n.fetched_at.isoformat(),
            "assets": n.assets, "impact_label": n.impact_label, "verified": n.verified, "is_rumor": n.is_rumor,
            "fact": n.fact, "interpretation": n.interpretation, "categories": n.categories}


def signal_rows(rep, scan_id: int, tr=None) -> list[dict]:
    rows = []
    exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    for sig in rep.trades:
        st, p, inst = sig.setup, sig.plan, sig.inst
        a = rep.analyses.get(st.inst_key)
        rows.append(_row(st, inst, a, rep, scan_id, "TRADE", exp) | {
            "leverage_ref": p.leverage, "rr_net": p.r_multiples_net, "warnings": sig.warnings,
            "catalyst": sig.catalyst_label, "fee_taker_pct": sig.fee_pct, "fee_maker_pct": sig.maker_fee_pct,
            "sources": [news_row(n, tr) | {"published": n.published_at.isoformat()} for n in sig.news]})
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
        # moteur v2
        "grade": st.grade or None, "regime": st.regime or None,
        "quality": {"composantes": st.components, "regime": st.regime_label, "contexte_btc": st.btc_context,
                    "coupe_circuits": st.kill[:5], "rr_net": st.net_rr, "score_ancien": st.legacy_score},
    }


V2_COLUMNS = ("grade", "regime", "quality")


def push_scan(sb: Supabase, rep, tr=None) -> int:
    row = sb.insert("scans", {
        "mode": rep.mode, "verdict": rep.verdict, "report_text": format_report(rep),
        "reasons": rep.no_trade_reasons, "counts": rep.counts, "opportunities": rep.opportunities[:60],
        # Les 10 premières news (celles affichées) sont traduites ; les autres gardent leur titre original.
        "news": [news_row(n, tr, translate=i < 10) for i, n in enumerate(rep.news)],
        "data_issues": rep.data_issues[:30], "duration_s": rep.duration_s})[0]
    rows = signal_rows(rep, row["id"], tr)
    if rows:
        try:
            inserted = sb.insert("signals", rows, returning=True)
        except SupabaseError as e:
            if not any(c in str(e) for c in V2_COLUMNS):
                raise
            # schéma pas encore mis à jour : on publie quand même, sans les colonnes du moteur v2
            log.warning("colonnes v2 absentes de « signals » (relance supabase/schema.sql) : %s", e)
            inserted = sb.insert("signals", [{k: v for k, v in r.items() if k not in V2_COLUMNS} for r in rows], returning=True)
        # Mémoire du bot : chaque signal publié est enregistré tout de suite (« en cours »), avec son contexte complet ;
        # le résultat réel est rempli plus tard par l'apprentissage. Jamais bloquant pour le scan.
        try:
            pairs = [(sig.setup, rep.analyses.get(sig.setup.inst_key), rep.mode) for sig in rep.trades] + \
                    [(w, rep.analyses.get(w.inst_key), rep.mode) for w in rep.watch if rep.analyses.get(w.inst_key)]
            sb.upsert("signal_outcomes", pending_rows(inserted, pairs), "signal_id")
        except (SupabaseError, KeyError, TypeError, ValueError, AttributeError) as e:
            log.warning("mémoire des signaux non enregistrée (lance supabase/schema.sql ?) : %s", e)
    return row["id"]


def site_universe(app: App) -> list:
    """Paires affichées sur le site = EXACTEMENT ce que Kraken déclare disponible pour le pays (FR) :
    spot et xStocks via AssetPairs?country_code=FR, perpétuels non interdits pour ce pays, statut négociable,
    dans les devises de cotation choisies (USD par défaut). Le scanner, lui, n'analyse en profondeur que les plus liquides."""
    quotes = set(app.taxonomy.quotes)
    return [i for i in app.discovery.discover()
            if i.tradable and i.account_access != "refusé" and (i.venue == "futures" or i.quote in quotes)]


def push_instruments(sb: Supabase, app: App, min_rows: int = 20) -> int:
    start = datetime.now(timezone.utc).isoformat()
    rows = [{"key": i.key, "display": i.display, "venue": i.venue, "api_symbol": i.symbol,
             "api_asset_class": i.api_asset_class, "asset_class": i.asset_class, "base": i.base, "quote": i.quote,
             "can_long": i.can_long, "can_short": i.can_short,
             "max_leverage": max(i.max_leverage_long, i.max_leverage_short), "ordermin": i.ordermin,
             "lot_decimals": i.lot_decimals, "pair_decimals": i.pair_decimals,
             "updated_at": datetime.now(timezone.utc).isoformat()}
            for i in site_universe(app)]
    sb.upsert("instruments", rows, "key")
    # Retire les paires qui ne sont plus disponibles (délistées, plus ouvertes en France, autre devise…).
    # Garde-fou : seulement si Kraken a bien renvoyé une liste complète.
    if len(rows) >= min_rows:
        sb.delete("instruments", {"updated_at": f"lt.{start}"})
    log.info("paires Kraken (%s) envoyées au site : %d", app.settings.country_code, len(rows))
    return len(rows)


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
        try:
            n += _track_one(sb, app, t, insts, cache)
        except Exception as e:  # noqa: BLE001 — un trade en erreur ne doit jamais bloquer le suivi des autres
            log.error("trade %s (%s) : suivi impossible (%s: %s)", t.get("id"), t.get("display"), type(e).__name__, e)
    log.info("trades membres suivis : %d/%d", n, len(trades))
    return n


def _track_one(sb: Supabase, app: App, t: dict, insts: dict, cache: dict) -> int:
    key = t["instrument_key"]
    try:
        if key not in cache:
            inst = insts.get(key)
            bars5 = _bars5(app, t)
            try:  # les bougies multi-unités ne servent qu'au conseil : leur absence ne bloque jamais TP / SL
                frames = app.candles.frames(inst) if inst else None
            except Exception as e:  # noqa: BLE001
                log.warning("trade %s (%s) : conseil indisponible (%s)", t["id"], t["display"], e)
                frames = None
            cache[key] = (bars5, frames)
        bars5, frames = cache[key]
    except (DataUnavailable, KeyError, ValueError) as e:
        log.warning("trade %s (%s) : bougies indisponibles (%s)", t["id"], t["display"], e)
        return 0
    upd: dict = {}
    if t.get("auto_track", True):
        upd, events = advance_trade(t, bars5, app.settings.tp_split)
        for e in events:
            log.info("trade #%s %s : %s", t["id"], t["display"], e)
    merged = {**t, **upd}
    if merged.get("status") == "ouvert" and frames is not None and merged.get("sl") is None:
        liq = merged.get("liq_price")
        upd.update(advice=(f"HOLD — pas de stop : marge isolée, liquidation vers {float(liq):.6g}. "
                           "Pense à poser un stop si le scénario s'invalide." if liq else
                           "HOLD — pas de stop et pas de levier : surveille l'invalidation de ton scénario.")[:500],
                   advice_at=datetime.now(timezone.utc).isoformat())
    elif merged.get("status") == "ouvert" and frames is not None:
        pos = Position(id=t["id"], source=t["mode"], instrument_key=key, display=t["display"], base="",
                       venue=t.get("venue") or "", asset_class=t.get("asset_class") or "",
                       direction=t["direction"], entry=float(t["entry_price"]), qty_initial=float(t["qty"]),
                       qty_remaining=float(merged["qty_remaining"]), sl=float(merged["sl"]),
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
        return 1
    return 0


def learn(sb: Supabase, app: App) -> None:
    """Enregistre les résultats réels des signaux terminés (jamais bloquant pour le scan)."""
    try:
        resolve_signals(sb, app)
    except (SupabaseError, DataUnavailable) as e:
        log.warning("apprentissage non enregistré : %s", e)


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
    cible = (os.environ.get("SCAN_SYMBOL") or "").strip()
    if cmd == "scan" and cible:
        # Vérification express d'un seul setup : uniquement cette paire, résultat publié comme un scan « cible ».
        rep = scan(app, mode="cible", focus={cible})
        print(format_report(rep), flush=True)
        sid = push_scan(sb, rep, Translator(app.db))
        log.info("vérification express %s envoyée au site (scan %s, verdict %s)", cible, sid, rep.verdict)
        return 0
    if cmd == "scan":
        rep = scan(app, mode=os.environ.get("SCAN_MODE", "normal"))
        print(format_report(rep), flush=True)
        sid = push_scan(sb, rep, Translator(app.db))
        log.info("scan %s envoyé au site (verdict %s)", sid, rep.verdict)
        try:
            push_instruments(sb, app)
        except (DataUnavailable, SupabaseError) as e:
            log.warning("liste des instruments non envoyée : %s", e)
        track_trades(sb, app)
        learn(sb, app)
        cleanup(sb)
    elif cmd == "track":
        track_trades(sb, app)
        learn(sb, app)
    elif cmd == "backtest":
        from ..backtest.runner import run_v2, summary_text
        days = int(os.environ.get("BACKTEST_DAYS") or 120)
        n = int(os.environ.get("BACKTEST_INSTRUMENTS") or 16)
        rep = run_v2(app, days=min(max(days, 30), 365), max_instruments=min(max(n, 3), 40))
        text = summary_text(rep)
        print(text, flush=True)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("```\n" + text + "\n```\n")
        sb.insert("backtest_runs", {"days": days, "summary": text, "report": json.loads(json.dumps(rep, default=str))})
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
