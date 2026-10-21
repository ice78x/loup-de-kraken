"""Backtest SWING sur bougies journalières Kraken (perpétuels), avec frais, glissement et FUNDING réel.

Simulation jour par jour, une position par instrument :
  - entrée à l'ouverture du lendemain du signal (+ glissement), frais taker ;
  - stop touché dans la journée → sortie au stop (ou à l'ouverture si le prix a sauté le stop), + glissement ;
  - « tp30 » : 30 % vendus à +2R (ordre limite, frais maker), puis stop au point mort ;
  - funding Kraken payé/reçu chaque jour sur la part restante (LONG paie si le taux est positif) ;
  - stop suiveur mis à jour à chaque clôture (canal de sortie), jamais reculé.
Walk-forward : la variante jouée sur une période est choisie avec les trades TERMINÉS avant cette période.
Aucune donnée inventée : funding absent → compté 0 et signalé (couverture en %).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..backtest.engine import BTTrade, equity_curve, metrics
from . import rules as R


@dataclass
class SwingParams:
    fee_taker_pct: float = 0.05
    fee_maker_pct: float = 0.02
    slippage_pct: float = 0.05
    folds: int = 5
    min_trades_select: int = 30
    min_oos_trades: int = 20
    min_pf: float = 1.2
    open_risk_cap: float = 2.0      # % du capital (règle du club), 1 % par trade


@dataclass
class SwingTrade(BTTrade):
    days: int = 0
    funding_r: float = 0.0
    risk_path: dict = field(default_factory=dict)
    tier: int = 1                                   # mise conseillée 1/4…4/4 (rules.tier, critères fixés le 21/10)   # date (jour) → part du risque initial encore exposée (0..1)


def daily_funding(rates: list[dict], index: pd.DatetimeIndex) -> pd.Series:
    """Taux de funding Kraken (relatifs, PAR HEURE) → coût relatif par jour UTC aligné sur `index`.
    Chaque taux s'applique jusqu'au taux suivant (au plus 24 h) : coût = Σ taux × durée en heures."""
    if not rates:
        return pd.Series(np.nan, index=index)
    df = pd.DataFrame([{"ts": pd.Timestamp(r["timestamp"]), "rate": float(r.get("relativeFundingRate") or 0.0)}
                       for r in rates if r.get("timestamp") is not None]).sort_values("ts")
    if df.empty:
        return pd.Series(np.nan, index=index)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    nxt = df["ts"].shift(-1)
    hours = ((nxt - df["ts"]).dt.total_seconds() / 3600).clip(upper=24)
    hours = hours.fillna(float(hours.median()) if hours.notna().any() else 1.0)   # dernier taux : pas habituel
    df["cost"] = df["rate"] * hours
    per_day = df.groupby(df["ts"].dt.floor("D"))["cost"].sum()
    out = per_day.reindex(index.floor("D"))
    out.index = index
    return out


def simulate(df: pd.DataFrame, funding: pd.Series | None, key: str, asset_class: str, variant: str, mgmt: str,
             sides: str, p: SwingParams, btc_ok: pd.Series | None = None) -> list[SwingTrade]:
    v = R.VARIANTS[variant]
    tiers = R.tier_series(df, btc_ok)
    ch = R.channels(df, v["entry"], v["exit"])
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    hi_e, lo_e = ch["hi_entry"].to_numpy(float), ch["lo_entry"].to_numpy(float)
    lo_x, hi_x, atr = ch["lo_exit"].to_numpy(float), ch["hi_exit"].to_numpy(float), ch["atr"].to_numpy(float)
    fund = (funding.to_numpy(float) if funding is not None else np.full(len(df), np.nan))
    idx = df.index
    slip, ft, fm = p.slippage_pct / 100, p.fee_taker_pct / 100, p.fee_maker_pct / 100
    name = R.combo_name(variant, mgmt, sides)
    trades: list[SwingTrade] = []
    pos = None
    pending = None
    start = v["entry"] + R.ATR_N + 1
    for i in range(start, len(df)):
        if pending is not None and pos is None:
            sign = 1 if pending == "LONG" else -1
            entry = o[i] * (1 + sign * slip)
            stop0 = entry - sign * R.STOP_N * atr[i - 1]
            risk = abs(entry - stop0)
            if risk > 0 and np.isfinite(risk):
                pos = {"dir": pending, "sign": sign, "entry": entry, "stop": stop0, "risk": risk, "rem": 1.0,
                       "r": -ft * entry / risk, "fund_r": 0.0, "i0": i, "partial": False, "path": {},
                       "tier": int(tiers[i - 1]) if pending == "LONG" else 1}
            pending = None
        if pos is not None:
            sign, entry, risk = pos["sign"], pos["entry"], pos["risk"]
            adverse = l[i] if sign > 0 else h[i]
            if sign * (adverse - pos["stop"]) <= 0:
                px = (min(o[i], pos["stop"]) if sign > 0 else max(o[i], pos["stop"])) * (1 - sign * slip)
                pos["r"] += pos["rem"] * (sign * (px - entry) - ft * px) / risk
                trades.append(_close(pos, i, idx, key, asset_class, name, "stop"))
                pos = None
            else:
                if mgmt == "tp30" and not pos["partial"]:
                    tp = entry + sign * R.TP_PARTIAL_R * risk
                    fav = h[i] if sign > 0 else l[i]
                    if sign * (fav - tp) >= 0:
                        px = tp if sign * (o[i] - tp) < 0 else o[i]
                        pos["r"] += R.TP_PARTIAL_SHARE * (sign * (px - entry) - fm * px) / risk
                        pos["rem"] -= R.TP_PARTIAL_SHARE
                        pos["partial"] = True
                        pos["stop"] = max(pos["stop"], entry) if sign > 0 else min(pos["stop"], entry)
                if np.isfinite(fund[i]):
                    f = pos["rem"] * sign * fund[i] * c[i] / risk
                    pos["r"] -= f
                    pos["fund_r"] -= f
                trail = lo_x[i] if sign > 0 else hi_x[i]
                if np.isfinite(trail):
                    pos["stop"] = max(pos["stop"], trail) if sign > 0 else min(pos["stop"], trail)
                pos["path"][idx[i].normalize()] = pos["rem"] * max(0.0, sign * (entry - pos["stop"])) / risk
        if pos is None and pending is None and i + 1 < len(df):
            if np.isfinite(hi_e[i]) and c[i] > hi_e[i] and not c[i - 1] > hi_e[i - 1]:
                pending = "LONG"
            elif sides == "both" and np.isfinite(lo_e[i]) and c[i] < lo_e[i] and not c[i - 1] < lo_e[i - 1]:
                pending = "SHORT"
    if pos is not None:
        sign = pos["sign"]
        px = c[-1] * (1 - sign * slip)
        pos["r"] += pos["rem"] * (sign * (px - pos["entry"]) - ft * px) / pos["risk"]
        trades.append(_close(pos, len(df) - 1, idx, key, asset_class, name, "fin de données"))
    return trades


def _close(pos, i, idx, key, asset_class, name, why) -> SwingTrade:
    return SwingTrade(key, name, pos["dir"], idx[pos["i0"]], idx[i], float(pos["r"]), why, "", asset_class, 0.0,
                      days=int(i - pos["i0"]) + 1, funding_r=float(pos["fund_r"]), risk_path=pos["path"], tier=pos.get("tier", 1))


def all_trades(data: dict[str, tuple[str, pd.DataFrame, pd.Series | None]], p: SwingParams) -> dict[str, list[SwingTrade]]:
    """{combo: trades sur tous les instruments}. data = {key: (classe, bougies 1j, funding/jour)}."""
    out: dict[str, list[SwingTrade]] = {}
    btc = next((df for key, (_, df, _) in data.items() if key.endswith("PF_XBTUSD")), None)
    btc_ok = R.above_sma(btc) if btc is not None else None
    for variant in R.VARIANTS:
        for mgmt in R.MGMT:
            for sides in R.SIDES:
                name = R.combo_name(variant, mgmt, sides)
                out[name] = [t for key, (cls, df, fund) in data.items()
                             for t in simulate(df, fund, key, cls, variant, mgmt, sides, p, btc_ok)]
    return out


def _stats(trades: list[SwingTrade]) -> dict:
    if not trades:
        return {"n": 0}
    rs = [t.r for t in trades]
    w, lo = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    return {"n": len(rs), "expectancy_r": round(float(np.mean(rs)), 3), "win_rate_pct": round(len(w) / len(rs) * 100, 1),
            "profit_factor": round(sum(w) / -sum(lo), 2) if lo and sum(lo) < 0 else (99.0 if w else None),
            "jours_moyens": round(float(np.mean([t.days for t in trades])), 1),
            "funding_r_moyen": round(float(np.mean([t.funding_r for t in trades])), 3),
            "meilleur_r": round(max(rs), 2), "pire_r": round(min(rs), 2)}


def by_year(trades: list[SwingTrade]) -> dict:
    out: dict[str, list[SwingTrade]] = {}
    for t in trades:
        out.setdefault(str(t.entry_ts.year), []).append(t)
    return {y: _stats(ts) for y, ts in sorted(out.items())}


def portfolio(trades: list[SwingTrade], cap_pct: float, risk_pct=1.0) -> list[SwingTrade]:
    """Règles du club : risque par trade (`risk_pct` : nombre, ou fonction trade → %), risque ouvert cumulé ≤ cap_pct
    (risque d'un trade = distance encore exposée jusqu'à son stop actuel ; un stop au point mort libère la place),
    une position par instrument."""
    rk = risk_pct if callable(risk_pct) else (lambda t: risk_pct)
    taken: list[SwingTrade] = []
    for t in sorted(trades, key=lambda x: (x.entry_ts, x.key)):
        day = t.entry_ts.normalize()
        open_ = [x for x in taken if x.entry_ts <= t.entry_ts < x.exit_ts]
        if any(x.key == t.key for x in open_):
            continue
        prev = day - pd.Timedelta(days=1)
        used = sum(rk(x) * x.risk_path.get(prev, 1.0) for x in open_)
        if used + rk(t) <= cap_pct + 1e-9:
            taken.append(t)
    return taken


def monthly(port: list[SwingTrade], rk) -> dict:
    """Résultat de chaque mois (en % du capital, trades comptés au mois de leur sortie, capital composé)."""
    if not port:
        return {}
    by: dict[str, float] = {}
    for t in sorted(port, key=lambda x: x.exit_ts):
        m = f"{t.exit_ts:%Y-%m}"
        by[m] = (1 + by.get(m, 0.0) / 100) * (1 + t.r * rk(t) / 100) * 100 - 100
    first, last = min(t.entry_ts for t in port), max(t.exit_ts for t in port)
    months = [f"{d:%Y-%m}" for d in pd.period_range(first, last, freq="M").to_timestamp()]
    vals = [round(by.get(m, 0.0), 2) for m in months]
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    return {"mois": len(vals), "mois_positifs": pos, "mois_negatifs": neg, "mois_sans_trade_clos": len(vals) - pos - neg,
            "pct_mois_positifs": round(pos / len(vals) * 100, 1), "pire_mois_pct": min(vals), "meilleur_mois_pct": max(vals),
            "detail": dict(zip(months, vals))}


def scenario(trades: list[SwingTrade], cap_pct: float, risk_pct, period: str) -> dict:
    """Ce qu'aurait vécu un membre : portefeuille aux règles du club, capital 100, risque par trade `risk_pct`
    (nombre, ou fonction trade → % pour la mise par paliers 1/4…4/4)."""
    rk = risk_pct if callable(risk_pct) else (lambda t: risk_pct)
    port = portfolio(trades, cap_pct, rk)
    if not port:
        return {"trades": 0}
    eq = [100.0]
    for t in sorted(port, key=lambda x: x.exit_ts):
        eq.append(eq[-1] * (1 + t.r * rk(t) / 100))
    m = metrics(port, equity=eq, period=period)
    months = max(1.0, (max(t.exit_ts for t in port) - min(t.entry_ts for t in port)).days / 30.44)
    keep = ("trades", "expectancy_r", "win_rate_pct", "profit_factor", "max_drawdown_pct", "pire_serie_pertes",
            "rendement_net_pct", "capital_final")
    out = {k: m.get(k) for k in keep}
    out["trades_par_mois"] = round(len(port) / months, 1)
    out["par_annee"] = {y: {"n": st["n"], "expectancy_r": st.get("expectancy_r")} for y, st in by_year(port).items()}
    out["mensuel"] = monthly(port, rk)
    return out


def by_tier(trades: list[SwingTrade]) -> dict:
    return {str(k): _stats([t for t in trades if t.tier == k]) for k in (1, 2, 3, 4)}


def variant_proof(ts: list[SwingTrade], oos_start: pd.Timestamp, p: SwingParams) -> dict:
    """Preuve d'UNE variante fixée à l'avance : tout l'historique ET la période hors échantillon (après la 1re tranche)."""
    allst, oos = _stats(ts), _stats([t for t in ts if t.entry_ts >= oos_start])
    ok = bool(allst.get("n", 0) >= p.min_trades_select and allst.get("expectancy_r", 0) > 0
              and (allst.get("profit_factor") or 0) >= p.min_pf
              and oos.get("n", 0) >= p.min_oos_trades and oos.get("expectancy_r", 0) > 0)
    return {"tout": allst, "hors_echantillon": oos, "prouve": ok}


def walk_forward(trades_by_combo: dict[str, list[SwingTrade]], p: SwingParams) -> dict:
    allt = [t for ts in trades_by_combo.values() for t in ts]
    if not allt:
        return {"message": "aucun trade — pas de statistique"}
    t0, t1 = min(t.entry_ts for t in allt), max(t.exit_ts for t in allt)
    cuts = list(pd.date_range(t0, t1, periods=p.folds + 1))
    oos: list[SwingTrade] = []
    rows = []
    for k in range(1, p.folds):
        start, end = cuts[k], cuts[k + 1]
        best, best_e = None, None
        for name, ts in trades_by_combo.items():
            past = [t for t in ts if t.exit_ts < start]
            if len(past) < p.min_trades_select:
                continue
            e = float(np.mean([t.r for t in past]))
            if best_e is None or e > best_e:
                best, best_e = name, e
        played = [t for t in trades_by_combo.get(best, []) if start <= t.entry_ts < end] if best and best_e > 0 else []
        oos += played
        rows.append({"debut": f"{start:%Y-%m-%d}", "fin": f"{end:%Y-%m-%d}", "variante": best,
                     "esperance_passee": None if best_e is None else round(best_e, 3),
                     "joue": bool(best and best_e > 0), **{"oos": _stats(played)}})
    return {"periode_hors_echantillon": f"{cuts[1]:%Y-%m-%d} → {cuts[-1]:%Y-%m-%d}", "tranches": rows,
            "oos": _stats(oos), "oos_trades": oos}


def report(data: dict[str, tuple[str, pd.DataFrame, pd.Series | None]], p: SwingParams) -> dict:
    trades = all_trades(data, p)
    classes = sorted({cls for cls, _, _ in data.values()})
    rep: dict = {"type": "swing", "variantes": {}, "par_classe": {}}
    for name, ts in trades.items():
        rep["variantes"][name] = {"tout": _stats(ts), **{cls: _stats([t for t in ts if t.asset_class == cls]) for cls in classes}}
    for cls in classes:
        by = {name: [t for t in ts if t.asset_class == cls] for name, ts in trades.items()}
        wf = walk_forward(by, p)
        oos = wf.pop("oos_trades", [])
        final = max(((n, ts) for n, ts in by.items() if len(ts) >= p.min_trades_select),
                    key=lambda x: float(np.mean([t.r for t in x[1]])), default=(None, []))
        fs = _stats(final[1])
        o = wf.get("oos", {})
        prouve = bool(final[0] and fs.get("expectancy_r", 0) > 0 and (fs.get("profit_factor") or 0) >= p.min_pf
                      and o.get("n", 0) >= p.min_oos_trades and o.get("expectancy_r", 0) > 0)
        port = portfolio(oos, p.open_risk_cap) if oos else []
        allc = [t for ts in by.values() for t in ts]
        oos_start = (list(pd.date_range(min(t.entry_ts for t in allc), max(t.exit_ts for t in allc), periods=p.folds + 1))[1]
                     if allc else None)
        # 21/10 : plus de signaux sans tricher — les deux longueurs de canal (20 et 55 jours) jouées ensemble, chacune
        # devant être prouvée seule ; et 0,5 % de risque par position (4 positions dans les 2 % au lieu de 2).
        detail, prouvees = {}, []
        if final[0] and oos_start is not None:
            _, mgmt, sides = R.parse_combo(final[0])
            for v in R.VARIANTS:
                name = R.combo_name(v, mgmt, sides)
                detail[name] = variant_proof(by.get(name, []), oos_start, p)
                if detail[name]["prouve"]:
                    prouvees.append(name)
        scen = {}
        if oos_start is not None and final[0]:
            per = f"{oos_start:%Y-%m-%d} → {max(t.exit_ts for t in allc):%Y-%m-%d}"
            sets = {"55_jours": [final[0]] if "55" in final[0] else [], "20_et_55_jours": list(detail)}
            for label, names in sets.items():
                pool = [t for n in names for t in by.get(n, []) if t.entry_ts >= oos_start]
                for risk in (1.0, 0.5):
                    scen[f"{label}|{risk:g}%"] = scenario(pool, p.open_risk_cap, risk, per) if pool else {"trades": 0}
            # 21/10 : mise par paliers (1/4 = 0,5 % … 4/4 = 2 %) selon des critères fixés à l'avance (rules.tier_series)
            pool = [t for n in detail for t in by.get(n, []) if t.entry_ts >= oos_start]
            if pool:
                for cap in (2.0, 4.0):
                    scen[f"20_et_55_jours|paliers|cap{cap:g}%"] = scenario(pool, cap, lambda t: R.TIER_RISK[t.tier], per)
                    scen[f"20_et_55_jours|0.5%|cap{cap:g}%"] = scenario(pool, cap, 0.5, per)
                    scen[f"20_et_55_jours|1%|cap{cap:g}%"] = scenario(pool, cap, 1.0, per)
        rep["par_classe"][cls] = {
            "walk_forward": wf, "variante_retenue": final[0], "stats_variante": fs, "par_annee": by_year(final[1]),
            "prouve": prouve, "variantes_prouvees": prouvees if prouve else [], "variantes_detail": detail,
            "scenarios_club": scen,
            "par_palier_hors_echantillon": by_tier([t for n in detail for t in by.get(n, []) if oos_start is not None and t.entry_ts >= oos_start]),
            "par_palier_tout": by_tier([t for n in detail for t in by.get(n, [])]),
            "portefeuille_club": metrics(port, period=wf.get("periode_hors_echantillon", "")) if port else {"trades": 0},
        }
    return rep
