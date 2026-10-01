"""Classification des interactions prix / niveau sur bougies 15m CLÔTURÉES.

Différencie : cassure confirmée (cassure → clôture 15m → retest → confirmation), cassure en attente de
retest, cassure sans volume, fausse cassure, sweep de liquidité, rejet, mouvement trop étendu.
Une mèche seule ne compte JAMAIS comme cassure : il faut une clôture au-delà du niveau.

Implémentation : la logique est écrite pour une cassure HAUSSIÈRE ; la version baissière est obtenue en
"miroir" (prix négatifs) pour garantir une symétrie exacte.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import relative_volume

CONFIRMED_RETEST = "CASSURE CONFIRMÉE + RETEST"
RETEST_IN_PROGRESS = "RETEST EN COURS"
WAIT_RETEST = "CASSURE — ATTENTE RETEST"
NO_VOLUME = "CASSURE SANS VOLUME"
FAKE_BREAKOUT = "FAUSSE CASSURE"
SWEEP = "SWEEP DE LIQUIDITÉ"
REJECTION = "REJET"
EXTENDED = "MOUVEMENT DÉJÀ TROP ÉTENDU"
NONE = "AUCUN"


@dataclass
class LevelEvent:
    level: float
    side: str                  # "up" : niveau au-dessus cassé/testé par le haut ; "down" : par le bas
    state: str
    implied_direction: str | None   # "LONG" | "SHORT" | None — direction de trade que l'évènement suggère
    break_ts: pd.Timestamp | None = None
    break_rvol: float | None = None
    retest_extreme: float | None = None  # plus bas du retest (up) / plus haut (down), prix réel
    sweep_extreme: float | None = None   # extrémité de la mèche du sweep/rejet, prix réel
    confirm_ts: pd.Timestamp | None = None
    bars_since_signal: int | None = None
    extension_atr: float = 0.0
    needs_close_confirmation: bool = False

    def describe(self) -> str:
        return f"{self.state} @ {self.level:g}"


@dataclass
class Bars:
    """Tableaux numpy des bougies 15m (calculés une seule fois par analyse)."""
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    rv: np.ndarray
    index: pd.DatetimeIndex

    def mirror(self) -> "Bars":
        return Bars(-self.o, -self.l, -self.h, -self.c, self.rv, self.index)


def prep(df15: pd.DataFrame) -> Bars:
    rv = relative_volume(df15["volume"]).to_numpy(dtype=float)
    return Bars(df15["open"].to_numpy(dtype=float), df15["high"].to_numpy(dtype=float),
                df15["low"].to_numpy(dtype=float), df15["close"].to_numpy(dtype=float), rv, df15.index)


def _classify_up(B: Bars, L: float, atr15: float, lookback: int, vol_min: float, buf_atr: float,
                 tol_atr: float, ext_max: float) -> LevelEvent:
    buf, tol = buf_atr * atr15, tol_atr * atr15
    N = len(B.c)
    lookback = min(lookback, N)
    s0 = N - lookback
    o, h, l, c, rvw = B.o[s0:], B.h[s0:], B.l[s0:], B.c[s0:], B.rv[s0:]
    idx = B.index[s0:]
    n = lookback
    last_close = float(c[-1])
    ext = (last_close - L) / atr15 if atr15 > 0 else 0.0

    prior = B.c[s0 - 1] if s0 > 0 else c[0]
    if prior > L + buf:
        # Le niveau était déjà sous le prix avant la fenêtre : pas une cassure fraîche.
        return LevelEvent(L, "up", NONE, None, extension_atr=ext)

    above = np.nonzero(c > L + buf)[0]
    b = int(above[0]) if len(above) else None
    if b is None:
        # Mèches au-dessus du niveau sans clôture : sweep ou rejet (implication baissière)
        for i in range(n - 1, max(-1, n - 5), -1):
            rng = h[i] - l[i]
            if h[i] > L + buf and c[i] < L and rng > 0:
                upper_wick = (h[i] - max(o[i], c[i])) / rng
                rvi = rvw[i] if np.isfinite(rvw[i]) else 0.0
                state = SWEEP if rvi >= vol_min else (REJECTION if upper_wick >= 0.5 else NONE)
                if state == NONE:
                    continue
                confirmed = i < n - 1 and c[-1] < min(o[i], c[i]) and c[-1] < L
                return LevelEvent(L, "up", state, "SHORT", sweep_extreme=float(h[i]),
                                  confirm_ts=idx[-1] if confirmed else None,
                                  bars_since_signal=n - 1 - i, extension_atr=ext,
                                  needs_close_confirmation=not confirmed)
        return LevelEvent(L, "up", NONE, None, extension_atr=ext)

    w = _W(idx)
    brv = float(rvw[b]) if np.isfinite(rvw[b]) else None
    after = range(b + 1, n)
    back_inside = next((i for i in after if c[i] < L - buf), None)
    if back_inside is not None:
        return LevelEvent(L, "up", FAKE_BREAKOUT, "SHORT", break_ts=w.index[b], break_rvol=brv,
                          sweep_extreme=float(h[b:back_inside + 1].max()),
                          confirm_ts=w.index[back_inside], bars_since_signal=n - 1 - back_inside, extension_atr=ext)
    r = next((i for i in after if l[i] <= L + tol and c[i] > L), None)
    if r is not None:
        confirm = None
        rng = h[r] - l[r]
        if rng > 0 and c[r] > o[r] and (min(o[r], c[r]) - l[r]) / rng >= 0.4:
            confirm = r  # la bougie de retest est elle-même un rejet haussier clôturé
        else:
            confirm = next((i for i in range(r + 1, n) if c[i] > max(h[r], L) and c[i] > o[i]), None)
        retest_low = float(l[r:(confirm if confirm is not None else n - 1) + 1].min())
        if confirm is None:
            return LevelEvent(L, "up", RETEST_IN_PROGRESS, "LONG", break_ts=w.index[b], break_rvol=brv,
                              retest_extreme=retest_low, bars_since_signal=n - 1 - r, extension_atr=ext,
                              needs_close_confirmation=True)
        if ext > ext_max or n - 1 - confirm > 4:
            return LevelEvent(L, "up", EXTENDED, "LONG", break_ts=w.index[b], break_rvol=brv,
                              retest_extreme=retest_low, confirm_ts=w.index[confirm],
                              bars_since_signal=n - 1 - confirm, extension_atr=ext)
        return LevelEvent(L, "up", CONFIRMED_RETEST, "LONG", break_ts=w.index[b], break_rvol=brv,
                          retest_extreme=retest_low, confirm_ts=w.index[confirm],
                          bars_since_signal=n - 1 - confirm, extension_atr=ext)
    if ext > ext_max:
        return LevelEvent(L, "up", EXTENDED, "LONG", break_ts=w.index[b], break_rvol=brv,
                          bars_since_signal=n - 1 - b, extension_atr=ext)
    if brv is None or brv < 1.0:
        return LevelEvent(L, "up", NO_VOLUME, "LONG", break_ts=w.index[b], break_rvol=brv,
                          bars_since_signal=n - 1 - b, extension_atr=ext, needs_close_confirmation=True)
    return LevelEvent(L, "up", WAIT_RETEST, "LONG", break_ts=w.index[b], break_rvol=brv,
                      bars_since_signal=n - 1 - b, extension_atr=ext, needs_close_confirmation=True)


def classify_level(df15: pd.DataFrame | Bars, level: float, side: str, atr15: float, lookback: int = 16,
                   vol_min: float = 1.3, buf_atr: float = 0.1, tol_atr: float = 0.3,
                   ext_max: float = 2.5) -> LevelEvent:
    """side="up" : niveau de résistance (au-dessus avant la fenêtre). side="down" : support.
    Accepte un DataFrame 15m ou des Bars pré-calculées (plus rapide)."""
    B = df15 if isinstance(df15, Bars) else prep(df15)
    if side == "up":
        return _classify_up(B, level, atr15, lookback, vol_min, buf_atr, tol_atr, ext_max)
    ev = _classify_up(B.mirror(), -level, atr15, lookback, vol_min, buf_atr, tol_atr, ext_max)
    flip = {"LONG": "SHORT", "SHORT": "LONG", None: None}
    return LevelEvent(level, "down", ev.state, flip[ev.implied_direction], ev.break_ts, ev.break_rvol,
                      -ev.retest_extreme if ev.retest_extreme is not None else None,
                      -ev.sweep_extreme if ev.sweep_extreme is not None else None,
                      ev.confirm_ts, ev.bars_since_signal, ev.extension_atr, ev.needs_close_confirmation)


class _W:
    """Adaptateur minimal : w.index[i] comme dans l'implémentation pandas d'origine."""
    def __init__(self, index: pd.DatetimeIndex):
        self.index = index
