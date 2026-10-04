"""Backtest walk-forward du moteur v2, comparé à l'ancien moteur sur EXACTEMENT les mêmes données.

1. Détection une seule fois (engine.detect) : chaque setup confirmé qui passe les filtres durs devient un candidat,
   avec l'ancien score, le score qualité v2, le régime et les coupe-circuits v2.
2. La période est coupée en K tranches chronologiques. La tranche 1 sert seulement à apprendre.
3. Pour chaque tranche k ≥ 2 (hors échantillon) :
     AVANT        ancien moteur : ancien score ≥ 60, filtres durs, confirmé (règle fixe, rien d'appris)
     APRÈS        moteur v2 : qualité ≥ 80, aucun coupe-circuit, ET combinaison stratégie × régime dont l'espérance
                  était positive sur les tranches PRÉCÉDENTES uniquement (preuve statistique sans regarder le futur)
     APRÈS (sans preuve)  v2 sans l'exigence de preuve, pour voir ce que la preuve apporte
4. Les « edges » finaux (toutes tranches) alimentent le scanner : sans edge prouvé, pas de 🟢.

Les seuils (80, 70, R:R 1,5…) sont fixés à l'avance, pas optimisés sur ces données. Un résultat passé ne garantit rien.
"""
from __future__ import annotations

import pandas as pd

from ..config import Settings
from ..strategies.quality import edge_key
from .engine import Arrays, BTParams, BTTrade, Candidate, evaluate_rule, metrics, simulate

LEGACY_THRESHOLD = 60


def _edge_trades(cands: list[Candidate], arrays: dict[str, Arrays], p: BTParams, s: Settings,
                 start=None, end=None) -> list[tuple[str, float]]:
    """Base d'apprentissage des edges : tous les candidats v2 sans coupe-circuit et de qualité ≥ seuil 🟡,
    simulés un par un (sans contrainte de portefeuille, pour mesurer la stratégie elle-même)."""
    out = []
    seen: dict[str, pd.Timestamp] = {}
    for cd in sorted(cands, key=lambda c: c.ts):
        if (start is not None and cd.ts < start) or (end is not None and cd.ts >= end):
            continue
        if cd.kill or cd.quality < s.score_watch:
            continue
        if cd.key in seen and cd.ts <= seen[cd.key]:
            continue
        r, j, _ = simulate(cd, arrays[cd.key], p)
        seen[cd.key] = arrays[cd.key].index[j]
        if r is not None:
            out.append((edge_key(cd.strategy, cd.regime), r))
    return out


def edge_table(pairs: list[tuple[str, float]]) -> dict[str, dict]:
    tab: dict[str, list[float]] = {}
    for k, r in pairs:
        tab.setdefault(k, []).append(r)
    out = {}
    for k, rs in tab.items():
        w, l = [r for r in rs if r > 0], [r for r in rs if r <= 0]
        out[k] = {"n": len(rs), "expectancy_r": round(sum(rs) / len(rs), 3), "win_rate_pct": round(len(w) / len(rs) * 100, 1),
                  "profit_factor": round(sum(w) / -sum(l), 2) if l and sum(l) < 0 else (None if not w else 99.0)}
    return out


def proven(e: dict | None, s: Settings) -> bool:
    if not e or e.get("n", 0) < s.edge_min_trades:
        return False
    if (e.get("expectancy_r") or 0) <= 0 or (e.get("profit_factor") or 0) < s.edge_min_pf:
        return False
    oos_n, oos_e = e.get("oos_n", 0), e.get("oos_expectancy_r")
    return not (oos_n >= 5 and oos_e is not None and oos_e <= 0)


def walk_forward_v2(cands: list[Candidate], arrays: dict[str, Arrays], s: Settings, p: BTParams,
                    folds: int = 5) -> dict:
    if not cands:
        return {"message": "aucun candidat détecté — pas de statistique", "folds": []}
    t0 = min(c.ts for c in cands)
    t1 = max(A.index[-1] for A in arrays.values())
    cuts = list(pd.date_range(t0, t1, periods=folds + 1))
    p_old = BTParams(**{**p.__dict__, "max_per_direction": None})
    p_new = BTParams(**{**p.__dict__, "max_per_direction": s.max_trades_per_direction_crypto})

    def old_rule(c: Candidate) -> bool:
        return c.legacy_trade and c.score >= LEGACY_THRESHOLD

    def v2_rule(c: Candidate) -> bool:
        return not c.kill and c.quality >= s.score_trade

    avant: list[BTTrade] = []
    apres: list[BTTrade] = []
    sans_preuve: list[BTTrade] = []
    oos_by_key: dict[str, list[float]] = {}
    fold_rows = []
    for k in range(1, folds):
        start, end = cuts[k], cuts[k + 1]
        learned = edge_table(_edge_trades(cands, arrays, p, s, end=start))
        allowed = {key for key, e in learned.items() if proven(e, s)}
        fa = evaluate_rule(cands, arrays, p_old, old_rule, start, end)
        fn = evaluate_rule(cands, arrays, p_new, lambda c: v2_rule(c) and edge_key(c.strategy, c.regime) in allowed, start, end)
        fs = evaluate_rule(cands, arrays, p_new, v2_rule, start, end)
        avant += fa
        apres += fn
        sans_preuve += fs
        for t in fn:
            oos_by_key.setdefault(edge_key(t.strategy, t.regime), []).append(t.r)
        fold_rows.append({"debut": f"{start:%Y-%m-%d}", "fin": f"{end:%Y-%m-%d}", "combinaisons_prouvees": sorted(allowed),
                          "avant": _short(fa), "apres": _short(fn), "apres_sans_preuve": _short(fs)})
    final = edge_table(_edge_trades(cands, arrays, p, s))
    for key, e in final.items():
        rs = oos_by_key.get(key, [])
        e["oos_n"] = len(rs)
        e["oos_expectancy_r"] = round(sum(rs) / len(rs), 3) if rs else None
        e["prouve"] = proven(e, s)
    period = f"{cuts[1]:%Y-%m-%d} → {cuts[-1]:%Y-%m-%d}"
    return {
        "periode_hors_echantillon": period, "periode_totale": f"{t0:%Y-%m-%d} → {t1:%Y-%m-%d}",
        "tranches": folds, "candidats": len(cands),
        "avant": metrics(avant, period=period), "apres": metrics(apres, period=period),
        "apres_sans_preuve": metrics(sans_preuve, period=period),
        "folds": fold_rows, "edges": final,
        "regles": {"avant": f"ancien score ≥ {LEGACY_THRESHOLD}, filtres durs, confirmé",
                   "apres": f"qualité ≥ {s.score_trade}/100, aucun coupe-circuit (régime, BTC, conflit 4h/1h, R:R net ≥ "
                            f"{s.min_net_rr_tp2_v2:g}), combinaison stratégie×régime prouvée sur le passé "
                            f"(≥ {s.edge_min_trades} trades, espérance > 0, PF ≥ {s.edge_min_pf:g})",
                   "frais": f"taker {p.fee_pct:g} % · maker {p.maker:g} % · glissement {p.slippage_pct:g} % sur les stops"},
    }


def _short(trades: list[BTTrade]) -> dict:
    m = metrics(trades)
    return {k: m.get(k) for k in ("trades", "win_rate_pct", "expectancy_r", "profit_factor", "max_drawdown_pct", "r_total")}
