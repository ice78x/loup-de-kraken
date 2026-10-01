"""Stratégie CASSURE → CLÔTURE 15M → RETEST → CONFIRMATION → ENTRÉE."""
from __future__ import annotations

from ..analysis import breakout as bo
from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings
from .base import (ACTION_ENTER, ACTION_WAIT_CLOSE, ACTION_WAIT_RETEST, Setup, build_targets, finalize,
                   score_setup)

NAME = "cassure_retest"


def find(a: MarketAnalysis, s: Settings) -> list[Setup]:
    out: list[Setup] = []
    atr15, price = a.atr15, a.price
    if atr15 <= 0:
        return out
    near = [lv for lv in a.levels + a.htf.levels
            if abs(lv.price - price) <= 4 * a.atr1h and lv.timeframe in ("1h", "4h", "1d", "1w")]
    level_prices = a.all_level_prices
    for lv in near:
        for side in ("up", "down"):
            ev = bo.classify_level(a.bars, lv.price, side, atr15, ext_max=s.max_extension_atr15)
            if ev.state not in (bo.CONFIRMED_RETEST, bo.RETEST_IN_PROGRESS, bo.WAIT_RETEST, bo.NO_VOLUME, bo.EXTENDED):
                continue
            direction = ev.implied_direction
            if direction is None:
                continue
            sign = 1 if direction == "LONG" else -1
            L = lv.price
            # Zone d'entrée autour du niveau cassé (côté "bon" du niveau)
            near_edge = L + sign * 0.05 * atr15
            far_edge = L + sign * max(0.45 * atr15, min(sign * (price - L), 1.0 * atr15))
            lo, hi = sorted((near_edge, far_edge))
            retest_ext = ev.retest_extreme if ev.retest_extreme is not None else L - sign * 0.3 * atr15
            sl_anchor = min(retest_ext, L - 0.3 * atr15) if sign > 0 else max(retest_ext, L + 0.3 * atr15)
            sl = sl_anchor - sign * 0.2 * atr15
            entry_ref = hi if sign > 0 else lo
            tps, notes, obstacle = build_targets(direction, entry_ref, sl, level_prices, atr15)
            if lo <= price <= hi:
                action = ACTION_ENTER
            elif sign * (price - L) > 0:
                action = ACTION_WAIT_RETEST
            else:
                action = ACTION_WAIT_CLOSE
            confirmed = ev.state == bo.CONFIRMED_RETEST and action != ACTION_WAIT_CLOSE
            word = "au-dessus" if sign > 0 else "sous"
            st = Setup(
                inst_key=a.inst.key, display=a.inst.display, asset_class=a.inst.asset_class, strategy=NAME,
                direction=direction, entry_low=lo, entry_high=hi, sl=sl, tps=tps,
                invalidation_price=L - sign * 0.3 * atr15,
                invalidation_text=f"Clôture 15m {'sous' if sign > 0 else 'au-dessus de'} {L - sign * 0.3 * atr15:.6g} "
                                  f"(retour {'sous' if sign > 0 else 'au-dessus du'} niveau cassé)",
                action=action, event=ev, tp_notes=notes, confirmed=confirmed,
                extension_atr=max(0.0, sign * (price - L) / atr15),
                reasons=[f"{ev.state} du niveau {L:.6g} ({lv.timeframe}, {lv.touches} contacts)",
                         f"structure 4h {a.structures['4h'].trend} / 1h {a.structures['1h'].trend}"],
            )
            if ev.break_rvol is not None:
                st.reasons.append(f"volume de cassure x{ev.break_rvol:.1f} la moyenne")
            if obstacle is not None:
                st.warnings.append(f"niveau gênant proche ({obstacle:.1f}R)")
            if ev.state == bo.EXTENDED:
                st.trigger = f"attendre un retour vers {L:.6g} (zone {lo:.6g}–{hi:.6g}) puis une clôture 15m {word}"
            elif not confirmed:
                st.trigger = f"retest de {L:.6g} puis clôture 15m {word} avec reprise de volume"
            conf = {bo.CONFIRMED_RETEST: 15, bo.RETEST_IN_PROGRESS: 7, bo.WAIT_RETEST: 5, bo.NO_VOLUME: 2,
                    bo.EXTENDED: 4}[ev.state]
            score_setup(st, a, s, lv.strength, ev.break_rvol, conf - (3 if obstacle is not None else 0))
            out.append(finalize(st, a, s))
    return out
