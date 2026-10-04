"""Backtest des stratégies techniques sur données historiques RÉELLES (historique local, CSV Kraken, API).

Principe (rapide et sans biais de look-ahead) :
  1. DÉTECTION : l'analyse complète (la même que le scanner) est rejouée bougie 15m par bougie 15m,
     uniquement avec les bougies clôturées à cet instant. Chaque setup confirmé devient un « candidat ».
  2. SIMULATION : chaque candidat est simulé sur les bougies suivantes (numpy) : ordre limite dans la
     zone, SL testé avant les TP dans une même bougie, TP 30/40/30, break-even après TP1 seulement si
     2 clôtures confirment, frais maker (limites) / taker (stop). Max 2 positions simultanées (plafond 2 %).
La détection est faite une fois ; la simulation peut être rejouée avec de nombreux jeux de paramètres
(→ optimiseur walk-forward).

Limites affichées : news non rejouées (catalyseur = 0), liquidité historique indisponible, cadre 5m
approximé par le 15m. Un résultat passé ne garantit rien.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..analysis.catalysts import CatalystContext
from ..analysis.htf import htf_context
from ..analysis.market_analysis import analyze_market
from ..analysis.regime import MarketContext, Regime, regime_from_analysis
from ..config import Settings
from ..market.candles import resample
from ..market.models import Instrument
from ..strategies import STRATEGIES
from ..strategies.base import TRADE

NOTES = ["news non rejouées (catalyseur = 0)", "liquidité historique non disponible",
         "le cadre 5m est approximé par le 15m"]


@dataclass
class BTParams:
    strategy: str = "all"
    risk_pct: float = 1.0
    tp_split: tuple[float, float, float] = (0.3, 0.4, 0.3)
    fee_pct: float = 0.40              # taker (stop, sortie forcée)
    maker_fee_pct: float | None = None  # ordres limite (entrée en zone, TP) ; défaut = 0,6 × taker
    sl_scale: float = 1.0
    be_after_tp1: bool = True          # BE après TP1 seulement si 2 clôtures 15m confirment
    pending_expiry_bars: int = 16      # 4 h
    warmup_bars: int = 400
    capital: float = 90.0
    score_threshold: float | None = None
    min_rr_tp2: float | None = None
    max_bars: int | None = None
    max_concurrent: int = 2
    slippage_pct: float = 0.0          # glissement sur les sorties au marché (stop, sortie forcée), en % du prix
    max_per_direction: int | None = None  # moteur v2 : cryptos corrélées → 1 position par sens à la fois

    @property
    def maker(self) -> float:
        return self.fee_pct * 0.6 if self.maker_fee_pct is None else self.maker_fee_pct


@dataclass
class Candidate:
    key: str
    asset_class: str
    i: int
    ts: pd.Timestamp
    strategy: str
    direction: str
    entry_low: float
    entry_high: float
    sl: float
    tps: tuple[float, ...]
    score: float                       # ancien score (moteur jusqu'au 04/10)
    r2: float
    quality: float = 0.0               # score qualité v2 /100
    regime: str = ""
    kill: tuple[str, ...] = ()         # coupe-circuits v2 (hors preuve statistique, appliquée au walk-forward)
    legacy_trade: bool = False         # l'ancien moteur aurait donné un 🟢
    btc: str = ""


@dataclass
class BTTrade:
    key: str
    strategy: str
    direction: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    r: float
    exit_reason: str
    regime: str = ""
    asset_class: str = ""
    quality: float = 0.0


@dataclass
class BTResult:
    trades: list[BTTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    params: BTParams | None = None
    bars: int = 0
    period: str = ""
    candidates: int = 0
    notes: list[str] = field(default_factory=list)

    def metrics(self) -> dict:
        return metrics(self.trades, self.equity_curve, self.period, self.bars)


def metrics(trades: list[BTTrade], equity: list[float] | None = None, period: str = "", bars: int = 0) -> dict:
    """Mesures d'une liste de trades (R nets de frais et de glissement). Aucune extrapolation."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "message": "aucun trade sur la période — pas de statistique"}
    ordered = sorted(trades, key=lambda t: t.exit_ts)
    rs = [t.r for t in ordered]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    if equity is None:
        equity = equity_curve(ordered, 100.0, 1.0)
    mdd = 0.0
    peak = equity[0]
    for e in equity:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100 if peak else 0)
    streak = worst = 0
    for r in rs:
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    sd = float(np.std(rs, ddof=1)) if n > 1 else 0.0
    mean = sum(rs) / n
    span_days = max(1.0, (ordered[-1].exit_ts - min(t.entry_ts for t in ordered)).total_seconds() / 86400)

    def group(key) -> dict:
        out: dict[str, dict] = {}
        for t in ordered:
            b = out.setdefault(key(t) or "?", {"trades": 0, "r_total": 0.0, "gagnants": 0})
            b["trades"] += 1
            b["r_total"] = round(b["r_total"] + t.r, 2)
            b["gagnants"] += t.r > 0
        for b in out.values():
            b["expectancy_r"] = round(b["r_total"] / b["trades"], 3)
            b["win_rate_pct"] = round(b.pop("gagnants") / b["trades"] * 100, 1)
        return out

    return {"trades": n, "win_rate_pct": round(len(wins) / n * 100, 1),
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown_pct": round(mdd, 2), "expectancy_r": round(mean, 3),
            "r_moyen_gagnant": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "r_moyen_perdant": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "pire_serie_pertes": worst, "r_total": round(sum(rs), 2),
            "rendement_net_pct": round((equity[-1] / equity[0] - 1) * 100, 2) if equity and equity[0] else None,
            "sharpe_par_trade": round(mean / sd, 3) if sd > 0 else None,
            "sharpe_annualise": round(mean / sd * float(np.sqrt(n / span_days * 365)), 2) if sd > 0 and n >= 30 else None,
            "capital_final": round(equity[-1], 2) if equity else None,
            "par_strategie": group(lambda t: t.strategy), "par_regime": group(lambda t: t.regime),
            "par_classe": group(lambda t: t.asset_class), "par_sens": group(lambda t: t.direction),
            "periode": period, "bougies_15m": bars}


def load_kraken_csv(path: str | Path) -> pd.DataFrame:
    """CSV OHLCVT Kraken (timestamp,open,high,low,close,volume,trades) sans en-tête."""
    df = pd.read_csv(path, header=None, names=["time", "open", "high", "low", "close", "volume", "trades"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float).sort_index()


# --------------------------------------------------------------------------- détection
def _closed_count(ends: np.ndarray, t_ns: int) -> int:
    return int(np.searchsorted(ends, t_ns, side="right"))


class ContextSeries:
    """Régimes BTC / ETH pré-calculés à chaque clôture 1h → contexte des altcoins à n'importe quel instant (sans look-ahead)."""

    def __init__(self, ends_ns: np.ndarray | None = None, btc: list[Regime] | None = None,
                 eth_ends_ns: np.ndarray | None = None, eth: list[Regime] | None = None):
        self.ends, self.btc = ends_ns, btc or []
        self.eth_ends, self.eth = eth_ends_ns, eth or []

    def at(self, t_ns: int) -> MarketContext:
        def pick(ends, regs):
            if ends is None or not len(regs):
                return None
            k = int(np.searchsorted(ends, t_ns, side="right")) - 1
            return regs[k] if k >= 0 else None
        return MarketContext(btc=pick(self.ends, self.btc), eth=pick(self.eth_ends, self.eth))


def regime_series(df15: pd.DataFrame | None) -> tuple[np.ndarray | None, list[Regime]]:
    """Régime calculé à chaque clôture 1h, uniquement avec les bougies clôturées à cet instant."""
    from ..analysis.regime import regime_from_frames
    from ..analysis.structure import analyze_structure
    if df15 is None or len(df15) < 15 * 4 * 24:
        return None, []
    h1 = resample(df15, 15, 60)
    h4 = resample(h1, 60, 240)
    d1 = resample(h1, 60, 1440)
    e4 = (h4.index + pd.Timedelta(hours=4)).as_unit("ns").asi8
    ed = (d1.index + pd.Timedelta(days=1)).as_unit("ns").asi8
    ends, regs, dcache = [], [], {}
    for k in range(60, len(h1)):
        t_end = h1.index[k].value + 3600 * 10**9
        n4 = _closed_count(e4, t_end)
        nd = _closed_count(ed, t_end)
        if n4 < 24:
            continue
        if nd not in dcache:
            dcache[nd] = analyze_structure(d1.iloc[:nd], "1d", 3, 3).trend if nd >= 30 else "inconnu"
        regs.append(regime_from_frames(h1.iloc[max(0, k - 599): k + 1], h4.iloc[max(0, n4 - 400): n4], dcache[nd]))
        ends.append(t_end)
    return np.asarray(ends, dtype="int64"), regs


def detect(df15: pd.DataFrame, inst: Instrument, settings: Settings, strategy: str = "all",
           warmup: int = 400, min_rr_tp2: float = 1.2, ctx: ContextSeries | None = None) -> list[Candidate]:
    """Rejoue l'analyse sur chaque bougie 15m clôturée ; retourne les setups confirmés qui passent les filtres durs,
    avec l'ancien score ET le score qualité v2 (+ régime, coupe-circuits). Les indices se réfèrent à `df15`."""
    if len(df15) < warmup + 20:
        return []
    h1 = resample(df15, 15, 60)
    h4 = resample(h1, 60, 240)
    d1 = resample(h1, 60, 1440)
    w1 = resample(d1, 1440, 10080) if len(d1) >= 14 else d1.iloc[:0]
    ends = {k: (df.index + pd.Timedelta(minutes=m)).as_unit("ns").asi8 for k, df, m in
            (("1h", h1, 60), ("4h", h4, 240), ("1d", d1, 1440), ("1w", w1, 10080))}
    det = settings.model_copy(update={"min_rr_tp2": min_rr_tp2, "require_proven_edge": False, "degraded_strategies": []})
    strategies = STRATEGIES if strategy == "all" else {strategy: STRATEGIES[strategy]}
    idx15 = df15.index
    out: list[Candidate] = []
    recent: dict[tuple, int] = {}
    htf_cache: tuple[int, int, object] | None = None
    for i in range(warmup, len(df15) - 1):
        t_end = idx15[i].value + 15 * 60 * 10**9
        n = {k: _closed_count(e, t_end) for k, e in ends.items()}
        if n["1h"] < 60 or n["4h"] < 12:
            continue
        w15 = df15.iloc[max(0, i - 499): i + 1]
        frames = {"5m": w15.iloc[-300:], "15m": w15, "1h": h1.iloc[max(0, n["1h"] - 600): n["1h"]],
                  "4h": h4.iloc[max(0, n["4h"] - 400): n["4h"]]}
        price = float(w15["close"].iloc[-1])
        try:
            a = analyze_market(inst, frames, price, None, CatalystContext(inst.base))
            if htf_cache is None or htf_cache[:2] != (n["1d"], n["1w"]):
                htf_cache = (n["1d"], n["1w"], htf_context(d1.iloc[:n["1d"]] if n["1d"] else None,
                                                          w1.iloc[:n["1w"]] if n["1w"] else None, price))
            a.htf = htf_cache[2]
            a.regime = regime_from_analysis(a)
            a.context = ctx.at(t_end) if ctx is not None else MarketContext()
        except (ValueError, IndexError, KeyError):
            continue
        for fn in strategies.values():
            try:
                setups = fn(a, det)
            except (ValueError, IndexError, KeyError, ZeroDivisionError):
                continue
            for st in setups:
                if not (st.hard_ok and st.confirmed) or len(st.tps) < 3:
                    continue
                sig = (st.strategy, st.direction, round(st.sl, 8))
                if sig in recent and i - recent[sig] <= 8:
                    continue  # même setup redétecté sur les bougies suivantes
                recent[sig] = i
                rs = st.r_multiples()
                out.append(Candidate(inst.key, inst.asset_class, i, idx15[i], st.strategy, st.direction,
                                     st.entry_low, st.entry_high, st.sl, tuple(st.tps[:3]), st.legacy_score,
                                     rs[1] if len(rs) > 1 else 0.0, quality=st.score, regime=st.regime,
                                     kill=tuple(st.kill), legacy_trade=st.legacy_status == TRADE, btc=st.btc_context))
    return out


# --------------------------------------------------------------------------- simulation
@dataclass
class Arrays:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    index: pd.DatetimeIndex

    @classmethod
    def of(cls, df: pd.DataFrame) -> "Arrays":
        return cls(*(df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")), df.index)


def simulate(cd: Candidate, A: Arrays, p: BTParams) -> tuple[float | None, int, str]:
    """Retourne (R net de frais ou None si non déclenché, indice de fin, raison)."""
    sign = 1 if cd.direction == "LONG" else -1
    e_lim = cd.entry_high if sign > 0 else cd.entry_low
    sl0 = e_lim - sign * abs(e_lim - cd.sl) * p.sl_scale
    ft, fm = p.fee_pct / 100, p.maker / 100
    n = len(A.c)
    start = cd.i + 1
    fill = None
    for j in range(start, min(start + p.pending_expiry_bars, n)):
        if (sign > 0 and A.l[j] <= cd.entry_high) or (sign < 0 and A.h[j] >= cd.entry_low):
            fill = j
            break
    if fill is None:
        return None, min(start + p.pending_expiry_bars, n - 1), "non déclenché"
    entry = min(A.o[fill], cd.entry_high) if sign > 0 else max(A.o[fill], cd.entry_low)
    risk = abs(entry - sl0)
    if risk <= 0:
        return None, fill, "invalide"
    r = -fm * entry / risk
    rem, sl, hit, confirm = 1.0, sl0, [False, False, False], 0
    tps = cd.tps
    for j in range(fill, n):
        adverse = A.l[j] if sign > 0 else A.h[j]
        if sign * (adverse - sl) <= 0:
            px = min(A.o[j], sl) if sign > 0 else max(A.o[j], sl)
            px *= 1 - sign * p.slippage_pct / 100          # un stop s'exécute au marché : un peu plus loin
            r += rem * (sign * (px - entry) - ft * px) / risk
            return r, j, "SL" if sl == sl0 else "SL ajusté"
        fav = A.h[j] if sign > 0 else A.l[j]
        for k in range(3):
            if hit[k] or sign * (fav - tps[k]) < 0:
                continue
            part = rem if k == 2 else min(p.tp_split[k], rem)
            r += part * (sign * (tps[k] - entry) - fm * tps[k]) / risk
            rem -= part
            hit[k] = True
        if rem <= 1e-9:
            return r, j, "TP3"
        if hit[0] and p.be_after_tp1 and sign * (sl - entry) < 0:
            confirm = confirm + 1 if sign * (A.c[j] - (entry + sign * 0.3 * risk)) > 0 else 0
            if confirm >= 2:
                sl = entry
    px = A.c[-1] * (1 - sign * p.slippage_pct / 100)
    r += rem * (sign * (px - entry) - ft * px) / risk
    return r, n - 1, "fin de données"


def evaluate(cands: list[Candidate], arrays: dict[str, Arrays], p: BTParams, threshold: float, min_rr: float,
             start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> list[BTTrade]:
    """Ancien moteur / optimiseur : ancien score ≥ seuil et R:R TP2 ≥ minimum."""
    return evaluate_rule(cands, arrays, p, lambda c: c.score >= threshold and c.r2 >= min_rr, start, end)


def evaluate_rule(cands: list[Candidate], arrays: dict[str, Arrays], p: BTParams, accept, start: pd.Timestamp | None = None,
                  end: pd.Timestamp | None = None) -> list[BTTrade]:
    """Joue dans l'ordre chronologique les candidats acceptés par `accept`, avec les contraintes du portefeuille :
    une position par instrument, `max_concurrent` positions au plus, `max_per_direction` cryptos par sens (v2)."""
    trades: list[BTTrade] = []
    busy: dict[str, pd.Timestamp] = {}
    open_pos: list[tuple[pd.Timestamp, str, str]] = []   # (fin, sens, classe)
    for cd in sorted(cands, key=lambda x: (x.ts, -x.quality)):
        if (start is not None and cd.ts < start) or (end is not None and cd.ts >= end):
            continue
        if not accept(cd):
            continue
        if cd.key in busy and cd.ts <= busy[cd.key]:
            continue
        open_pos = [o for o in open_pos if o[0] > cd.ts]
        if len(open_pos) >= p.max_concurrent:
            continue
        if p.max_per_direction is not None and cd.asset_class == "crypto" and \
                sum(1 for o in open_pos if o[1] == cd.direction and o[2] == "crypto") >= p.max_per_direction:
            continue
        A = arrays[cd.key]
        r, j, why = simulate(cd, A, p)
        busy[cd.key] = A.index[j]
        if r is None:
            continue
        open_pos.append((A.index[j], cd.direction, cd.asset_class))
        trades.append(BTTrade(cd.key, cd.strategy, cd.direction, cd.ts, A.index[j], round(r, 4), why,
                              cd.regime, cd.asset_class, cd.quality))
    return trades


def equity_curve(trades: list[BTTrade], capital: float, risk_pct: float) -> list[float]:
    eq = [capital]
    for t in sorted(trades, key=lambda x: x.exit_ts):
        eq.append(eq[-1] * (1 + t.r * risk_pct / 100))
    return eq


def run_backtest(df15: pd.DataFrame, inst: Instrument, settings: Settings, p: BTParams) -> BTResult:
    if p.max_bars:
        df15 = df15.iloc[-(p.max_bars + p.warmup_bars):]
    res = BTResult(params=p, bars=len(df15), notes=list(NOTES))
    if len(df15) < p.warmup_bars + 50:
        res.notes.append(f"historique insuffisant ({len(df15)} bougies 15m, {p.warmup_bars + 50} requises)")
        return res
    thr = settings.score_trade if p.score_threshold is None else p.score_threshold
    rr = settings.min_rr_tp2 if p.min_rr_tp2 is None else p.min_rr_tp2
    cands = detect(df15, inst, settings, p.strategy, p.warmup_bars, min(rr, 1.2))
    res.candidates = len(cands)
    res.trades = evaluate(cands, {inst.key: Arrays.of(df15)}, p, thr, rr)
    res.equity_curve = equity_curve(res.trades, p.capital, p.risk_pct)
    res.period = f"{df15.index[p.warmup_bars]:%Y-%m-%d} → {df15.index[-1]:%Y-%m-%d}"
    return res
