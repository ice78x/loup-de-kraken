"""Régime de volatilité : ATR actuel vs médiane récente."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .indicators import atr


@dataclass
class VolatilityReport:
    atr_1h_pct: float
    ratio_vs_median: float
    regime: str   # "compressée" | "normale" | "élevée" | "extrême"

    @property
    def score(self) -> float:
        """0..1 — la volatilité 'normale à élevée' est la plus exploitable pour des checks toutes les 10-30 min."""
        return {"compressée": 0.4, "normale": 1.0, "élevée": 0.8, "extrême": 0.2}[self.regime]


def volatility_report(df1h: pd.DataFrame) -> VolatilityReport:
    a = atr(df1h) / df1h["close"] * 100
    cur = float(a.iloc[-1])
    med = float(a.iloc[-min(len(a), 24 * 20):].median())
    ratio = cur / med if med > 0 else 1.0
    regime = "compressée" if ratio < 0.6 else "normale" if ratio < 1.6 else "élevée" if ratio < 2.8 else "extrême"
    return VolatilityReport(round(cur, 3), round(ratio, 2), regime)
