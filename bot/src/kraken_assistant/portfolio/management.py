"""GESTION POSITION : HOLD / PRENDRE TP / DÉPLACER SL / LAISSER COURIR / SORTIE selon invalidation.

Principes :
  - Aucune action réelle n'est exécutée : ce module CONSEILLE.
  - Le SL n'est jamais remonté parce que le prix est "un peu" favorable : il faut TP1 atteint ET une
    confirmation structurelle (creux 15m au-dessus de l'entrée, ou clôtures 15m tenues).
  - On évite de sortir trop tôt : une structure qui faiblit déclenche une alerte, pas une sortie,
    tant que l'invalidation n'est pas clôturée.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..analysis.indicators import atr, ema
from ..analysis.structure import find_swings
from .positions import Position

HOLD = "HOLD"
TAKE_TP = "PRENDRE TP"
MOVE_SL = "DÉPLACER SL"
LET_RUN = "LAISSER COURIR"
EXIT = "SORTIE — INVALIDATION"
SL_HIT = "SL TOUCHÉ"
SET_SL = "RENSEIGNER SL"


@dataclass
class Advice:
    position_id: int
    display: str
    action: str
    details: list[str] = field(default_factory=list)
    new_sl: float | None = None
    tp_index: int | None = None
    urgent: bool = False


def advise(p: Position, frames: dict[str, pd.DataFrame] | None, price: float | None,
           tp_split: tuple[float, float, float] = (0.3, 0.4, 0.3)) -> Advice:
    a = Advice(p.id, p.display, HOLD)
    if price is None or frames is None:
        a.details.append("DATA INSUFFISANTE — prix/bougies indisponibles, aucune recommandation")
        return a
    sg = p.sign
    f15 = frames["15m"]
    atr15 = float(atr(f15).iloc[-1])
    last_close = float(f15["close"].iloc[-1])
    if p.sl is None:
        a.action = SET_SL
        a.urgent = True
        a.details.append("aucun SL connu pour cette position — renseigne-le (POSITION SET <id> sl=...)")
        return a
    if sg * (price - p.sl) <= 0:
        a.action, a.urgent = SL_HIT, True
        a.details.append(f"prix {price:.6g} a atteint le SL {p.sl:.6g}")
        return a
    if p.invalidation is not None and sg * (last_close - p.invalidation) < 0:
        a.action, a.urgent = EXIT, True
        a.details.append(f"clôture 15m {last_close:.6g} {'sous' if sg > 0 else 'au-dessus de'} l'invalidation "
                         f"{p.invalidation:.6g} — scénario invalidé")
        return a
    tps = [(1, p.tp1, p.tp1_hit), (2, p.tp2, p.tp2_hit), (3, p.tp3, p.tp3_hit)]
    for i, tp, hit in tps:
        if tp is not None and not hit and sg * (price - tp) >= 0:
            a.action, a.tp_index, a.urgent = TAKE_TP, i, True
            a.details.append(f"TP{i} {tp:.6g} atteint → prendre {int(tp_split[i - 1] * 100)} % de la position initiale")
            break
    entry = p.entry
    fees_be = entry * (1 + sg * 2 * p.fee_rate_pct / 100)  # break-even frais inclus
    sl_in_loss = sg * (p.sl - entry) < 0
    if p.tp1_hit and not p.tp2_hit and sl_in_loss:
        sw = [s for s in find_swings(f15.iloc[-40:], 2, 2) if s.kind == ("L" if sg > 0 else "H")]
        closes_ok = (sg * (f15["close"].iloc[-2:] - (entry + sg * 0.3 * atr15)) > 0).all()
        if sw and sg * (sw[-1].price - entry) > 0:
            cand = sw[-1].price - sg * 0.2 * atr15
            if sg * (cand - p.sl) > 0:
                a.new_sl = cand
                a.details.append(f"TP1 pris + creux 15m {sw[-1].price:.6g} au-delà de l'entrée → SL technique {cand:.6g}")
        elif closes_ok:
            a.new_sl = fees_be
            a.details.append(f"TP1 pris + 2 clôtures 15m confirmées → SL à break-even {fees_be:.6g} (frais inclus)")
        else:
            a.details.append("TP1 pris mais structure non confirmée → SL inchangé pour l'instant")
    elif p.tp2_hit and not p.tp3_hit:
        f1h = frames["1h"]
        sw = [s for s in find_swings(f1h.iloc[-60:], 2, 2) if s.kind == ("L" if sg > 0 else "H")]
        if sw:
            cand = sw[-1].price - sg * 0.2 * atr15
            if sg * (cand - p.sl) > 0 and sg * (price - cand) > 0:
                a.new_sl = cand
                a.details.append(f"reliquat 30 % : SL suiveur sous le dernier creux 1h → {cand:.6g}")
        if a.new_sl is None:
            a.details.append("reliquat 30 % : laisser courir, SL inchangé")
            if a.action == HOLD:
                a.action = LET_RUN
    if a.new_sl is not None and a.action == HOLD:
        a.action = MOVE_SL
    # Alerte structure (sans sortie anticipée)
    e20 = float(ema(f15["close"], 20).iloc[-1])
    if sg * (last_close - e20) < 0 and a.action in (HOLD, LET_RUN):
        a.details.append("⚠ structure 15m qui faiblit (clôture de l'autre côté de l'EMA20) — surveiller l'invalidation")
    if a.action == HOLD and not a.details:
        a.details.append("scénario intact — pas d'action")
    return a
