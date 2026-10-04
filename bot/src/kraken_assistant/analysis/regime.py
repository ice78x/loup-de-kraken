"""Régime de marché (moteur v2) : décidé AVANT de choisir une stratégie.

Règles objectives, calculées uniquement sur des bougies clôturées :
  - structure HH/HL/LH/LL en 4h et 1h, tendance journalière ;
  - efficacité du mouvement 4h (ratio de Kaufman : déplacement net / chemin parcouru, 0 = zigzag, 1 = ligne droite) ;
  - pente de l'EMA50 1h en ATR ;
  - volatilité 1h vs sa médiane (volatility_report) ;
  - cassure récente du range 4h.

Régimes :
  TREND_UP / TREND_DOWN   tendance lisible → pullback ou cassure dans le sens de la tendance
  RANGE                   marché latéral net → rejet des bornes du range
  BREAKOUT_UP / _DOWN     sortie récente du range 4h → cassure + retest dans le sens de la sortie
  HIGH_VOL                volatilité extrême → pas de nouveau trade
  CHAOTIC                 unités de temps en conflit + mouvement désordonné → pas de trade
  UNCERTAIN               rien de net → pas de trade
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import atr, ema
from .structure import StructureReport, analyze_structure
from .volatility import VolatilityReport, volatility_report

TREND_UP, TREND_DOWN, RANGE = "TREND_UP", "TREND_DOWN", "RANGE"
BREAKOUT_UP, BREAKOUT_DOWN = "BREAKOUT_UP", "BREAKOUT_DOWN"
HIGH_VOL, CHAOTIC, UNCERTAIN = "HIGH_VOL", "CHAOTIC", "UNCERTAIN"
NO_TRADE_REGIMES = (HIGH_VOL, CHAOTIC, UNCERTAIN)

LABELS = {TREND_UP: "Tendance haussière", TREND_DOWN: "Tendance baissière", RANGE: "Range",
          BREAKOUT_UP: "Cassure haussière", BREAKOUT_DOWN: "Cassure baissière", HIGH_VOL: "Volatilité extrême",
          CHAOTIC: "Marché chaotique", UNCERTAIN: "Régime incertain"}

# Stratégie adaptée à chaque régime : (stratégie, direction autorisée). Tout le reste est refusé.
ALLOWED: dict[str, set[tuple[str, str]]] = {
    TREND_UP: {("tendance_pullback", "LONG"), ("cassure_retest", "LONG"), ("rejet_sweep", "LONG")},
    TREND_DOWN: {("tendance_pullback", "SHORT"), ("cassure_retest", "SHORT"), ("rejet_sweep", "SHORT")},
    RANGE: {("rejet_sweep", "LONG"), ("rejet_sweep", "SHORT")},
    BREAKOUT_UP: {("cassure_retest", "LONG")},
    BREAKOUT_DOWN: {("cassure_retest", "SHORT")},
}


@dataclass
class Regime:
    name: str = UNCERTAIN
    confidence: float = 0.0           # 0..1
    efficiency_4h: float | None = None
    ema_slope_1h: float | None = None  # pente EMA50 1h sur 10 bougies, en ATR 1h
    vol_regime: str = "normale"
    move_4h_atr: float = 0.0           # déplacement des 4 dernières heures, en ATR 1h (signé)
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)

    @property
    def bias(self) -> str | None:
        """Direction favorisée par le régime (None = aucune)."""
        if self.name in (TREND_UP, BREAKOUT_UP):
            return "LONG"
        if self.name in (TREND_DOWN, BREAKOUT_DOWN):
            return "SHORT"
        return None

    def allows(self, strategy: str, direction: str) -> bool:
        return (strategy, direction) in ALLOWED.get(self.name, set())

    def as_dict(self) -> dict:
        return {"regime": self.name, "confiance": round(self.confidence, 2), "efficacite_4h": _r(self.efficiency_4h),
                "pente_ema_1h": _r(self.ema_slope_1h), "volatilite": self.vol_regime, "mouvement_4h_atr": _r(self.move_4h_atr)}


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def efficiency_ratio(close: pd.Series, n: int = 20) -> float | None:
    c = close.to_numpy(dtype=float)[-(n + 1):]
    if len(c) < n + 1:
        return None
    path = float(np.abs(np.diff(c)).sum())
    return abs(c[-1] - c[0]) / path if path > 0 else 0.0


def classify_regime(s4: StructureReport, s1: StructureReport, daily_trend: str, vol: VolatilityReport,
                    h1: pd.DataFrame, h4: pd.DataFrame) -> Regime:
    rg = Regime(vol_regime=vol.regime)
    er = efficiency_ratio(h4["close"], 20)
    rg.efficiency_4h = er
    a1 = float(atr(h1).iloc[-1]) if len(h1) > 15 else float("nan")
    e50 = ema(h1["close"], 50)
    if len(e50.dropna()) > 11 and a1 > 0:
        rg.ema_slope_1h = float((e50.iloc[-1] - e50.iloc[-11]) / a1)
    if len(h1) > 5 and a1 > 0:
        rg.move_4h_atr = float((h1["close"].iloc[-1] - h1["close"].iloc[-5]) / a1)
    if er is None or not np.isfinite(a1) or a1 <= 0:
        rg.reasons.append("historique 4h/1h insuffisant")
        return rg
    slope = rg.ema_slope_1h or 0.0

    if vol.regime == "extrême":
        rg.name, rg.confidence = HIGH_VOL, 1.0
        rg.reasons.append(f"volatilité 1h ×{vol.ratio_vs_median:.1f} sa médiane")
        return rg

    # Cassure récente du range 4h (les 20 bougies 4h AVANT les 2 dernières) : clôture 1h au-delà de ±0,3 ATR 1h
    if len(h4) >= 24:
        box = h4.iloc[-22:-2]
        top, bot = float(box["high"].max()), float(box["low"].min())
        last = h1["close"].iloc[-8:]
        if (last > top + 0.3 * a1).any() and h1["close"].iloc[-1] > top:
            rg.name, rg.confidence = BREAKOUT_UP, min(1.0, 0.5 + 0.5 * min(er / 0.5, 1))
            rg.reasons.append(f"clôture au-dessus du range 4h ({top:.6g})")
            return rg
        if (last < bot - 0.3 * a1).any() and h1["close"].iloc[-1] < bot:
            rg.name, rg.confidence = BREAKOUT_DOWN, min(1.0, 0.5 + 0.5 * min(er / 0.5, 1))
            rg.reasons.append(f"clôture sous le range 4h ({bot:.6g})")
            return rg

    conflict = {s4.trend, s1.trend} == {"up", "down"}
    if conflict and er < 0.25:
        rg.name, rg.confidence = CHAOTIC, 1.0
        rg.reasons.append(f"4h {s4.trend} contre 1h {s1.trend}, mouvement désordonné (efficacité {er:.2f})")
        return rg

    for d, name, sgn in (("up", TREND_UP, 1), ("down", TREND_DOWN, -1)):
        if s4.trend == d and s1.trend != ("down" if d == "up" else "up") and er >= 0.25 and sgn * slope > 0:
            votes = sum([s1.trend == d, daily_trend == d, s4.ema_bias == d, sgn * slope >= 0.5])
            rg.name = name
            rg.confidence = round(min(1.0, 0.4 + 0.15 * votes + 0.3 * min(er / 0.6, 1)) , 3)
            rg.reasons.append(f"structure 4h {d} · 1h {s1.trend} · jour {daily_trend} · efficacité {er:.2f}")
            return rg

    if s4.trend == "range" and s1.trend != ("up" if slope > 0.5 else "down" if slope < -0.5 else "x") and er < 0.3 \
            and abs(slope) < 0.8:
        rg.name = RANGE
        rg.confidence = round(min(1.0, 0.5 + (0.3 - er) / 0.3 * 0.5), 3)
        rg.reasons.append(f"4h en range, efficacité {er:.2f}, EMA 1h plate ({slope:+.2f} ATR)")
        return rg

    rg.reasons.append(f"rien de net : 4h {s4.trend} / 1h {s1.trend}, efficacité {er:.2f}, pente {slope:+.2f}")
    return rg


def regime_from_analysis(a) -> Regime:
    """Depuis une MarketAnalysis déjà calculée (scanner / backtest)."""
    return classify_regime(a.structures["4h"], a.structures["1h"], a.htf.daily_trend, a.vol,
                           a.frames["1h"], a.frames["4h"])


def regime_from_frames(h1: pd.DataFrame, h4: pd.DataFrame, daily_trend: str = "inconnu") -> Regime:
    """Depuis des bougies brutes (contexte BTC/ETH)."""
    if len(h1) < 60 or len(h4) < 24:
        return Regime(reasons=["historique insuffisant"])
    h1w, h4w = h1.iloc[-600:], h4.iloc[-400:]
    return classify_regime(analyze_structure(h4w, "4h", 2, 2), analyze_structure(h1w, "1h", 3, 3), daily_trend,
                           volatility_report(h1w), h1w, h4w)


# ----------------------------------------------------------------------------------------- contexte BTC / ETH
@dataclass
class MarketContext:
    btc: Regime | None = None
    eth: Regime | None = None

    def check(self, base: str, asset_class: str, direction: str) -> tuple[str, float, list[str]]:
        """Verdict pour une altcoin : ("bloque" | "contre" | "neutre" | "favorable", points 0..5, raisons).
        Ne s'applique pas à BTC lui-même, ni aux xStocks / matières premières."""
        if asset_class != "crypto" or base in ("BTC", "XBT") or self.btc is None or self.btc.name == UNCERTAIN and \
                not self.btc.reasons:
            return "neutre", 2.5, []
        b, e = self.btc, self.eth
        sgn = 1 if direction == "LONG" else -1
        why: list[str] = []
        if b.name == HIGH_VOL:
            return "bloque", 0.0, ["BTC en volatilité extrême : pas de trade sur les altcoins"]
        if sgn * b.move_4h_atr <= -2.5:
            return "bloque", 0.0, [f"BTC vient de bouger fort contre le trade ({b.move_4h_atr:+.1f} ATR en 4 h)"]
        against_b = b.bias is not None and b.bias != direction
        against_e = e is not None and e.bias is not None and e.bias != direction
        if against_b and (against_e or b.confidence >= 0.7):
            return "bloque", 0.0, [f"BTC {b.label.lower()} contre le {direction}" + (" (ETH aussi)" if against_e else "")]
        if against_b:
            return "contre", 0.5, [f"BTC {b.label.lower()} contre le {direction}"]
        if b.bias == direction:
            why.append(f"BTC {b.label.lower()} dans le sens du trade")
            return "favorable", 5.0 if not against_e else 3.5, why
        if b.name == CHAOTIC:
            return "contre", 1.0, ["BTC chaotique"]
        return "neutre", 2.5, []
