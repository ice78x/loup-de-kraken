"""Corrélations des rendements 1h (log) sur fenêtre glissante."""
from __future__ import annotations

import numpy as np
import pandas as pd


def log_returns(df: pd.DataFrame) -> pd.Series:
    return np.log(df["close"]).diff().dropna()


def correlation(a: pd.DataFrame, b: pd.DataFrame, bars: int = 168, min_overlap: int = 48) -> float | None:
    ra, rb = log_returns(a).iloc[-bars:], log_returns(b).iloc[-bars:]
    j = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(j) < min_overlap or j.iloc[:, 0].std() == 0 or j.iloc[:, 1].std() == 0:
        return None
    return float(j.iloc[:, 0].corr(j.iloc[:, 1]))
