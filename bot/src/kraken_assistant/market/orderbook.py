"""Carnet d'ordres : spread et profondeur réelle autour du prix (liquidité exécutable)."""
from __future__ import annotations

from dataclasses import dataclass

from ..api.errors import DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from .models import Instrument


@dataclass
class BookStats:
    best_bid: float
    best_ask: float
    spread_pct: float
    bid_depth_quote: float   # valeur (devise de cotation) cumulée dans -band %
    ask_depth_quote: float   # valeur cumulée dans +band %
    band_pct: float


def book_stats(bids: list, asks: list, band_pct: float = 0.5) -> BookStats:
    if not bids or not asks:
        raise DataUnavailable("carnet d'ordres vide")
    b = [(float(x[0]), float(x[1])) for x in bids]
    a = [(float(x[0]), float(x[1])) for x in asks]
    bb, ba = max(p for p, _ in b), min(p for p, _ in a)
    if ba <= bb:
        raise DataUnavailable("carnet incohérent (ask <= bid)")
    mid = (bb + ba) / 2
    lo, hi = mid * (1 - band_pct / 100), mid * (1 + band_pct / 100)
    return BookStats(bb, ba, (ba - bb) / mid * 100, sum(p * q for p, q in b if p >= lo),
                     sum(p * q for p, q in a if p <= hi), band_pct)


class OrderBookService:
    def __init__(self, spot: KrakenSpotClient, futures: KrakenFuturesClient | None):
        self.spot, self.futures = spot, futures

    def stats(self, inst: Instrument, band_pct: float = 0.5) -> BookStats:
        if inst.venue == "spot":
            d = self.spot.depth(inst.symbol, 100, inst.api_asset_class)
            return book_stats(d.get("bids", []), d.get("asks", []), band_pct)
        if not self.futures:
            raise DataUnavailable("client futures désactivé")
        payload = self.futures.http.request("GET", "/derivatives/api/v3/orderbook", params={"symbol": inst.symbol})
        ob = (payload or {}).get("orderBook", {})
        return book_stats(ob.get("bids", []), ob.get("asks", []), band_pct)
