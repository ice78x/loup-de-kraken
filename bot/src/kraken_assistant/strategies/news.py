"""Stratégie NEWS : catalyseur vérifié à fort impact + réaction de prix réelle + premier pullback confirmé.
La news seule ne suffit jamais : sans impulsion ET confirmation 15m, il n'y a pas de trade."""
from __future__ import annotations

import pandas as pd

from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings
from .base import ACTION_ENTER, ACTION_WAIT_RETEST, Setup, build_targets, finalize, score_setup

NAME = "news_momentum"


def find(a: MarketAnalysis, s: Settings) -> list[Setup]:
    n = a.catalyst.main
    if not n or n.impact < 3 or n.direction_hint == "incertain" or n.scope == "calendar":
        return []
    direction = "LONG" if n.direction_hint == "haussier" else "SHORT"
    sign = 1 if direction == "LONG" else -1
    f15 = a.frames["15m"]
    after = f15[f15.index >= pd.Timestamp(n.published_at).floor("15min")]
    if len(after) < 3 or a.atr15 <= 0:
        return []
    anchor = float(after["open"].iloc[0])
    extreme = float(after["high"].max() if sign > 0 else after["low"].min())
    move = sign * (extreme - anchor)
    if move < 1.5 * a.atr1h:
        return []  # le marché n'a pas (encore) validé la news
    ext_idx = after["high"].idxmax() if sign > 0 else after["low"].idxmin()
    post = after[after.index > ext_idx]
    if len(post) < 2:
        st_trigger = "attendre le premier pullback après l'impulsion"
        pb = None
    else:
        pb = float(post["low"].min() if sign > 0 else post["high"].max())
        st_trigger = ""
    if pb is None:
        return []
    retr = sign * (extreme - pb) / move
    if not (0.2 <= retr <= 0.65):
        return []
    last, prev = f15.iloc[-1], f15.iloc[-3:-1]
    trig = float(prev["high"].max() if sign > 0 else prev["low"].min())
    confirmed = (last["close"] > trig and last["close"] > last["open"]) if sign > 0 else \
                (last["close"] < trig and last["close"] < last["open"])
    close = float(last["close"])
    lo, hi = sorted((close - sign * 0.35 * a.atr15, close + sign * 0.1 * a.atr15))
    sl = pb - sign * 0.25 * a.atr15
    tps, notes, obstacle = build_targets(direction, hi if sign > 0 else lo, sl,
                                         a.all_level_prices + [extreme], a.atr15)
    st = Setup(
        inst_key=a.inst.key, display=a.inst.display, asset_class=a.inst.asset_class, strategy=NAME,
        direction=direction, entry_low=lo, entry_high=hi, sl=sl, tps=tps, invalidation_price=pb,
        invalidation_text=f"Clôture 15m {'sous' if sign > 0 else 'au-dessus de'} {pb:.6g} (creux/sommet post-news)",
        action=ACTION_ENTER if lo <= a.price <= hi else ACTION_WAIT_RETEST, tp_notes=notes,
        confirmed=bool(confirmed), extension_atr=0.0,
        reasons=[f"réaction de prix {move / a.atr1h:.1f} ATR1h depuis la news", f"pullback {retr * 100:.0f} %"],
        trigger=st_trigger or ("" if confirmed else f"clôture 15m {'au-dessus' if sign > 0 else 'sous'} {trig:.6g}"),
    )
    if obstacle is not None:
        st.warnings.append(f"niveau gênant proche ({obstacle:.1f}R)")
    score_setup(st, a, s, 2.0, a.rvol15_last, 12 if confirmed else 4)
    return [finalize(st, a, s)]
