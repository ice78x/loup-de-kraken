"""Liquidité : volume 24h en EUR, spread, profondeur du carnet, zones de stops, proxy de liquidations."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..market.models import Ticker
from ..market.orderbook import BookStats


@dataclass
class LiquidityReport:
    volume_24h_eur: float
    spread_pct: float | None
    book: BookStats | None = None
    ok: bool = True
    issues: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        v = self.volume_24h_eur
        s = 1.0 if v > 20e6 else 0.8 if v > 3e6 else 0.6 if v > 5e5 else 0.4
        if self.spread_pct is not None and self.spread_pct > 0.15:
            s -= 0.2
        return max(0.0, s)


def liquidity_report(t: Ticker, eur_per_quote: float, min_vol_eur: float, max_spread_pct: float,
                     is_futures: bool) -> LiquidityReport:
    vol_quote = t.volume_24h_base * (t.vwap_24h or t.last)
    rep = LiquidityReport(vol_quote * eur_per_quote, t.spread_pct)
    if rep.volume_24h_eur < min_vol_eur:
        rep.ok = False
        rep.issues.append(f"liquidité insuffisante (volume 24h ≈ {rep.volume_24h_eur:,.0f} €)")
    if rep.spread_pct is None:
        rep.ok = False
        rep.issues.append("spread indisponible")
    elif rep.spread_pct > max_spread_pct:
        rep.ok = False
        rep.issues.append(f"spread trop élevé ({rep.spread_pct:.2f} %)")
    return rep


def check_book(rep: LiquidityReport, book: BookStats, notional_quote: float, max_spread_pct: float,
               min_depth_multiple: float = 10.0) -> None:
    rep.book = book
    if book.spread_pct > max_spread_pct * 1.5:
        rep.ok = False
        rep.issues.append(f"spread anormal dans le carnet ({book.spread_pct:.2f} %)")
    depth = min(book.bid_depth_quote, book.ask_depth_quote)
    if notional_quote > 0 and depth < notional_quote * min_depth_multiple:
        rep.ok = False
        rep.issues.append("profondeur de carnet insuffisante pour sortir proprement")


def stop_cluster_zones(df: pd.DataFrame, swings_high: list[float], swings_low: list[float]) -> dict[str, list[float]]:
    """Zones où les stops s'accumulent typiquement : juste au-delà des derniers swings (liquidité)."""
    return {"au-dessus": sorted(swings_high[-3:]), "en-dessous": sorted(swings_low[-3:], reverse=True)}


def liquidation_proxy(prev_oi: float | None, oi: float | None, price_change_pct: float) -> str | None:
    """Kraken ne publie pas de flux agrégé de liquidations. Proxy : forte baisse d'open interest
    simultanée à un mouvement de prix brutal. C'est une INTERPRÉTATION, pas une donnée de liquidation."""
    if not prev_oi or not oi:
        return None
    d_oi = (oi / prev_oi - 1) * 100
    if d_oi <= -5 and abs(price_change_pct) >= 2:
        side = "longs" if price_change_pct < 0 else "shorts"
        return f"liquidations probables des {side} (OI {d_oi:+.1f} %, prix {price_change_pct:+.1f} %)"
    return None
