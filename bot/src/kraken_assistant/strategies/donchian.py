"""Stratégie CANAL (méthode « Turtle » / suivi de tendance Donchian), ajoutée le 13/10.

Idée publique et documentée : acheter quand le prix clôture au-dessus du plus haut des N dernières périodes
(vendre sous le plus bas), stop à 2 × la volatilité (2N des Turtles). C'est la base des fonds de suivi de tendance ;
des études récentes la testent aussi sur les cryptos (canaux de Donchian sur les plus liquides).
Ici, version adaptée au club : bougies 4h, canal 20 bougies (≈ 3,3 jours), stop 2 × ATR 4h, objectifs 1,5R / 3R / 5R
(30/40/30, stop au point mort après TP1). Tous ces chiffres sont fixés à l'avance, PAS optimisés sur les données.
Le 🟢 n'est donné que si le backtest le prouve, comme pour les autres stratégies.
"""
from __future__ import annotations

import pandas as pd

from ..analysis.indicators import atr
from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings
from .base import ACTION_ENTER, ACTION_WAIT_RETEST, Setup, finalize, score_setup

NAME = "canal_donchian"
LOOKBACK = 20          # bougies 4h du canal
STOP_N = 2.0           # stop = 2 × ATR 4h (« 2N »)
TP_R = (1.5, 3.0, 5.0)
MAX_AGE_BARS = 4       # la cassure doit dater de la dernière bougie 4h clôturée, il y a 1 h au plus (4 × 15 min)
MAX_BEYOND_N = 1.0     # prix déjà à plus de 1 × ATR 4h au-delà du canal → on ne court pas après


def find(a: MarketAnalysis, s: Settings) -> list[Setup]:
    out: list[Setup] = []
    h4 = a.frames.get("4h")
    f15 = a.frames.get("15m")
    if h4 is None or f15 is None or len(h4) < LOOKBACK + 20 or not len(f15):
        return out
    n_atr = float(atr(h4, 20).iloc[-1])
    if not n_atr or n_atr != n_atr or n_atr <= 0:
        return out
    last, prev = h4.iloc[-1], h4.iloc[-2]
    chan = h4.iloc[-(LOOKBACK + 1):-1]          # les 20 bougies AVANT la dernière clôturée
    chan_prev = h4.iloc[-(LOOKBACK + 2):-2]
    now = f15.index[-1] + pd.Timedelta(minutes=15)
    age = int((now - (h4.index[-1] + pd.Timedelta(hours=4))) / pd.Timedelta(minutes=15))
    for direction in ("LONG", "SHORT"):
        sign = 1 if direction == "LONG" else -1
        level = float(chan["high"].max() if sign > 0 else chan["low"].min())
        level_prev = float(chan_prev["high"].max() if sign > 0 else chan_prev["low"].min())
        close = float(last["close"])
        if sign * (close - level) <= 0:
            continue                                 # pas de clôture 4h hors du canal
        if sign * (float(prev["close"]) - level_prev) > 0:
            continue                                 # cassure déjà ancienne (bougie 4h précédente déjà dehors)
        lo, hi = sorted((close, close - sign * 0.25 * n_atr))
        entry_ref = hi if sign > 0 else lo
        sl = entry_ref - sign * STOP_N * n_atr
        risk = abs(entry_ref - sl)
        tps = [entry_ref + sign * r * risk for r in TP_R]
        stale = age > MAX_AGE_BARS
        action = ACTION_ENTER if lo <= a.price <= hi else ACTION_WAIT_RETEST
        st = Setup(
            inst_key=a.inst.key, display=a.inst.display, asset_class=a.inst.asset_class, strategy=NAME,
            direction=direction, entry_low=lo, entry_high=hi, sl=sl, tps=tps, invalidation_price=sl,
            invalidation_text=f"Stop {sl:.6g} (2 × la volatilité 4h sous l'entrée)" if sign > 0
            else f"Stop {sl:.6g} (2 × la volatilité 4h au-dessus de l'entrée)",
            action=action, confirmed=not stale and sign * (a.price - sl) > 0,
            reasons=[f"clôture 4h {'au-dessus du plus haut' if sign > 0 else 'sous le plus bas'} des {LOOKBACK} dernières "
                     f"bougies 4h ({level:.6g})", f"volatilité 4h (ATR) {n_atr:.6g} · stop à 2 × ATR"],
        )
        st.stale = stale
        if stale:
            st.trigger = (f"une nouvelle cassure : celle-ci date de {age * 15} min (1 h max), "
                          "le bot ne la validera plus")
        if sign * (a.price - level) > MAX_BEYOND_N * n_atr:
            st.rejections.append("prix déjà trop loin du canal : on ne court pas après")
        score_setup(st, a, s, 3.0, a.rvol15_last, 0 if stale else 10)
        out.append(finalize(st, a, s))
    return out
