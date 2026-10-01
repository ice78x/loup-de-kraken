"""Assemble l'analyse complète d'un instrument (multi-timeframes) utilisée par les stratégies."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..market.models import Instrument, Ticker
from .breakout import Bars, prep
from .catalysts import CatalystContext
from .htf import HTFContext, htf_context
from .indicators import atr, ema, relative_volume, rsi, session_vwap
from .liquidity import LiquidityReport
from .structure import Level, StructureReport, analyze_structure, build_levels
from .volatility import VolatilityReport, volatility_report


@dataclass
class MarketAnalysis:
    inst: Instrument
    price: float
    frames: dict[str, pd.DataFrame]
    structures: dict[str, StructureReport]
    levels: list[Level]
    atr15: float
    atr1h: float
    vol: VolatilityReport
    liquidity: LiquidityReport | None
    catalyst: CatalystContext
    rsi1h: float
    rsi15: float
    ema20_1h: float
    ema50_1h: float
    vwap15: float | None
    rvol15_last: float | None
    ticker: Ticker | None = None
    bars: Bars | None = None
    htf: HTFContext = field(default_factory=HTFContext)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        s = self.structures
        return {"1w": self.htf.weekly_trend, "1d": self.htf.daily_trend, "4h": s["4h"].trend, "1h": s["1h"].trend,
                "15m": s["15m"].trend, "vol": self.vol.regime, "rsi1h": round(self.rsi1h, 1),
                "atr1h_pct": round(self.vol.atr_1h_pct, 2)}

    @property
    def all_level_prices(self) -> list[float]:
        return [lv.price for lv in self.levels] + [lv.price for lv in self.htf.levels]


# Fenêtres d'analyse (les frames peuvent contenir beaucoup plus d'historique)
WINDOW = {"5m": 300, "15m": 500, "1h": 600, "4h": 400}


def analyze_market(inst: Instrument, frames: dict[str, pd.DataFrame], price: float,
                   liquidity: LiquidityReport | None, catalyst: CatalystContext,
                   ticker: Ticker | None = None) -> MarketAnalysis:
    long_frames = frames
    frames = {tf: df.iloc[-WINDOW[tf]:] for tf, df in frames.items() if tf in WINDOW}
    structures = {
        "5m": analyze_structure(frames["5m"], "5m", 3, 3),
        "15m": analyze_structure(frames["15m"], "15m", 3, 3),
        "1h": analyze_structure(frames["1h"], "1h", 3, 3),
        "4h": analyze_structure(frames["4h"], "4h", 2, 2),
    }
    levels = build_levels(frames, structures, price)
    f15, f1h = frames["15m"], frames["1h"]
    vw = session_vwap(f15).iloc[-1]
    rv = relative_volume(f15["volume"]).iloc[-1]
    return MarketAnalysis(
        inst=inst, price=price, frames=frames, structures=structures, levels=levels,
        atr15=float(atr(f15).iloc[-1]), atr1h=float(atr(f1h).iloc[-1]), vol=volatility_report(f1h),
        liquidity=liquidity, catalyst=catalyst, rsi1h=float(rsi(f1h["close"]).iloc[-1]),
        rsi15=float(rsi(f15["close"]).iloc[-1]), ema20_1h=float(ema(f1h["close"], 20).iloc[-1]),
        ema50_1h=float(ema(f1h["close"], 50).iloc[-1]), vwap15=float(vw) if pd.notna(vw) else None,
        rvol15_last=float(rv) if pd.notna(rv) else None, ticker=ticker, bars=prep(f15),
        htf=htf_context(long_frames.get("1d"), long_frames.get("1w"), price),
    )
