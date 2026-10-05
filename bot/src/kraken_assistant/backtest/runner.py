"""Lance le backtest walk-forward v2 sur de VRAIES bougies Kraken (perpétuels) : utilisé par GitHub Actions.

  1. univers : les perpétuels crypto les plus liquides du moment (BTC et ETH toujours inclus) ;
  2. historique : remonté page par page depuis l'API charts de Kraken Futures (backfill), gardé en cache ;
  3. contexte BTC/ETH recalculé à chaque heure ;
  4. détection (en parallèle), puis walk-forward AVANT / APRÈS (walkforward.py).
Aucune donnée n'est inventée : un instrument sans historique suffisant est ignoré et listé.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from ..api.errors import DataUnavailable
from ..market.instruments import tradable_universe
from ..market.prices import eur_per_quote
from .engine import Arrays, BTParams, ContextSeries, detect, regime_series
from .walkforward import walk_forward_v2

log = logging.getLogger(__name__)
WARMUP = 400


def _job(args):
    df15, inst, settings, ctx = args
    try:
        return detect(df15, inst, settings, "all", WARMUP, 1.2, ctx)
    except Exception as e:  # un instrument en erreur ne doit pas arrêter le backtest
        log.warning("détection impossible sur %s : %s", inst.display, e)
        return []


def pick_universe(app, max_instruments: int) -> list:
    insts = [i for i in tradable_universe(app.discovery.discover()) if i.venue == "futures" and i.asset_class == "crypto"]
    tickers = app.prices.fetch(insts)
    try:
        usd = eur_per_quote("USD", insts, tickers)
    except DataUnavailable:
        usd = 1.0
    vol = {i.key: (tickers[i.key].volume_24h_base * (tickers[i.key].vwap_24h or tickers[i.key].last) * usd)
           for i in insts if i.key in tickers}
    ranked = sorted((i for i in insts if i.key in vol), key=lambda i: -vol[i.key])
    chosen = [i for i in ranked if i.base in ("BTC", "XBT", "ETH")][:2]
    for i in ranked:
        if len(chosen) >= max_instruments:
            break
        if i not in chosen:
            chosen.append(i)
    return chosen


def run_v2(app, days: int = 120, max_instruments: int = 16, workers: int | None = None, folds: int = 5) -> dict:
    s = app.settings
    started = datetime.now(timezone.utc)
    insts = pick_universe(app, max_instruments)
    data, skipped = {}, []
    for inst in insts:
        try:
            app.history.backfill_futures(inst, "15m", max_days=days)
        except DataUnavailable as e:
            skipped.append(f"{inst.display} : historique indisponible ({e})")
            continue
        df15 = app.history.store.load(inst.key, "15m")
        df15 = df15[df15.index >= df15.index[-1] - pd.Timedelta(days=days)] if len(df15) else df15
        if len(df15) < WARMUP + 96 * 14:
            skipped.append(f"{inst.display} : {len(df15)} bougies 15m (au moins {WARMUP + 96 * 14} requises)")
            continue
        data[inst.key] = (inst, df15)
    if not data:
        return {"message": "DATA INSUFFISANTE — aucun historique exploitable", "ignores": skipped}
    btc = next((df for i, df in data.values() if i.base in ("BTC", "XBT")), None)
    eth = next((df for i, df in data.values() if i.base == "ETH"), None)
    be, br = regime_series(btc)
    ee, er = regime_series(eth)
    ctx = ContextSeries(be, br, ee, er)
    log.info("backtest : %d instruments, contexte BTC %d heures", len(data), len(br))
    jobs = [(df, inst, s, ctx) for inst, df in data.values()]
    workers = workers or max(1, (os.cpu_count() or 2))
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
            results = list(ex.map(_job, jobs))
    else:
        results = [_job(j) for j in jobs]
    cands = [c for r in results for c in r]
    arrays = {inst.key: Arrays.of(df) for inst, df in data.values()}
    p = BTParams(fee_pct=s.default_futures_taker_fee_pct, maker_fee_pct=s.default_futures_maker_fee_pct,
                 tp_split=s.tp_split, slippage_pct=float(os.environ.get("BACKTEST_SLIPPAGE_PCT", "0.03")), capital=100.0)
    rep = walk_forward_v2(cands, arrays, s, p, folds)
    rep.update({"instruments": {inst.display: len(df) for inst, df in data.values()}, "ignores": skipped,
                "jours": days, "lance_le": started.isoformat(timespec="seconds"),
                "duree_s": round((datetime.now(timezone.utc) - started).total_seconds())})
    return rep


def summary_text(rep: dict) -> str:
    """Résumé lisible (journal GitHub Actions / site)."""
    if "avant" not in rep:
        return "🛑 " + rep.get("message", "backtest impossible") + "".join(f"\n• {x}" for x in rep.get("ignores", [])[:10])
    def line(name, m):
        if not m.get("trades"):
            return f"{name:<22} 0 trade"
        pf = m.get("profit_factor")
        return (f"{name:<22} {m['trades']:>4} trades · win {m['win_rate_pct']:>5.1f} % · espérance {m['expectancy_r']:+.3f}R · "
                f"PF {pf if pf is not None else '—'} · DD max {m['max_drawdown_pct']:.1f} % · pire série {m['pire_serie_pertes']}")
    out = [f"BACKTEST WALK-FORWARD · hors échantillon {rep['periode_hors_echantillon']} · {len(rep.get('instruments', {}))} perpétuels",
           line("AVANT (ancien moteur)", rep["avant"]), line("APRÈS (moteur v2)", rep["apres"]),
           line("v2 sans preuve", rep["apres_sans_preuve"]),
           line("v2 prouvé dès 70/100", rep.get("apres_seuil_70", {})), "", "Combinaisons prouvées (stratégie|régime) :"]
    proved = [f"  {k} : {e['n']} trades, {e['expectancy_r']:+.3f}R, PF {e['profit_factor']}" for k, e in rep["edges"].items() if e.get("prouve")]
    out += proved or ["  aucune → le moteur v2 ne donnera AUCUN 🟢 (pas d'avantage démontré)"]
    return "\n".join(out)
