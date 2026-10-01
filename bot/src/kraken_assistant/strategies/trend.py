"""Stratégie TENDANCE : pullback dans une tendance 4h/1h + signal de reprise 15m clôturé."""
from __future__ import annotations

from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings
from .base import ACTION_ENTER, ACTION_WAIT_RETEST, Setup, build_targets, finalize, score_setup

NAME = "tendance_pullback"


def _impulse(swings, direction: str):
    """Dernière impulsion 1h : (origine, extrême) dans le sens de la tendance."""
    hk, lk = ("H", "L") if direction == "LONG" else ("L", "H")
    ext = next((i for i in range(len(swings) - 1, -1, -1) if swings[i].kind == hk), None)
    if ext is None:
        return None
    org = next((j for j in range(ext - 1, -1, -1) if swings[j].kind == lk), None)
    return (swings[org].price, swings[ext].price) if org is not None else None


def find(a: MarketAnalysis, s: Settings) -> list[Setup]:
    out: list[Setup] = []
    s4, s1 = a.structures["4h"], a.structures["1h"]
    f15 = a.frames["15m"]
    atr15 = a.atr15
    for direction, d in (("LONG", "up"), ("SHORT", "down")):
        htf = s4.trend == d or (s4.trend == "range" and s4.ema_bias == d)
        mtf = s1.trend == d or (s1.trend == "range" and s1.ema_bias == d)
        if not (htf and mtf) or atr15 <= 0:
            continue
        sign = 1 if direction == "LONG" else -1
        imp = _impulse(s1.swings, direction)
        if not imp:
            continue
        origin, extreme = imp
        size = abs(extreme - origin)
        if size < 1.5 * a.atr1h:
            continue
        recent = f15.iloc[-12:]
        pb_extreme = float(recent["low"].min() if sign > 0 else recent["high"].max())
        retr = sign * (extreme - pb_extreme) / size
        if not (0.3 <= retr <= 0.8):
            continue
        if sign * (pb_extreme - origin) <= 0:
            continue  # structure cassée (sous l'origine de l'impulsion)
        last, prev3 = f15.iloc[-1], f15.iloc[-4:-1]
        if sign > 0:
            trigger_px = float(prev3["high"].max())
            confirmed = last["close"] > trigger_px and last["close"] > last["open"]
        else:
            trigger_px = float(prev3["low"].min())
            confirmed = last["close"] < trigger_px and last["close"] < last["open"]
        close = float(last["close"])
        lo, hi = sorted((close - sign * 0.35 * atr15, close + sign * 0.1 * atr15))
        sl = pb_extreme - sign * 0.25 * atr15
        entry_ref = hi if sign > 0 else lo
        levels = a.all_level_prices + [extreme]
        tps, notes, obstacle = build_targets(direction, entry_ref, sl, levels, atr15)
        action = ACTION_ENTER if lo <= a.price <= hi else ACTION_WAIT_RETEST
        ext_ema = sign * (a.price - a.ema20_1h) / a.atr1h if a.atr1h else 0
        st = Setup(
            inst_key=a.inst.key, display=a.inst.display, asset_class=a.inst.asset_class, strategy=NAME,
            direction=direction, entry_low=lo, entry_high=hi, sl=sl, tps=tps, invalidation_price=pb_extreme,
            invalidation_text=(f"Clôture 15m sous {pb_extreme:.6g} (creux du pullback)" if sign > 0
                               else f"Clôture 15m au-dessus de {pb_extreme:.6g} (sommet du pullback)"),
            action=action, tp_notes=notes, confirmed=bool(confirmed) and sign * (a.price - sl) > 0,
            reasons=[f"tendance 4h {s4.trend} / 1h {s1.trend} ({' '.join(s1.last_labels[-2:])})",
                     f"pullback de {retr * 100:.0f} % de l'impulsion {origin:.6g}→{extreme:.6g}",
                     "reprise 15m clôturée" if confirmed else "pas encore de reprise 15m"],
        )
        if ext_ema > 1.5:
            st.rejections.append("prix trop éloigné de l'EMA20 1h — étendu")
        if obstacle is not None:
            st.warnings.append(f"niveau gênant proche ({obstacle:.1f}R)")
        if not confirmed:
            st.trigger = f"clôture 15m {'au-dessus' if sign > 0 else 'sous'} {trigger_px:.6g}"
        score_setup(st, a, s, 3.0, a.rvol15_last, (12 if confirmed else 4) - (3 if obstacle is not None else 0))
        out.append(finalize(st, a, s))
    return out
