"""Indicateurs calculés en interne (testés) — utilisés comme éléments SECONDAIRES uniquement."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder."""
    d = close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0).where(au.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    pc = np.empty_like(c)
    pc[0], pc[1:] = np.nan, c[:-1]
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr, index=df.index)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR de Wilder."""
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP réinitialisé chaque jour UTC (prix typique)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.floor("D")
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return pv / vv.replace(0, np.nan)


def relative_volume(vol: pd.Series, n: int = 20) -> pd.Series:
    """Volume / moyenne des n bougies PRÉCÉDENTES."""
    return vol / vol.shift(1).rolling(n, min_periods=max(5, n // 2)).mean()
