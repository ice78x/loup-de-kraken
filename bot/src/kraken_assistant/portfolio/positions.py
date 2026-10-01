"""Positions ouvertes : paper (base locale) + Kraken (marge spot, futures, soldes spot).

Les positions Kraken ne contiennent pas de SL/TP (ce sont des ordres séparés). L'utilisateur peut les
renseigner avec la commande `POSITION SET`. Tant que le SL est inconnu, le risque est compté de manière
prudente (hypothèse : risque normal), et c'est affiché comme une hypothèse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..api.errors import AuthMissing, DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from ..database.db import Database, utcnow
from ..market.models import Instrument, normalize_base

log = logging.getLogger(__name__)


@dataclass
class Position:
    id: int
    source: str
    instrument_key: str
    display: str
    base: str
    venue: str
    asset_class: str
    direction: str
    entry: float
    qty_initial: float
    qty_remaining: float
    sl: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    tp1_hit: bool
    tp2_hit: bool
    tp3_hit: bool
    status: str
    eur_per_quote: float | None
    fee_rate_pct: float
    realized_pnl_eur: float
    strategy: str | None = None
    catalyst: str | None = None
    signal_id: int | None = None
    leverage: int | None = None
    invalidation: float | None = None
    opened_at: str | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    risk_eur_initial: float | None = None
    sl_initial: float | None = None

    @classmethod
    def from_row(cls, r: dict) -> "Position":
        return cls(
            id=r["id"], source=r["source"], instrument_key=r["instrument_key"], display=r["display"] or "",
            base=r["base"] or "", venue=r["venue"] or "", asset_class=r["asset_class"] or "",
            direction=r["direction"], entry=r["entry"] or 0.0, qty_initial=r["qty_initial"] or 0.0,
            qty_remaining=r["qty_remaining"] or 0.0, sl=r["sl"], tp1=r["tp1"], tp2=r["tp2"], tp3=r["tp3"],
            tp1_hit=bool(r["tp1_hit"]), tp2_hit=bool(r["tp2_hit"]), tp3_hit=bool(r["tp3_hit"]),
            status=r["status"], eur_per_quote=r["eur_per_quote"], fee_rate_pct=r["fee_rate_pct"] or 0.0,
            realized_pnl_eur=r["realized_pnl_eur"] or 0.0, strategy=r["strategy"], catalyst=r["catalyst"],
            signal_id=r["signal_id"], leverage=r["leverage"], invalidation=r["invalidation"],
            opened_at=r["opened_at"], entry_low=r["entry_low"], entry_high=r["entry_high"],
            risk_eur_initial=r["risk_eur_initial"], sl_initial=r["sl_initial"],
        )

    @property
    def sign(self) -> int:
        return 1 if self.direction == "LONG" else -1

    def unrealized_quote(self, price: float) -> float:
        return self.sign * (price - self.entry) * self.qty_remaining

    def remaining_risk_quote(self) -> float | None:
        """Perte supplémentaire si le SL actuel est touché (0 si le SL verrouille un gain). None si SL inconnu."""
        if self.sl is None or self.qty_remaining <= 0:
            return None if self.sl is None else 0.0
        loss = self.sign * (self.entry - self.sl) * self.qty_remaining
        fees = self.fee_rate_pct / 100 * self.qty_remaining * self.sl
        return max(0.0, loss) + fees


class PositionStore:
    def __init__(self, db: Database):
        self.db = db

    def open_positions(self, include_pending: bool = False) -> list[Position]:
        st = ("open", "pending") if include_pending else ("open",)
        rows = self.db.query(f"SELECT * FROM positions WHERE status IN ({','.join('?' * len(st))}) ORDER BY id", st)
        return [Position.from_row(r) for r in rows]

    def get(self, pid: int) -> Position | None:
        r = self.db.one("SELECT * FROM positions WHERE id=?", (pid,))
        return Position.from_row(r) if r else None

    def holdings(self) -> list[Position]:
        """Avoirs spot sans SL : affichés, mais hors budget de risque tant qu'aucun SL n'est défini."""
        return [Position.from_row(r) for r in self.db.query("SELECT * FROM positions WHERE status='holding' ORDER BY id")]

    def set_levels(self, pid: int, **levels: float | None) -> None:
        data = {k: v for k, v in levels.items()
                if k in ("sl", "tp1", "tp2", "tp3", "invalidation", "entry") and v is not None}
        if data:
            self.db.update("positions", pid, data)
        r = self.db.one("SELECT status, sl, entry FROM positions WHERE id=?", (pid,))
        if r and r["status"] == "holding" and r["sl"] is not None and r["entry"]:
            self.db.update("positions", pid, {"status": "open"})  # l'avoir devient une position gérée


class KrakenPositionSync:
    """Importe les positions réelles du compte (lecture seule)."""

    def __init__(self, db: Database, spot: KrakenSpotClient, futures: KrakenFuturesClient | None,
                 default_fee_spot: float, default_fee_fut: float):
        self.db, self.spot, self.futures = db, spot, futures
        self.fee_spot, self.fee_fut = default_fee_spot, default_fee_fut
        self.warnings: list[str] = []

    def _upsert(self, source: str, ext_id: str, data: dict) -> None:
        row = self.db.one("SELECT id FROM positions WHERE source=? AND external_id=?", (source, ext_id))
        if row:
            # On conserve SL/TP/entrée saisis localement ; on met à jour taille (et prix si Kraken le fournit).
            keep = {k: v for k, v in data.items() if k in ("qty_remaining", "last_checked")
                    or (k == "entry" and v is not None)}
            self.db.update("positions", row["id"], keep)
        else:
            self.db.insert("positions", {"source": source, "external_id": ext_id, "created_at": utcnow(), **data})

    def sync(self, insts: list[Instrument], tickers: dict) -> None:
        self.warnings = []
        seen: dict[str, set[str]] = {"kraken_margin": set(), "kraken_futures": set(), "kraken_spot": set()}
        by_symbol = {i.symbol: i for i in insts}
        now = utcnow()
        try:
            for txid, p in self.spot.open_positions().items():
                inst = by_symbol.get(p.get("pair", ""))
                vol = float(p.get("vol", 0)) - float(p.get("vol_closed", 0))
                entry = float(p["cost"]) / float(p["vol"]) if float(p.get("vol", 0)) else 0.0
                self._upsert("kraken_margin", txid, {
                    "instrument_key": inst.key if inst else f"spot:{p.get('pair')}",
                    "display": inst.display if inst else p.get("pair"), "base": inst.base if inst else "",
                    "venue": "spot", "asset_class": inst.asset_class if inst else "",
                    "direction": "LONG" if p.get("type") == "buy" else "SHORT", "entry": entry,
                    "qty_initial": float(p.get("vol", 0)), "qty_remaining": vol, "status": "open",
                    "opened_at": str(p.get("time")), "fee_rate_pct": self.fee_spot, "last_checked": now})
                seen["kraken_margin"].add(txid)
        except AuthMissing:
            return
        except DataUnavailable as e:
            self.warnings.append(f"positions marge Kraken indisponibles ({e})")
            seen.pop("kraken_margin")
        if self.futures:
            try:
                fut = {i.symbol: i for i in insts if i.venue == "futures"}
                for p in self.futures.open_positions():
                    sym = str(p.get("symbol", "")).upper()
                    inst = fut.get(sym)
                    self._upsert("kraken_futures", sym, {
                        "instrument_key": f"futures:{sym}", "display": sym, "base": inst.base if inst else "",
                        "venue": "futures", "asset_class": inst.asset_class if inst else "crypto",
                        "direction": "LONG" if p.get("side") == "long" else "SHORT",
                        "entry": float(p.get("price", 0)), "qty_initial": float(p.get("size", 0)),
                        "qty_remaining": float(p.get("size", 0)), "status": "open",
                        "fee_rate_pct": self.fee_fut, "last_checked": now})
                    seen["kraken_futures"].add(sym)
            except AuthMissing:
                seen.pop("kraken_futures")
            except DataUnavailable as e:
                self.warnings.append(f"positions futures indisponibles ({e})")
                seen.pop("kraken_futures")
        # Soldes spot détenus (positions LONG sans levier)
        try:
            bal = self.spot.balance()
            eur_pairs = {i.base: i for i in insts if i.venue == "spot" and i.quote == "EUR"}
            usd_pairs = {i.base: i for i in insts if i.venue == "spot" and i.quote == "USD"}
            for asset, amount in bal.items():
                base = normalize_base(asset)
                amt = float(amount)
                inst = eur_pairs.get(base) or usd_pairs.get(base)
                if not inst or amt <= 0:
                    continue
                t = tickers.get(inst.key)
                if t and amt * t.last < 1.0:  # poussière
                    continue
                self._upsert("kraken_spot", base, {
                    "instrument_key": inst.key, "display": inst.display, "base": inst.base, "venue": "spot",
                    "asset_class": inst.asset_class, "direction": "LONG", "entry": None, "qty_initial": amt,
                    "qty_remaining": amt, "status": "holding", "fee_rate_pct": self.fee_spot, "last_checked": now,
                    "notes": "solde spot — prix d'entrée inconnu (non fourni par Balance)"})
                seen["kraken_spot"].add(base)
        except DataUnavailable as e:
            self.warnings.append(f"soldes spot indisponibles ({e})")
            seen.pop("kraken_spot")
        # Ferme localement les positions qui n'existent plus côté Kraken
        for source, ids in seen.items():
            for r in self.db.query("SELECT id, external_id FROM positions WHERE source=? AND status IN ('open','holding')",
                                   (source,)):
                if r["external_id"] not in ids:
                    self.db.update("positions", r["id"], {"status": "closed", "closed_at": now,
                                                          "notes": "fermée côté Kraken"})
