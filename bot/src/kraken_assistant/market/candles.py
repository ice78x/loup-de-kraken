"""Bougies OHLCV multi-timeframes (5m, 15m, 1h, 4h) + contrôles de qualité.

Spot    : /0/public/OHLC (max 720 bougies) en 5m et 60m ; 15m et 4h sont agrégés à partir de ces données.
Futures : /api/charts/v1/trade/{symbol}/{res}.
La bougie en cours (non clôturée) est TOUJOURS retirée : les signaux se basent sur des clôtures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..api.errors import DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from .models import Instrument

log = logging.getLogger(__name__)

TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
MIN_BARS = {"5m": 100, "15m": 60, "1h": 100, "4h": 40}


def spot_rows_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="s", utc=True)
    for c in ["open", "high", "low", "close", "vwap", "volume"]:
        df[c] = df[c].astype(float)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]].sort_index()


def futures_rows_to_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]].sort_index()


def drop_unclosed(df: pd.DataFrame, minutes: int, now: datetime | None = None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    end = df.index + pd.Timedelta(minutes=minutes)
    return df[end <= pd.Timestamp(now)]


def resample(df: pd.DataFrame, src_minutes: int, dst_minutes: int) -> pd.DataFrame:
    """Agrège des bougies clôturées ; ne garde que les buckets complets (tous les sous-intervalles présents
    ou, à défaut, clôturés dans le temps)."""
    rule = f"{dst_minutes}min"
    agg = df.resample(rule, label="left", closed="left", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    counts = df["close"].resample(rule, label="left", closed="left", origin="epoch").count()
    agg = agg[counts > 0].dropna()
    last_sub_end = df.index[-1] + pd.Timedelta(minutes=src_minutes)
    agg = agg[agg.index + pd.Timedelta(minutes=dst_minutes) <= last_sub_end]
    return agg


def validate_frame(df: pd.DataFrame, tf: str, now: datetime | None = None, max_stale_bars: float = 3) -> list[str]:
    """Retourne la liste des problèmes détectés (vide = OK)."""
    issues: list[str] = []
    if df is None or len(df) < MIN_BARS[tf]:
        return [f"{tf}: historique insuffisant ({0 if df is None else len(df)} bougies)"]
    if df[["open", "high", "low", "close"]].isna().any().any():
        issues.append(f"{tf}: valeurs manquantes")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        issues.append(f"{tf}: prix nuls ou négatifs")
    bad = (df["high"] < df[["open", "close"]].max(axis=1) - 1e-12) | (df["low"] > df[["open", "close"]].min(axis=1) + 1e-12)
    if bad.sum() > 0:
        issues.append(f"{tf}: {int(bad.sum())} bougies incohérentes (high/low)")
    rets = df["close"].pct_change().abs()
    if (rets > 0.5).any():
        issues.append(f"{tf}: variation > 50 % entre deux bougies (donnée suspecte)")
    now = now or datetime.now(timezone.utc)
    age_min = (pd.Timestamp(now) - df.index[-1]).total_seconds() / 60 - TF_MINUTES[tf]
    if age_min > TF_MINUTES[tf] * max_stale_bars + 10:
        issues.append(f"{tf}: données périmées ({age_min:.0f} min) — marché fermé ou illiquide ?")
    return issues


class CandleService:
    def __init__(self, spot: KrakenSpotClient, futures: KrakenFuturesClient | None):
        self.spot, self.futures = spot, futures

    def fetch_raw(self, inst: Instrument) -> tuple[pd.DataFrame, pd.DataFrame]:
        if inst.venue == "spot":
            d5 = spot_rows_to_df(self.spot.ohlc(inst.symbol, 5, inst.api_asset_class))
            d60 = spot_rows_to_df(self.spot.ohlc(inst.symbol, 60, inst.api_asset_class))
        else:
            if not self.futures:
                raise DataUnavailable("client futures désactivé")
            d5 = futures_rows_to_df(self.futures.candles(inst.symbol, 5))
            d60 = futures_rows_to_df(self.futures.candles(inst.symbol, 60))
        return d5, d60

    history = None  # HistoryService, branché par App.build

    def frames(self, inst: Instrument, now: datetime | None = None) -> dict[str, pd.DataFrame]:
        """Bougies live (API) fusionnées avec l'historique local, + journalier/hebdo pour le contexte long terme."""
        d5, d60 = self.fetch_raw(inst)
        d5, d60 = drop_unclosed(d5, 5, now), drop_unclosed(d60, 60, now)
        h = self.history
        if h is not None:
            from .history import merge
            h.store.upsert(inst.key, "5m", d5)
            h.store.upsert(inst.key, "1h", d60)
            d5 = merge(h.store.load(inst.key, "5m", 2000), d5)
            d60 = merge(h.store.load(inst.key, "1h", 2000), d60)
        frames = build_frames(d5, d60, now)
        if h is not None:
            d1, w1 = h.fetch_htf(inst)
            if d1 is not None:
                frames["1d"] = d1
            if w1 is not None:
                frames["1w"] = w1
        return frames


def build_frames(d5: pd.DataFrame, d60: pd.DataFrame, now: datetime | None = None) -> dict[str, pd.DataFrame]:
    d5 = drop_unclosed(d5, 5, now)
    d60 = drop_unclosed(d60, 60, now)
    if d5.empty or d60.empty:
        raise DataUnavailable("aucune bougie clôturée")
    frames = {"5m": d5, "15m": resample(d5, 5, 15), "1h": d60, "4h": resample(d60, 60, 240)}
    # Contrôles de qualité sur la partie récente (celle qui sert aux décisions)
    issues = [i for tf, df in frames.items() for i in validate_frame(df.iloc[-720:], tf, now)]
    if issues:
        raise DataUnavailable("; ".join(issues))
    return frames


def returns_series(df: pd.DataFrame) -> pd.Series:
    return np.log(df["close"]).diff().dropna()
