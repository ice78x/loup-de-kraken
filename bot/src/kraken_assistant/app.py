"""Conteneur applicatif : instancie une seule fois settings, base, clients API et services."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from .api.errors import AuthMissing, DataUnavailable
from .api.kraken_futures import KrakenFuturesClient
from .api.kraken_spot import KrakenSpotClient
from .config import Settings, get_settings
from .database.db import Database
from .risk.fees import default_fees
from .execution.live import LiveBroker
from .execution.paper import PaperBroker
from .logging_setup import setup_logging
from .market.candles import CandleService
from .market.history import CandleStore, HistoryService
from .market.instruments import InstrumentDiscovery, Taxonomy
from .market.models import Instrument
from .market.orderbook import OrderBookService
from .market.prices import PriceService
from .news.engine import NewsEngine
from .portfolio.pnl import paper_capital
from .portfolio.positions import KrakenPositionSync, PositionStore
from .risk.portfolio_risk import PortfolioRiskManager

log = logging.getLogger(__name__)


@dataclass
class App:
    settings: Settings
    db: Database
    spot: KrakenSpotClient
    futures: KrakenFuturesClient | None
    taxonomy: Taxonomy
    discovery: InstrumentDiscovery
    prices: PriceService
    candles: CandleService
    books: OrderBookService
    news: NewsEngine
    positions: PositionStore
    kraken_sync: KrakenPositionSync
    risk: PortfolioRiskManager
    paper: PaperBroker
    live: LiveBroker
    scan_lock: threading.Lock = field(default_factory=threading.Lock)
    state: dict[str, Any] = field(default_factory=dict)
    fee_cache: dict[str, float] = field(default_factory=dict)
    history: HistoryService | None = None

    @classmethod
    def build(cls, settings: Settings | None = None, spot_transport=None, futures_transport=None,
              news_transport=None, db: Database | None = None) -> "App":
        s = settings or get_settings()
        setup_logging(s)
        db = db or Database(s.db_path)
        spot = KrakenSpotClient(s, transport=spot_transport)
        fut = KrakenFuturesClient(s, transport=futures_transport) if s.futures_enabled else None
        tax = Taxonomy.load(s)
        if db.kv_get("paper_initial_capital") is None:
            db.kv_set("paper_initial_capital", s.capital_eur)
        candles = CandleService(spot, fut)
        history = HistoryService(CandleStore(db), spot, fut)
        candles.history = history
        return cls(
            history=history, settings=s, db=db, spot=spot, futures=fut, taxonomy=tax,
            discovery=InstrumentDiscovery(s, spot, fut, tax), prices=PriceService(spot, fut),
            candles=candles, books=OrderBookService(spot, fut),
            news=NewsEngine(s, transport=news_transport), positions=PositionStore(db),
            kraken_sync=KrakenPositionSync(db, spot, fut, s.default_spot_taker_fee_pct, s.default_futures_taker_fee_pct),
            risk=PortfolioRiskManager(s), paper=PaperBroker(db, s), live=LiveBroker(s, db, spot, fut),
        )

    # ------------------------------------------------------------------
    def capital(self) -> dict:
        """Capital utilisé pour le risque. Paper : capital paper. Live armé : equity Kraken (EUR)."""
        initial = float(self.db.kv_get("paper_initial_capital", self.settings.capital_eur))
        pc = paper_capital(self.db, initial)
        out = {"mode": "PAPER", "risk_capital_eur": pc["equity"], "paper": pc, "kraken_equity_eur": None}
        if self.settings.has_spot_keys:
            try:
                tb = self.spot.trade_balance("ZEUR")
                out["kraken_equity_eur"] = float(tb.get("e", tb.get("eb", 0)))
            except (AuthMissing, DataUnavailable) as e:
                out["kraken_error"] = str(e)
        if self.settings.live_armed:
            if out["kraken_equity_eur"] is None:
                raise DataUnavailable("LIVE armé mais capital Kraken illisible — DATA INSUFFISANTE")
            out.update(mode="LIVE", risk_capital_eur=out["kraken_equity_eur"])
        return out

    def fee_for(self, inst: Instrument) -> tuple[float, float, str]:
        """(taker %, maker %, source). Frais réels du compte si clé API, sinon valeurs par défaut."""
        if inst.key in self.fee_cache:
            t, m = self.fee_cache[inst.key]
            return t, m, "Kraken (compte)"
        if inst.venue == "spot" and self.settings.has_spot_keys:
            try:
                tv = self.spot.trade_volume([inst.symbol])
                fees, fees_m = tv.get("fees", {}), tv.get("fees_maker", {})
                if fees:
                    t = float(next(iter(fees.values()))["fee"])
                    m = float(next(iter(fees_m.values()))["fee"]) if fees_m else t
                    self.fee_cache[inst.key] = (t, m)
                    return t, m, "Kraken (compte)"
            except (AuthMissing, DataUnavailable, KeyError, ValueError, StopIteration):
                pass
        s = self.settings
        if inst.venue != "spot":
            return s.default_futures_taker_fee_pct, s.default_futures_maker_fee_pct, "défaut (estimation)"
        t, m, label = default_fees(inst.venue, inst.asset_class, inst.base, inst.quote)
        if label.startswith("spot") and s.execution_venue == "futures":  # tradé sur le perpétuel correspondant
            return s.default_futures_taker_fee_pct, s.default_futures_maker_fee_pct, "défaut futures perpétuels (estimation)"
        if label.startswith("spot"):  # spot crypto : valeurs réglables (.env)
            return s.default_spot_taker_fee_pct, s.default_spot_maker_fee_pct, "défaut (estimation)"
        return t, m, f"défaut {label} (estimation)"  # xStocks, stablecoins : grille Kraken
