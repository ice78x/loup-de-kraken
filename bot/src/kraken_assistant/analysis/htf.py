"""Contexte long terme à partir de tout l'historique disponible (journalier + hebdomadaire).

- tendance de fond journalière et hebdomadaire (structure HH/HL, EMA50/200 en secondaire) ;
- niveaux majeurs : swings journaliers/hebdo, plus haut/bas historique connu, plus haut/bas 52 semaines ;
- position du prix dans son range annuel.
Ces niveaux servent d'objectifs (TP), d'obstacles et de niveaux de cassure à fort poids.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import ema
from .structure import Level, analyze_structure


@dataclass
class HTFContext:
    daily_trend: str = "inconnu"     # up | down | range | inconnu
    weekly_trend: str = "inconnu"
    daily_bias: str = "flat"         # EMA50/200 journalières (secondaire)
    levels: list[Level] = field(default_factory=list)
    ath: float | None = None
    atl: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    range_position: float | None = None   # 0 = plus bas 52 sem., 1 = plus haut 52 sem.
    history_days: int = 0
    notes: list[str] = field(default_factory=list)

    def aligned(self, direction: str) -> int:
        """Nombre de tendances de fond (jour, semaine) alignées avec la direction ; négatif si opposées."""
        d = "up" if direction == "LONG" else "down"
        o = "down" if d == "up" else "up"
        return sum(1 for t in (self.daily_trend, self.weekly_trend) if t == d) - \
            sum(1 for t in (self.daily_trend, self.weekly_trend) if t == o)

    def summary(self) -> str:
        parts = [f"fond J {self.daily_trend} / S {self.weekly_trend}"]
        if self.range_position is not None:
            parts.append(f"{self.range_position * 100:.0f} % du range 52 sem.")
        if self.history_days:
            parts.append(f"{self.history_days} j d'historique")
        return " · ".join(parts)


def htf_context(d1: pd.DataFrame | None, w1: pd.DataFrame | None, price: float) -> HTFContext:
    ctx = HTFContext()
    if d1 is None or len(d1) < 30:
        ctx.notes.append("historique journalier insuffisant")
        return ctx
    ctx.history_days = int((d1.index[-1] - d1.index[0]).days)
    sd = analyze_structure(d1, "1d", 3, 3)
    ctx.daily_trend = sd.trend
    c = d1["close"]
    if len(c) >= 200:
        e50, e200 = ema(c, 50).iloc[-1], ema(c, 200).iloc[-1]
        ctx.daily_bias = "up" if e50 > e200 else "down" if e50 < e200 else "flat"
    last_year = d1[d1.index >= d1.index[-1] - pd.Timedelta(days=365)]
    ctx.high_52w, ctx.low_52w = float(last_year["high"].max()), float(last_year["low"].min())
    rng = ctx.high_52w - ctx.low_52w
    ctx.range_position = float(np.clip((price - ctx.low_52w) / rng, 0, 1)) if rng > 0 else None
    src = w1 if w1 is not None and len(w1) > len(d1) / 7 else d1
    ctx.ath, ctx.atl = float(max(src["high"].max(), d1["high"].max())), float(min(src["low"].min(), d1["low"].min()))
    levels: list[Level] = []
    # Swings journaliers récents (les 60 derniers) — tolérance de regroupement : 0,5 % du prix
    tol = price * 0.005
    for s in sd.swings[-60:]:
        levels.append(Level(s.price, "support" if s.price < price else "resistance", 1, "1d", s.ts))
    if w1 is not None and len(w1) >= 20:
        sw = analyze_structure(w1, "1w", 2, 2)
        ctx.weekly_trend = sw.trend
        for s in sw.swings[-40:]:
            levels.append(Level(s.price, "support" if s.price < price else "resistance", 1, "1w", s.ts))
    for p, tf in ((ctx.high_52w, "1d"), (ctx.low_52w, "1d"), (ctx.ath, "1w"), (ctx.atl, "1w")):
        levels.append(Level(p, "support" if p < price else "resistance", 2, tf))
    # regroupement
    levels.sort(key=lambda lv: lv.price)
    merged: list[Level] = []
    for lv in levels:
        if merged and abs(lv.price - merged[-1].price) <= tol:
            m = merged[-1]
            m.touches += lv.touches
            if lv.timeframe == "1w":
                m.timeframe = "1w"
        else:
            merged.append(Level(lv.price, lv.kind, lv.touches, lv.timeframe, lv.last_touch))
    # On garde les niveaux dans ±25 % du prix (au-delà, inutiles en intraday/swing court)
    ctx.levels = [lv for lv in merged if abs(lv.price / price - 1) <= 0.25]
    return ctx
