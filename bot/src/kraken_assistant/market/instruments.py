"""instrument_discovery : découvre dynamiquement les instruments réellement disponibles.

Aucune liste d'instruments codée en dur : tout vient de
  - Spot    : /0/public/AssetPairs?country_code=FR (crypto) et aclass_base=tokenized_asset (xStocks)
  - Futures : /derivatives/api/v3/instruments (perpétuels, filtrés par countriesBanned)
La taxonomie (config/classification.toml) sert seulement à CLASSER (ex. PAXG = matière première).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from ..api.errors import AuthMissing, DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from ..config import Settings
from .models import Instrument, normalize_base

log = logging.getLogger(__name__)

SPOT_TRADABLE_STATUS = {"online", "limit_only", "post_only"}


@dataclass
class Taxonomy:
    commodities: set[str]
    excluded: set[str]
    quotes: list[str]
    aliases: dict[str, str]

    @classmethod
    def load(cls, settings: Settings) -> "Taxonomy":
        cfg = settings.load_toml("classification.toml")
        return cls(
            commodities={b.upper() for b in cfg.get("commodities", {}).get("bases", [])},
            excluded={b.upper() for b in cfg.get("exclude", {}).get("bases", [])},
            quotes=[q.upper() for q in (settings.quote_currencies or cfg.get("quotes", {}).get("preferred", ["USD"]))],
            aliases={k.lower(): v.upper() for k, v in cfg.get("aliases", {}).items()},
        )


def underlying_of(base: str, api_asset_class: str | None) -> str:
    """xStocks : 'TSLAX' -> 'TSLA'. Crypto : inchangé."""
    b = base.upper()
    if api_asset_class == "tokenized_asset" and b.endswith("X") and len(b) > 2:
        return b[:-1]
    return b


def parse_spot_pair(key: str, info: dict, tax: Taxonomy, api_asset_class: str | None) -> Instrument | None:
    altname = info.get("altname", key)
    if altname.endswith(".d"):  # dark pool
        return None
    base = normalize_base(info.get("base", ""))
    quote = normalize_base(info.get("quote", ""))
    if quote not in tax.quotes or base in tax.excluded:
        return None
    status = str(info.get("status", "unknown"))
    under = underlying_of(base, api_asset_class)
    if under in tax.commodities or base in tax.commodities:
        aclass = "commodity"
    elif api_asset_class == "tokenized_asset":
        aclass = "xstock"
    else:
        aclass = "crypto"
    lev_buy = sorted({int(x) for x in info.get("leverage_buy", []) or []})
    lev_sell = sorted({int(x) for x in info.get("leverage_sell", []) or []})
    constraints: list[str] = []
    if status != "online":
        constraints.append(f"statut Kraken: {status}")
    if not lev_sell:
        constraints.append("SHORT indisponible (pas de marge vente)")
    tradable = status in SPOT_TRADABLE_STATUS
    display = str(info.get("wsname") or altname)
    if display.startswith("XBT/"):
        display = "BTC/" + display[4:]
    return Instrument(
        symbol=key, display=display, venue="spot", asset_class=aclass, kind="spot",
        base=under, quote=quote, status=status, tradable=tradable,
        can_long=tradable, can_short=tradable and bool(lev_sell),
        max_leverage_long=max([1, *lev_buy]), max_leverage_short=max(lev_sell) if lev_sell else 0,
        allowed_leverages_long=[1, *[x for x in lev_buy if x > 1]], allowed_leverages_short=lev_sell,
        ordermin=float(info.get("ordermin") or 0), costmin=float(info.get("costmin") or 0),
        tick_size=float(info.get("tick_size") or 0), lot_decimals=int(info.get("lot_decimals", 8)),
        pair_decimals=int(info.get("pair_decimals", 8)), api_asset_class=api_asset_class,
        constraints=constraints, altname=altname,
    )


def tick_decimals(tick: float, default: int = 8) -> int:
    """Nombre de décimales d'un pas de prix Kraken (0.000001 → 6, 0.5 → 1, 1 → 0). 0 ou inconnu → default."""
    if not tick or tick <= 0:
        return default
    for d in range(0, 13):
        if abs(round(tick, d) - tick) < tick * 1e-6:
            return d
    return default


def classify_xstock_perps(insts: list[Instrument]) -> int:
    """Perpétuels sur actions (PF_NVDAXUSD, PF_TSLAXUSD, PF_SPYXUSD…) : Kraken les liste comme des futures « crypto ».
    On les reconnaît grâce aux xStocks spot (NVDAx, TSLAx…) et on les range avec les actions (base = action sous-jacente)."""
    xbases = {i.base.upper() for i in insts if i.asset_class == "xstock"}
    n = 0
    for i in insts:
        b = (i.base or "").upper()
        if i.venue == "futures" and i.asset_class == "crypto" and b.endswith("X") and len(b) > 2 and b[:-1] in xbases:
            i.asset_class, i.base = "xstock", b[:-1]
            n += 1
    return n


def us_market_open(now=None) -> bool:
    """Bourse américaine ouverte (lun–ven, 9 h 30 – 16 h à New York, jours fériés non gérés)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    t = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    return t.weekday() < 5 and (t.hour, t.minute) >= (9, 30) and t.hour < 16


def _max_lev_from_margin(levels: list[dict] | None) -> int:
    if not levels:
        return 0
    im = levels[0].get("initialMargin")
    try:
        return int(math.floor(1 / float(im) + 1e-9)) if im else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def parse_futures_instrument(info: dict, tax: Taxonomy, country: str, max_leverage: int) -> Instrument | None:
    if info.get("type") != "flexible_futures" or info.get("isExpired"):
        return None
    symbol = str(info.get("symbol", "")).upper()
    if not symbol.startswith("PF_"):
        return None  # uniquement les perpétuels linéaires
    if not info.get("tradeable", True):
        return None
    banned = [c.upper() for c in info.get("countriesBanned", []) or []]
    base = normalize_base(str(info.get("base") or symbol[3:-3]))
    quote = normalize_base(str(info.get("quote") or "USD"))
    if base in tax.excluded:
        return None
    constraints: list[str] = []
    tradable = country.upper() not in banned
    if not tradable:
        constraints.append(f"interdit pour le pays {country}")
    if info.get("postOnly"):
        constraints.append("post-only")
    if info.get("tradfi"):
        aclass = "commodity" if base in tax.commodities else "tradfi"
    else:
        aclass = "commodity" if base in tax.commodities else "crypto"
    lev = _max_lev_from_margin(info.get("retailMarginLevels") or info.get("marginLevels"))
    lev = min(lev, max_leverage) if lev else 0
    if lev == 0:
        constraints.append("niveaux de marge absents — levier inconnu")
    prec = info.get("contractValueTradePrecision", 4)
    try:
        lot_dec = int(prec)
    except (TypeError, ValueError):
        lot_dec = 4
    min_size = 10 ** (-lot_dec) if lot_dec >= 0 else 10 ** abs(lot_dec)
    allowed = list(range(1, lev + 1))
    return Instrument(
        symbol=symbol, display=symbol, venue="futures", asset_class=aclass, kind="perpetual", base=base,
        quote=quote, status="online" if tradable else "banned", tradable=tradable and lev > 0,
        can_long=tradable and lev > 0, can_short=tradable and lev > 0,
        max_leverage_long=lev, max_leverage_short=lev, allowed_leverages_long=allowed,
        allowed_leverages_short=allowed, ordermin=min_size, costmin=0.0,
        tick_size=float(info.get("tickSize") or 0), lot_decimals=max(lot_dec, 0),
        pair_decimals=tick_decimals(float(info.get("tickSize") or 0)), contract_size=float(info.get("contractSize") or 1), constraints=constraints,
    )


@dataclass
class InstrumentDiscovery:
    settings: Settings
    spot: KrakenSpotClient
    futures: KrakenFuturesClient | None
    taxonomy: Taxonomy
    _cache: list[Instrument] = field(default_factory=list)
    _cache_ts: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def discover(self, force: bool = False) -> list[Instrument]:
        if self._cache and not force and time.time() - self._cache_ts < self.settings.instrument_cache_hours * 3600:
            return self._cache
        self.warnings = []
        out: list[Instrument] = []
        cc = self.settings.country_code
        # Crypto spot — critique : on laisse remonter l'erreur si indisponible.
        pairs = self.spot.asset_pairs(country_code=cc)
        out += [i for k, v in pairs.items() if (i := parse_spot_pair(k, v, self.taxonomy, None))]
        # xStocks (tokenized assets)
        try:
            tok = self.spot.asset_pairs(aclass_base="tokenized_asset", country_code=cc)
            out += [i for k, v in tok.items() if (i := parse_spot_pair(k, v, self.taxonomy, "tokenized_asset"))]
        except DataUnavailable as e:
            self.warnings.append(f"xStocks indisponibles via l'API ({e})")
        # Perpétuels futures
        if self.settings.futures_enabled and self.futures:
            try:
                for info in self.futures.instruments():
                    inst = parse_futures_instrument(info, self.taxonomy, cc, self.settings.max_leverage)
                    if inst:
                        out.append(inst)
            except DataUnavailable as e:
                self.warnings.append(f"Futures indisponibles ({e})")
        classify_xstock_perps(out)
        self._apply_account_access(out)
        self._cache, self._cache_ts = out, time.time()
        log.info("instruments=%d (spot=%d, futures=%d, tradables=%d)", len(out),
                 sum(i.venue == "spot" for i in out), sum(i.venue == "futures" for i in out),
                 sum(i.tradable for i in out))
        return out

    def _apply_account_access(self, insts: list[Instrument]) -> None:
        spot_ok = fut_ok = None
        if self.settings.has_spot_keys:
            try:
                self.spot.balance()
                spot_ok = True
            except AuthMissing:
                pass
            except DataUnavailable as e:
                spot_ok = False
                self.warnings.append(f"Clé spot refusée par Kraken ({e})")
        if self.futures and self.settings.has_futures_keys:
            try:
                self.futures.accounts()
                fut_ok = True
            except DataUnavailable as e:
                fut_ok = False
                self.warnings.append(f"Compte futures inaccessible ({e})")
        for i in insts:
            ok = spot_ok if i.venue == "spot" else fut_ok
            if ok is True:
                # Le compte existe et répond. L'éligibilité xStocks n'est pas exposée par l'API :
                # elle reste "non vérifiée" jusqu'à un AddOrder validate=true réussi.
                i.account_access = "vérifié" if i.asset_class == "crypto" or i.venue == "futures" else "non vérifié"
            elif ok is False:
                i.account_access = "refusé"
            if i.venue == "futures" and ok is None:
                i.constraints.append("compte futures non vérifié (pas de clé API futures)")


def tradable_universe(insts: list[Instrument]) -> list[Instrument]:
    return [i for i in insts if i.tradable and i.account_access != "refusé" and i.asset_class != "tradfi"]
