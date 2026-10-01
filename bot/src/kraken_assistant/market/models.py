from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def normalize_base(sym: str) -> str:
    """Normalise les codes Kraken historiques (XXBT, XBT, XETH, ZUSD...)."""
    s = sym.upper().split(".")[0]
    legacy = {"XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM",
              "XXDG": "DOGE", "XDG": "DOGE", "XETC": "ETC", "XXMR": "XMR", "XZEC": "ZEC", "XREP": "REP",
              "XMLN": "MLN", "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP", "ZCAD": "CAD", "ZJPY": "JPY",
              "ZAUD": "AUD", "ZCHF": "CHF"}
    return legacy.get(s, s)


@dataclass
class Instrument:
    symbol: str            # identifiant utilisé par l'API (clé AssetPairs spot ou symbol futures)
    display: str           # ex. "LINK/EUR", "PF_LINKUSD"
    venue: str             # "spot" | "futures"
    asset_class: str       # "crypto" | "xstock" | "commodity" | "tradfi"
    kind: str              # "spot" | "perpetual" | "future"
    base: str
    quote: str
    status: str
    tradable: bool
    can_long: bool
    can_short: bool
    max_leverage_long: int = 1
    max_leverage_short: int = 0
    allowed_leverages_long: list[int] = field(default_factory=lambda: [1])
    allowed_leverages_short: list[int] = field(default_factory=list)
    ordermin: float = 0.0
    costmin: float = 0.0
    tick_size: float = 0.0
    lot_decimals: int = 8
    pair_decimals: int = 8
    contract_size: float = 1.0
    taker_fee_pct: float | None = None
    fee_source: str = "défaut (estimation)"
    api_asset_class: str | None = None   # "tokenized_asset" pour les xStocks
    account_access: str = "non vérifié"  # "vérifié" | "non vérifié" | "refusé"
    constraints: list[str] = field(default_factory=list)
    altname: str = ""

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.symbol}"

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["key"] = self.key
        return d


@dataclass
class Ticker:
    key: str
    last: float
    bid: float
    ask: float
    volume_24h_base: float
    vwap_24h: float
    high_24h: float
    low_24h: float
    open_ref: float | None
    ts: datetime
    open_interest: float | None = None
    funding_rate: float | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid > 0 and self.ask > 0 else self.last

    @property
    def spread_pct(self) -> float | None:
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            return None
        return (self.ask - self.bid) / self.mid * 100

    @property
    def change_24h_pct(self) -> float | None:
        if not self.open_ref:
            return None
        return (self.last / self.open_ref - 1) * 100

    @property
    def range_24h_pct(self) -> float:
        return (self.high_24h - self.low_24h) / self.last * 100 if self.last else 0.0
