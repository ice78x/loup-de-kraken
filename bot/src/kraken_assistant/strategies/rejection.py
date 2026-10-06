"""Stratégie de REJET : sweep de liquidité / mèche de rejet / fausse cassure sur un niveau fort → trade inverse,
uniquement après une clôture 15m de confirmation (jamais sur la mèche seule)."""
from __future__ import annotations

from ..analysis import breakout as bo
from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings
from .base import ACTION_ENTER, ACTION_WAIT_CLOSE, ACTION_WAIT_RETEST, Setup, build_targets, finalize, score_setup

NAME = "rejet_sweep"


MAX_SIGNAL_AGE_BARS = 4   # un rejet/piège n'est validé que dans l'heure qui suit (4 bougies 15m)


def find(a: MarketAnalysis, s: Settings) -> list[Setup]:
    out: list[Setup] = []
    atr15, price = a.atr15, a.price
    if atr15 <= 0:
        return out
    near = [lv for lv in a.levels + a.htf.levels
            if abs(lv.price - price) <= 3 * a.atr1h and (lv.touches >= 2 or lv.timeframe in ("1d", "1w"))]
    level_prices = a.all_level_prices
    for lv in near:
        for side in ("up", "down"):
            ev = bo.classify_level(a.bars, lv.price, side, atr15)
            if ev.state not in (bo.SWEEP, bo.REJECTION, bo.FAKE_BREAKOUT) or ev.implied_direction is None:
                continue
            direction = ev.implied_direction
            sign = 1 if direction == "LONG" else -1
            L = lv.price
            wick = ev.sweep_extreme if ev.sweep_extreme is not None else L - sign * 0.5 * atr15
            sl = wick - sign * 0.25 * atr15
            near_edge = L + sign * 0.05 * atr15
            far_edge = L + sign * max(0.5 * atr15, min(sign * (price - L), 1.2 * atr15))
            lo, hi = sorted((near_edge, far_edge))
            entry_ref = hi if sign > 0 else lo
            tps, notes, obstacle = build_targets(direction, entry_ref, sl, [p for p in level_prices if p != L], atr15)
            if lo <= price <= hi:
                action = ACTION_ENTER
            elif sign * (price - L) > 0:
                action = ACTION_WAIT_RETEST
            else:
                action = ACTION_WAIT_CLOSE
            age = ev.bars_since_signal or 0
            stale = age > MAX_SIGNAL_AGE_BARS     # le piège date de plus d'1 h : il ne sera plus jamais confirmé
            confirmed = (not ev.needs_close_confirmation) and action != ACTION_WAIT_CLOSE and not stale
            st = Setup(
                inst_key=a.inst.key, display=a.inst.display, asset_class=a.inst.asset_class, strategy=NAME,
                direction=direction, entry_low=lo, entry_high=hi, sl=sl, tps=tps, invalidation_price=L,
                invalidation_text=f"Clôture 15m {'sous' if sign > 0 else 'au-dessus de'} {L:.6g} (niveau repris)",
                action=action, event=ev, tp_notes=notes, confirmed=confirmed,
                extension_atr=max(0.0, sign * (price - L) / atr15),
                reasons=[f"{ev.state} sur {L:.6g} ({lv.timeframe}, {lv.touches} contacts)",
                         f"mèche extrême {wick:.6g}"],
            )
            if obstacle is not None:
                st.warnings.append(f"niveau gênant proche ({obstacle:.1f}R)")
            st.stale = stale and not ev.needs_close_confirmation
            if not confirmed:
                if ev.needs_close_confirmation:
                    st.trigger = f"clôture 15m {'au-dessus' if sign > 0 else 'sous'} {L:.6g} confirmant le rejet"
                elif st.stale:
                    # 06/10 (TAO) : avant, le texte disait « retour dans la zone » alors que le prix y était déjà.
                    st.trigger = (f"un nouveau rejet : celui-ci date de {age * 15} min (1 h max), "
                                  "le bot ne le validera plus")
                else:
                    st.trigger = f"retour dans la zone {lo:.6g}–{hi:.6g}"
            conf = {bo.SWEEP: 12, bo.FAKE_BREAKOUT: 12, bo.REJECTION: 10}[ev.state]
            if ev.needs_close_confirmation:
                conf = 3
            score_setup(st, a, s, lv.strength, a.rvol15_last, conf - (3 if obstacle is not None else 0), reversal=True)
            out.append(finalize(st, a, s))
    return out
