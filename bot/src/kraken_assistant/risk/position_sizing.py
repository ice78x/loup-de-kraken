"""risk_manager — calcul de taille de position.

Ordre imposé :
  1. entrée   2. stop logique   3. montant accepté en perte   4. taille   5. levier (en DERNIER)

Le levier ne modifie JAMAIS le montant risqué : il ne détermine que la marge immobilisée.
Formule (frais inclus, taker à l'entrée et à la sortie) :
    perte_par_unité = |entry - SL| + fee × (entry + SL)
    taille = risque_en_devise_de_cotation / perte_par_unité   (arrondie vers le BAS)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

LIQ_SAFETY = 0.5  # le SL doit se trouver avant la moitié de la distance de liquidation


def liq_fraction(lev: float, venue: str = "futures", max_lev: float = 10) -> float:
    """Distance (fraction du prix) de liquidation d'une position isolée, règles Kraken (miroir de site/js/sizing.js) :
    - futures perpétuels EEE : marge de maintenance = moitié de la marge initiale minimale → 1/levier − 0,5/levier max ;
    - spot sur marge : liquidation à 40 % de margin level → 0,6/levier."""
    lev = max(1.0, float(lev or 1))
    if venue == "futures":
        return max(0.005, 1 / lev - 0.5 / max(1.0, float(max_lev or 10)))
    return 0.6 / lev


@dataclass
class SizingInput:
    capital_eur: float
    risk_percent: float
    entry: float
    stop_loss: float
    direction: str                         # "LONG" | "SHORT"
    take_profits: list[float] = field(default_factory=list)
    tp_split: tuple[float, ...] = (0.30, 0.40, 0.30)
    fee_rate_pct: float = 0.0              # frais taker (%, par côté) — appliqués à la sortie au SL
    maker_fee_pct: float | None = None     # frais maker (ordres limite : TP, entrée non immédiate)
    entry_is_maker: bool = False           # True si l'entrée est un ordre limite en attente
    eur_per_quote: float = 1.0             # 1 unité de devise de cotation = x EUR
    ordermin: float = 0.0                  # taille minimale (unités de base)
    costmin: float = 0.0                   # coût minimal (devise de cotation)
    lot_decimals: int = 8
    allowed_leverages: list[int] = field(default_factory=lambda: [1])
    max_leverage: int = 10
    leverage: int | None = None            # levier imposé (optionnel) — n'affecte pas la taille
    available_margin_eur: float | None = None
    venue: str = "spot"


@dataclass
class PositionPlan:
    ok: bool
    errors: list[str]
    warnings: list[str]
    risk_amount_eur: float = 0.0
    position_size: float = 0.0             # unités de base
    notional_quote: float = 0.0
    notional_eur: float = 0.0
    leverage: int = 1
    margin_required_eur: float = 0.0
    estimated_loss_at_sl_eur: float = 0.0
    estimated_profit_tp_eur: list[float] = field(default_factory=list)
    r_multiples: list[float] = field(default_factory=list)       # R brut (distance prix)
    r_multiples_net: list[float] = field(default_factory=list)   # R net de frais (sortie totale à ce TP)
    sl_distance_pct: float = 0.0
    fees_at_sl_eur: float = 0.0
    effective_risk_pct: float = 0.0
    min_risk_required_eur: float | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _floor_step(x: float, decimals: int) -> float:
    step = 10 ** (-decimals)
    return round(math.floor(x / step + 1e-9) * step, max(0, decimals))


def validate_levels(direction: str, entry: float, sl: float, tps: list[float]) -> list[str]:
    errs = []
    if entry <= 0 or sl <= 0:
        errs.append("entrée/SL invalides (<= 0)")
        return errs
    if direction == "LONG" and sl >= entry:
        errs.append("LONG : le SL doit être sous l'entrée")
    if direction == "SHORT" and sl <= entry:
        errs.append("SHORT : le SL doit être au-dessus de l'entrée")
    prev = entry
    for i, tp in enumerate(tps, 1):
        if (direction == "LONG" and tp <= prev) or (direction == "SHORT" and tp >= prev):
            errs.append(f"TP{i} mal ordonné")
        prev = tp
    return errs


def compute_position(p: SizingInput) -> PositionPlan:
    d = p.direction.upper()
    errors = validate_levels(d, p.entry, p.stop_loss, p.take_profits)
    warnings: list[str] = []
    if p.capital_eur <= 0 or p.risk_percent <= 0:
        errors.append("capital ou risque invalide")
    if p.eur_per_quote <= 0:
        errors.append("taux de conversion invalide")
    if errors:
        return PositionPlan(False, errors, warnings)

    fee = p.fee_rate_pct / 100
    fm = (p.maker_fee_pct if p.maker_fee_pct is not None else p.fee_rate_pct) / 100
    fe = fm if p.entry_is_maker else fee
    dist = abs(p.entry - p.stop_loss)
    risk_eur = p.capital_eur * p.risk_percent / 100
    risk_quote = risk_eur / p.eur_per_quote
    per_unit_loss = dist + fe * p.entry + fee * p.stop_loss
    qty = _floor_step(risk_quote / per_unit_loss, p.lot_decimals)

    min_qty = max(p.ordermin, (p.costmin / p.entry) if p.costmin else 0.0)
    min_risk = min_qty * per_unit_loss * p.eur_per_quote if min_qty else None
    if qty <= 0 or qty < p.ordermin - 1e-12 or (p.costmin and qty * p.entry < p.costmin - 1e-9):
        msg = "taille minimale Kraken > taille permise par le risque"
        if min_risk:
            msg += f" (il faudrait risquer {min_risk:.2f} €)"
        return PositionPlan(False, [msg], warnings, risk_amount_eur=risk_eur, min_risk_required_eur=min_risk)

    avail = p.available_margin_eur if p.available_margin_eur is not None else p.capital_eur
    if avail <= 0:
        return PositionPlan(False, ["aucune marge disponible"], warnings, risk_amount_eur=risk_eur)
    sl_frac = dist / p.entry
    allowed = sorted({lv for lv in p.allowed_leverages if 1 <= lv <= p.max_leverage})
    if not allowed:
        return PositionPlan(False, ["aucun levier autorisé pour cette direction"], warnings, risk_amount_eur=risk_eur)

    # Levier max "sûr" : la liquidation (règles Kraken) doit rester au moins 2× plus loin que le SL.
    max_safe = 1
    for lv in range(1, int(p.max_leverage) + 1):
        if sl_frac <= 0 or liq_fraction(lv, p.venue, p.max_leverage) * LIQ_SAFETY >= sl_frac:
            max_safe = lv
    safe_allowed = [lv for lv in allowed if lv == 1 or lv <= max_safe]
    if not safe_allowed:
        return PositionPlan(False, [f"SL trop large ({sl_frac*100:.1f} %) pour les leviers disponibles "
                                    "(risque de liquidation avant le SL)"], warnings, risk_amount_eur=risk_eur)

    def notional_eur(q: float) -> float:
        return q * p.entry * p.eur_per_quote

    required = notional_eur(qty) / avail
    if p.leverage is not None:
        lev = int(p.leverage)
        if lev not in allowed:
            return PositionPlan(False, [f"levier x{lev} non disponible sur cet instrument"], warnings,
                                risk_amount_eur=risk_eur)
        if lev not in safe_allowed:
            return PositionPlan(False, [f"levier x{lev} trop élevé vs SL (liquidation avant SL)"], warnings,
                                risk_amount_eur=risk_eur)
        if lev < required - 1e-9:
            cap_qty = _floor_step(avail * lev / (p.entry * p.eur_per_quote), p.lot_decimals)
            warnings.append(f"marge insuffisante à x{lev} : taille réduite (risque réel plus faible)")
            qty = cap_qty
    else:
        candidates = [lv for lv in safe_allowed if lv >= required - 1e-9]
        if candidates:
            lev = candidates[0]
        else:
            lev = max(safe_allowed)
            qty = _floor_step(avail * lev / (p.entry * p.eur_per_quote), p.lot_decimals)
            warnings.append(f"marge insuffisante : taille réduite à x{lev} (risque réel plus faible que prévu)")
    if qty < p.ordermin - 1e-12 or qty <= 0 or (p.costmin and qty * p.entry < p.costmin - 1e-9):
        return PositionPlan(False, ["taille réduite sous le minimum Kraken"], warnings, risk_amount_eur=risk_eur)

    notional_q = qty * p.entry
    loss_q = qty * dist + qty * (fe * p.entry + fee * p.stop_loss)
    fees_sl_q = qty * (fe * p.entry + fee * p.stop_loss)
    profits, rs, rs_net = [], [], []
    split = list(p.tp_split)[: len(p.take_profits)]
    if p.take_profits and abs(sum(split) - 1) > 1e-6:
        split = [s / sum(split) for s in split]
    for tp, part in zip(p.take_profits, split):
        q = qty * part
        profits.append(round((q * abs(tp - p.entry) - q * (fe * p.entry + fm * tp)) * p.eur_per_quote, 4))
        rs.append(round(abs(tp - p.entry) / dist, 2))
        rs_net.append(round((abs(tp - p.entry) - fe * p.entry - fm * tp) / per_unit_loss, 2))
    loss_eur = loss_q * p.eur_per_quote
    if fees_sl_q / loss_q > 0.35:
        warnings.append(f"frais = {fees_sl_q / loss_q * 100:.0f} % de la perte au SL (SL très serré vs frais)")
    return PositionPlan(
        ok=True, errors=[], warnings=warnings, risk_amount_eur=round(risk_eur, 4), position_size=qty,
        notional_quote=round(notional_q, 6), notional_eur=round(notional_eur(qty), 4), leverage=lev,
        margin_required_eur=round(notional_eur(qty) / lev, 4), estimated_loss_at_sl_eur=round(loss_eur, 4),
        estimated_profit_tp_eur=profits, r_multiples=rs, r_multiples_net=rs_net, sl_distance_pct=round(sl_frac * 100, 4),
        fees_at_sl_eur=round(fees_sl_q * p.eur_per_quote, 4),
        effective_risk_pct=round(loss_eur / p.capital_eur * 100, 4), min_risk_required_eur=min_risk,
    )
