"""Fixtures de test.

⚠ Toutes les données de marché utilisées dans les tests sont SYNTHÉTIQUES (générées), uniquement pour
vérifier la logique. Elles ne représentent aucun prix réel et ne sont jamais utilisées hors des tests.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kraken_assistant.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
                    config_dir=ROOT / "config", scheduler_enabled=False, capital_eur=90.0,
                    quote_currencies=["EUR", "USD"])


def make_df(prices: list[tuple[float, float, float, float]], start: str = "2026-01-05 00:00", freq: str = "15min",
            volume: list[float] | float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(prices), freq=freq, tz="UTC")
    df = pd.DataFrame(prices, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = volume if isinstance(volume, list) else [volume] * len(prices)
    return df


def random_walk(n: int, start: float = 100.0, vol: float = 0.002, seed: int = 1, freq: str = "5min",
                end: pd.Timestamp | None = None, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]])
    spread = np.abs(rng.normal(0, vol / 2, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    if end is None:
        idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    else:
        idx = pd.date_range(end=end, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(50, 150, n)}, index=idx)
