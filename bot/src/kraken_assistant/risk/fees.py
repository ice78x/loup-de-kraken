"""Frais Kraken Pro par défaut (quand le bot n'a pas les frais réels de ton compte). Miroir de site/js/fees.js.

Grille officielle vérifiée le 01/10/2026 sur https://www.kraken.com/features/fee-schedule (niveau d'entrée, 0 $ de volume) :
- Futures (perpétuels) : maker 0,02 % · taker 0,05 %
- xStocks sur Kraken Pro : taker 0,10 % (0,08 % à partir du 05/10/2026), maker -0,02 % puis 0 % → on compte 0 % (prudent)
- Paires stablecoin / devises : 0,20 % maker et taker
- Spot crypto (depuis le 09/07/2026) : maker 0,40 % · taker 0,80 %
Les niveaux baissent avec ton volume sur 30 jours : avec une clé API, le bot lit tes frais réels.
"""
from __future__ import annotations

from datetime import datetime, timezone

XSTOCK_CHANGE = datetime(2026, 10, 5, tzinfo=timezone.utc)
STABLES = {"USDT", "USDC", "DAI", "PYUSD", "USDG", "EURC", "RLUSD", "USDS", "FDUSD", "TUSD", "USDE", "EUROP", "EURQ", "EURR",
           "USD", "EUR", "GBP", "CHF", "CAD", "AUD", "JPY"}


def default_fees(venue: str, asset_class: str, base: str, quote: str, now: datetime | None = None) -> tuple[float, float, str]:
    """(taker %, maker %, libellé)."""
    now = now or datetime.now(timezone.utc)
    if venue == "futures":
        return 0.05, 0.02, "futures Kraken (niveau d'entrée)"
    if asset_class == "xstock":
        return (0.08 if now >= XSTOCK_CHANGE else 0.10), 0.0, "xStocks Kraken Pro"
    if str(base).upper() in STABLES and str(quote).upper() in STABLES:
        return 0.20, 0.20, "paire stablecoin / devise"
    return 0.80, 0.40, "spot Kraken Pro (niveau d'entrée)"
