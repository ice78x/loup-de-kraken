"""portfolio_risk_manager — risque cumulé, perte du jour, corrélation, exposition directionnelle."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..portfolio.positions import Position


@dataclass
class PositionRisk:
    position_id: int
    display: str
    base: str
    direction: str
    asset_class: str
    risk_eur: float
    assumed: bool   # True si SL inconnu -> hypothèse prudente


@dataclass
class RiskSnapshot:
    capital_eur: float
    open_risk_eur: float
    open_risk_pct: float
    max_open_risk_eur: float
    available_risk_eur: float
    realized_today_eur: float
    daily_limit_eur: float
    daily_limit_hit: bool
    positions: list[PositionRisk] = field(default_factory=list)
    exposure: dict[str, int] = field(default_factory=dict)  # ex. {"crypto LONG": 1}
    notes: list[str] = field(default_factory=list)

    @property
    def available_risk_pct(self) -> float:
        return self.available_risk_eur / self.capital_eur * 100 if self.capital_eur else 0.0


@dataclass
class Decision:
    ok: bool
    risk_pct: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PortfolioRiskManager:
    def __init__(self, settings: Settings):
        self.s = settings

    def position_risk(self, p: Position, capital: float) -> PositionRisk:
        rq = p.remaining_risk_quote()
        if rq is None or p.eur_per_quote is None:
            return PositionRisk(p.id, p.display, p.base, p.direction, p.asset_class,
                                capital * self.s.risk_normal_pct / 100, True)
        return PositionRisk(p.id, p.display, p.base, p.direction, p.asset_class, rq * p.eur_per_quote, False)

    def snapshot(self, capital: float, positions: list[Position], realized_today_eur: float) -> RiskSnapshot:
        prs = [self.position_risk(p, capital) for p in positions if p.status == "open"]
        open_risk = sum(r.risk_eur for r in prs)
        max_open = capital * self.s.max_open_risk_pct / 100
        daily_limit = capital * self.s.max_daily_loss_pct / 100
        loss_today = max(0.0, -realized_today_eur)
        # Budget = min(plafond risque ouvert, marge restante avant la limite journalière)
        avail = max(0.0, min(max_open - open_risk, daily_limit - loss_today - open_risk))
        exposure: dict[str, int] = {}
        for r in prs:
            k = f"{r.asset_class or '?'} {r.direction}"
            exposure[k] = exposure.get(k, 0) + 1
        notes = [f"{r.display}: SL inconnu — risque compté par hypothèse ({r.risk_eur:.2f} €). Renseigne le SL."
                 for r in prs if r.assumed]
        return RiskSnapshot(capital, round(open_risk, 4), round(open_risk / capital * 100, 3) if capital else 0,
                            max_open, round(avail, 4), round(realized_today_eur, 4), daily_limit,
                            loss_today >= daily_limit - 1e-9, prs, exposure, notes)

    def allowed_risk_pct(self, snap: RiskSnapshot, exceptional: bool) -> Decision:
        if snap.daily_limit_hit:
            return Decision(False, 0.0, ["STOP : perte journalière max atteinte — aucun nouveau trade aujourd'hui"])
        wanted = self.s.risk_exceptional_pct if exceptional else self.s.risk_normal_pct
        avail = snap.available_risk_pct
        if avail + 1e-9 < self.s.risk_min_pct:
            return Decision(False, 0.0, [f"risque cumulé trop important (disponible {avail:.2f} %)"])
        pct = min(wanted, avail)
        warns = [f"risque réduit à {pct:.2f} % (budget disponible)"] if pct < wanted - 1e-9 else []
        return Decision(True, round(pct, 4), [], warns)

    def check_candidate(self, snap: RiskSnapshot, base: str, direction: str,
                        correlations: dict[int, float]) -> Decision:
        """correlations : {position_id: corrélation des rendements 1h avec le candidat}."""
        reasons, warns = [], []
        for r in snap.positions:
            if r.base and r.base == base:
                reasons.append(f"position déjà ouverte sur {base} ({r.direction})")
                continue
            c = correlations.get(r.position_id)
            if c is None:
                continue
            if abs(c) >= self.s.correlation_block:
                same_way = (r.direction == direction) == (c > 0)
                if same_way:
                    reasons.append(f"trop corrélé à {r.display} {r.direction} (corr {c:+.2f}) — double exposition")
                else:
                    reasons.append(f"contradictoire avec {r.display} {r.direction} (corr {c:+.2f})")
            elif abs(c) >= 0.5:
                warns.append(f"corrélation modérée avec {r.display} ({c:+.2f})")
        return Decision(not reasons, 0.0, reasons, warns)
