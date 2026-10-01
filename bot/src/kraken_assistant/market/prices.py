"""Prix temps réel (tickers) et conversion EUR <-> devise de cotation."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..api.errors import DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from .models import Instrument, Ticker

log = logging.getLogger(__name__)


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_spot_ticker(key: str, t: dict, now: datetime) -> Ticker | None:
    try:
        last = _f(t["c"][0])
        if last <= 0:
            return None
        return Ticker(key=f"spot:{key}", last=last, bid=_f(t["b"][0]), ask=_f(t["a"][0]),
                      volume_24h_base=_f(t["v"][1]), vwap_24h=_f(t["p"][1]), high_24h=_f(t["h"][1]),
                      low_24h=_f(t["l"][1]), open_ref=_f(t.get("o")) or None, ts=now)
    except (KeyError, IndexError, TypeError):
        return None


def parse_futures_ticker(t: dict, now: datetime) -> Ticker | None:
    last = _f(t.get("last"))
    if last <= 0 or t.get("suspended"):
        return None
    ch = t.get("change24h")
    open_ref = last / (1 + _f(ch) / 100) if ch is not None else None
    return Ticker(key=f"futures:{str(t.get('symbol', '')).upper()}", last=last, bid=_f(t.get("bid")),
                  ask=_f(t.get("ask")), volume_24h_base=_f(t.get("vol24h")),
                  vwap_24h=(_f(t.get("volumeQuote")) / _f(t.get("vol24h"), 1) if _f(t.get("vol24h")) else last),
                  high_24h=_f(t.get("high24h"), last), low_24h=_f(t.get("low24h"), last), open_ref=open_ref,
                  ts=now, open_interest=_f(t.get("openInterest")) or None,
                  funding_rate=_f(t.get("fundingRate")) if t.get("fundingRate") is not None else None)


class PriceService:
    def __init__(self, spot: KrakenSpotClient, futures: KrakenFuturesClient | None):
        self.spot, self.futures = spot, futures
        self.warnings: list[str] = []

    def fetch(self, insts: list[Instrument]) -> dict[str, Ticker]:
        """Récupère tous les tickers en 2-3 appels. Retourne {instrument.key: Ticker}."""
        self.warnings = []
        now = datetime.now(timezone.utc)
        out: dict[str, Ticker] = {}
        raw = self.spot.ticker()  # critique
        for k, v in raw.items():
            if tk := parse_spot_ticker(k, v, now):
                out[tk.key] = tk
        if any(i.api_asset_class == "tokenized_asset" for i in insts):
            try:
                for k, v in self.spot.ticker(asset_class="tokenized_asset").items():
                    if tk := parse_spot_ticker(k, v, now):
                        out[tk.key] = tk
            except DataUnavailable as e:
                self.warnings.append(f"Tickers xStocks indisponibles ({e})")
        if self.futures and any(i.venue == "futures" for i in insts):
            try:
                for t in self.futures.tickers():
                    if tk := parse_futures_ticker(t, now):
                        out[tk.key] = tk
            except DataUnavailable as e:
                self.warnings.append(f"Tickers futures indisponibles ({e})")
        return out


def eur_per_quote(quote: str, insts: list[Instrument], tickers: dict[str, Ticker]) -> float:
    """Combien d'EUR vaut 1 unité de `quote`. Aucune valeur par défaut : lève DataUnavailable si inconnu.

    Méthode : paire EUR/USD Kraken si présente, sinon ratio BTC/EUR ÷ BTC/USD (deux prix réels).
    """
    q = quote.upper()
    if q == "EUR":
        return 1.0
    if q != "USD":
        raise DataUnavailable(f"Conversion {q}->EUR non supportée")
    # 1) paire forex EUR/USD de Kraken (présente dans les tickers même si elle n'est pas un instrument tradé)
    for k in ("spot:ZEURZUSD", "spot:EURUSD"):
        if (t := tickers.get(k)) and t.mid > 0:
            return 1 / t.mid
    # 2) ratio de deux prix réels BTC/EUR ÷ BTC/USD
    for eur_k, usd_k in (("spot:XXBTZEUR", "spot:XXBTZUSD"), ("spot:XETHZEUR", "spot:XETHZUSD")):
        e, u = tickers.get(eur_k), tickers.get(usd_k)
        if e and u and u.mid > 0:
            return e.mid / u.mid
    spot = [i for i in insts if i.venue == "spot"]
    by_base: dict[tuple[str, str], float] = {}
    for i in spot:
        if i.asset_class == "crypto" and i.quote in ("EUR", "USD") and (t := tickers.get(i.key)):
            by_base[(i.base, i.quote)] = t.mid
    for base in ("BTC", "ETH", "SOL"):
        eur, usd = by_base.get((base, "EUR")), by_base.get((base, "USD"))
        if eur and usd:
            return eur / usd
    raise DataUnavailable("Taux EUR/USD introuvable dans les données Kraken")
