"""Optimiseur walk-forward : utilise tout l'historique local pour régler chaque stratégie, par classe d'actif.

Méthode (anti sur-optimisation) :
  - grille volontairement petite : seuil de score {50…75} × R:R minimal au TP2 {1,2 ; 1,5 ; 2,0} ;
  - walk-forward en fenêtre croissante : on choisit les paramètres sur le passé, on les TESTE sur la
    période suivante jamais vue, et on répète (4 plis) ;
  - seuls les résultats hors échantillon (OOS) décident :
        adopté      : ≥ N trades OOS et espérance OOS > 0      → le scanner utilise ces réglages
        désactivé   : ≥ N trades OOS et espérance OOS < −0,1R → la stratégie est bloquée sur cette classe
        non démontré: sinon → réglages par défaut, et le signal l'indique.
Rien n'est présenté comme une garantie : c'est une mesure sur le passé.
"""
from __future__ import annotations

import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

from ..config import Settings
from ..database.db import Database
from ..market.models import Instrument
from ..strategies import STRATEGIES
from .engine import Arrays, BTParams, Candidate, detect, evaluate, metrics

log = logging.getLogger(__name__)

GRID_SCORE = (50, 55, 60, 65, 70, 75)
GRID_RR = (1.2, 1.5, 2.0)

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_params (
    asset_class TEXT NOT NULL, strategy TEXT NOT NULL, status TEXT NOT NULL,
    score_threshold REAL, min_rr_tp2 REAL,
    oos_trades INTEGER, oos_expectancy REAL, oos_win_rate REAL, oos_pf REAL,
    is_trades INTEGER, is_expectancy REAL, instruments INTEGER, period TEXT, updated_at TEXT,
    PRIMARY KEY (asset_class, strategy)
);
"""
ADOPTED, DISABLED, UNPROVEN = "adopté", "désactivé", "non démontré"


@dataclass
class StrategyEdge:
    asset_class: str
    strategy: str
    status: str
    score_threshold: float
    min_rr_tp2: float
    oos_trades: int
    oos_expectancy: float | None
    oos_win_rate: float | None
    oos_pf: float | None
    is_trades: int
    is_expectancy: float | None
    instruments: int
    period: str
    updated_at: str

    def note(self) -> str:
        if self.oos_trades == 0:
            return f"historique : aucune occurrence testée ({self.strategy}, {self.asset_class})"
        pf = f" · PF {self.oos_pf}" if self.oos_pf is not None else ""
        return (f"historique hors échantillon : {self.oos_trades} trades · {self.oos_expectancy:+.2f}R/trade · "
                f"win {self.oos_win_rate:.0f} %{pf} → {self.status}")


def ensure_schema(db: Database) -> None:
    with db._lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def load_edges(db: Database) -> dict[tuple[str, str], StrategyEdge]:
    ensure_schema(db)
    return {(r["asset_class"], r["strategy"]): StrategyEdge(**r) for r in db.query("SELECT * FROM strategy_params")}


def _objective(trades) -> float:
    n = len(trades)
    if n < 5:
        return -math.inf
    return sum(t.r for t in trades) / n * math.sqrt(n)


def _best(cands, arrays, p, end=None) -> tuple[float, float] | None:
    best, best_val = None, -math.inf
    for thr in GRID_SCORE:
        for rr in GRID_RR:
            v = _objective(evaluate(cands, arrays, p, thr, rr, end=end))
            if v > best_val:
                best, best_val = (thr, rr), v
    return best


def walk_forward(cands: list[Candidate], arrays: dict[str, Arrays], p: BTParams, default: tuple[float, float],
                 folds: int = 4) -> tuple[tuple[float, float], list, list, str]:
    if not cands:
        return default, [], [], ""
    t0 = min(c.ts for c in cands)
    t1 = max(A.index[-1] for A in arrays.values())
    edges = pd.date_range(t0, t1, periods=folds + 2)
    oos = []
    for k in range(1, folds + 1):
        chosen = _best(cands, arrays, p, end=edges[k]) or default
        oos += evaluate(cands, arrays, p, *chosen, start=edges[k], end=edges[k + 1])
    final = _best(cands, arrays, p) or default
    is_trades = evaluate(cands, arrays, p, *final)
    return final, oos, is_trades, f"{t0:%Y-%m-%d} → {t1:%Y-%m-%d}"


def _detect_job(args) -> list[Candidate]:
    df15, inst, settings, warmup = args
    try:
        return detect(df15, inst, settings, "all", warmup, 1.2)
    except Exception as e:  # un instrument en erreur ne doit pas arrêter l'optimisation
        log.warning("détection impossible sur %s : %s", inst.display, e)
        return []


def optimize(db: Database, settings: Settings, data: dict[str, tuple[Instrument, pd.DataFrame]],
             fees: dict[str, tuple[float, float]], workers: int | None = None) -> dict:
    """data : {clé instrument: (instrument, historique 15m)}. fees : {clé: (taker %, maker %)}."""
    ensure_schema(db)
    warmup = 400
    report: dict = {"instruments": {}, "resultats": [], "ignores": []}
    jobs = []
    for key, (inst, df15) in data.items():
        df15 = df15.iloc[-(settings.optimizer_max_bars + warmup):]
        if len(df15) < warmup + 500:
            report["ignores"].append(f"{inst.display} : {len(df15)} bougies 15m (≥ {warmup + 500} requises)")
            continue
        jobs.append((df15, inst, settings, warmup))
        report["instruments"][inst.display] = len(df15)
    if not jobs:
        return report
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2) - 1))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_detect_job, jobs))
    else:
        results = [_detect_job(j) for j in jobs]
    by_class: dict[str, list[Candidate]] = {}
    arrays: dict[str, Arrays] = {}
    for (df15, inst, _, _), cands in zip(jobs, results):
        arrays[inst.key] = Arrays.of(df15)
        by_class.setdefault(inst.asset_class, []).extend(cands)
    default = (settings.score_trade, settings.min_rr_tp2)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for aclass, cands in by_class.items():
        n_inst = len({c.key for c in cands}) or len([j for j in jobs if j[1].asset_class == aclass])
        # frais : moyenne des instruments de la classe
        keys = [j[1].key for j in jobs if j[1].asset_class == aclass]
        taker = sum(fees.get(k, (0.4, 0.25))[0] for k in keys) / max(1, len(keys))
        maker = sum(fees.get(k, (0.4, 0.25))[1] for k in keys) / max(1, len(keys))
        p = BTParams(fee_pct=taker, maker_fee_pct=maker, tp_split=settings.tp_split)
        arr = {k: arrays[k] for k in keys}
        for strat in STRATEGIES:
            sc = [c for c in cands if c.strategy == strat]
            final, oos, is_tr, period = walk_forward(sc, arr, p, default)
            mo, mi = metrics(oos), metrics(is_tr)
            n_oos = mo["trades"]
            exp = mo.get("expectancy_r")
            if n_oos >= settings.optimizer_min_trades and exp is not None and exp > 0:
                status = ADOPTED
            elif n_oos >= settings.optimizer_min_trades and exp is not None and exp < -0.1:
                status = DISABLED
            else:
                status = UNPROVEN
                final = default
            edge = StrategyEdge(aclass, strat, status, float(final[0]), float(final[1]), n_oos, exp,
                                mo.get("win_rate_pct"), mo.get("profit_factor"), mi["trades"], mi.get("expectancy_r"),
                                n_inst, period, now)
            db.execute("INSERT OR REPLACE INTO strategy_params VALUES "
                       "(:asset_class,:strategy,:status,:score_threshold,:min_rr_tp2,:oos_trades,:oos_expectancy,"
                       ":oos_win_rate,:oos_pf,:is_trades,:is_expectancy,:instruments,:period,:updated_at)", asdict(edge))
            report["resultats"].append(edge)
            log.info("OPTIMISER %s/%s : %s (OOS %d trades, %s R)", aclass, strat, status, n_oos, exp)
    return report
