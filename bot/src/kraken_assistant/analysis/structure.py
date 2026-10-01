"""Structure de marché : swings, HH/HL/LH/LL, tendance, supports/résistances, range."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .indicators import atr, ema


@dataclass
class Swing:
    ts: pd.Timestamp
    price: float
    kind: str        # "H" | "L"
    label: str = ""  # HH | LH | HL | LL


@dataclass
class Level:
    price: float
    kind: str        # "support" | "resistance" (relatif au prix actuel)
    touches: int
    timeframe: str
    last_touch: pd.Timestamp | None = None

    @property
    def strength(self) -> float:
        tf_w = {"5m": 0.5, "15m": 0.8, "1h": 1.0, "4h": 1.4, "1d": 1.8, "1w": 2.2}.get(self.timeframe, 1.0)
        return tf_w * min(self.touches, 5)


@dataclass
class StructureReport:
    timeframe: str
    trend: str                       # "up" | "down" | "range"
    swings: list[Swing]
    last_labels: list[str]
    ema_bias: str                    # "up" | "down" | "flat" (secondaire)
    atr: float
    atr_pct: float
    range_high: float | None = None
    range_low: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def last_swing_high(self) -> Swing | None:
        return next((s for s in reversed(self.swings) if s.kind == "H"), None)

    @property
    def last_swing_low(self) -> Swing | None:
        return next((s for s in reversed(self.swings) if s.kind == "L"), None)


def find_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Swing]:
    """Fractales : un sommet est le plus haut sur [i-left, i+right]. Les `right` dernières bougies
    ne peuvent pas encore être confirmées (pas de look-ahead)."""
    h, l = df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float)
    out: list[Swing] = []
    k = left + right + 1
    if len(df) >= k:
        wh, wl = sliding_window_view(h, k), sliding_window_view(l, k)
        ch, cl = h[left:len(h) - right], l[left:len(l) - right]
        is_h = (ch == wh.max(axis=1)) & ((wh == ch[:, None]).sum(axis=1) == 1)
        is_l = (cl == wl.min(axis=1)) & ((wl == cl[:, None]).sum(axis=1) == 1)
        idx = df.index
        for j in np.nonzero(is_h | is_l)[0]:
            i = j + left
            if is_h[j]:
                out.append(Swing(idx[i], float(h[i]), "H"))
            if is_l[j]:
                out.append(Swing(idx[i], float(l[i]), "L"))
    out.sort(key=lambda s: (s.ts, s.kind))
    # Alterne H/L : garde l'extrême quand deux swings de même type se suivent
    alt: list[Swing] = []
    for s in out:
        if alt and alt[-1].kind == s.kind:
            if (s.kind == "H" and s.price >= alt[-1].price) or (s.kind == "L" and s.price <= alt[-1].price):
                alt[-1] = s
            continue
        alt.append(s)
    last_h = last_l = None
    for s in alt:
        if s.kind == "H":
            s.label = "" if last_h is None else ("HH" if s.price > last_h else "LH")
            last_h = s.price
        else:
            s.label = "" if last_l is None else ("HL" if s.price > last_l else "LL")
            last_l = s.price
    return alt


def classify_trend(swings: list[Swing]) -> tuple[str, list[str]]:
    labels = [s.label for s in swings if s.label][-4:]
    highs = [s.label for s in swings if s.kind == "H" and s.label][-2:]
    lows = [s.label for s in swings if s.kind == "L" and s.label][-2:]
    if highs and lows:
        if highs[-1] == "HH" and lows[-1] == "HL" and ("HH" in highs[:1] or "HL" in lows[:1]):
            return "up", labels
        if highs[-1] == "LH" and lows[-1] == "LL" and ("LH" in highs[:1] or "LL" in lows[:1]):
            return "down", labels
    return "range", labels


def analyze_structure(df: pd.DataFrame, timeframe: str, left: int = 3, right: int = 3) -> StructureReport:
    swings = find_swings(df, left, right)
    trend, labels = classify_trend(swings)
    a = atr(df).iloc[-1]
    close = df["close"]
    e20, e50 = ema(close, 20).iloc[-1], ema(close, 50).iloc[-1]
    if np.isnan(e50):
        bias = "flat"
    else:
        bias = "up" if close.iloc[-1] > e20 > e50 else "down" if close.iloc[-1] < e20 < e50 else "flat"
    rep = StructureReport(timeframe, trend, swings, labels, bias, float(a), float(a / close.iloc[-1] * 100))
    if trend == "range" and swings:
        recent = swings[-6:]
        rep.range_high = max(s.price for s in recent if s.kind == "H") if any(s.kind == "H" for s in recent) else None
        rep.range_low = min(s.price for s in recent if s.kind == "L") if any(s.kind == "L" for s in recent) else None
    return rep


def build_levels(frames: dict[str, pd.DataFrame], structures: dict[str, StructureReport], price: float,
                 tfs: tuple[str, ...] = ("15m", "1h", "4h")) -> list[Level]:
    """Regroupe les swings proches (tolérance 0,35 ATR 1h) en niveaux ; plus il y a de contacts, plus fort."""
    tol = structures["1h"].atr * 0.35
    raw: list[tuple[float, str, pd.Timestamp]] = []
    for tf in tfs:
        for s in structures[tf].swings[-40:]:
            raw.append((s.price, tf, s.ts))
    raw.sort(key=lambda x: x[0])
    clusters: list[list[tuple[float, str, pd.Timestamp]]] = []
    for item in raw:
        if clusters and abs(item[0] - np.mean([c[0] for c in clusters[-1]])) <= tol:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    order = {"5m": 0, "15m": 1, "1h": 2, "4h": 3, "1d": 4, "1w": 5}
    levels = []
    for c in clusters:
        p = float(np.mean([x[0] for x in c]))
        tf = max((x[1] for x in c), key=lambda t: order[t])
        levels.append(Level(p, "support" if p < price else "resistance", len(c), tf, max(x[2] for x in c)))
    return levels


def nearest_levels(levels: list[Level], price: float, side: str, n: int = 3, min_dist: float = 0.0) -> list[Level]:
    if side == "above":
        c = sorted([lv for lv in levels if lv.price > price + min_dist], key=lambda lv: lv.price)
    else:
        c = sorted([lv for lv in levels if lv.price < price - min_dist], key=lambda lv: -lv.price)
    return c[:n]
