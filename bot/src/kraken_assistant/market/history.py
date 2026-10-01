"""Historique local des bougies : il s'enrichit à chaque scan et peut être complété en masse.

Sources (toutes réelles) :
  1. API spot OHLC : 720 bougies par intervalle → 5m ≈ 2,5 j · 1h ≈ 30 j · 1j ≈ 2 ans · 1 sem ≈ tout l'historique.
  2. Accumulation : chaque scan ajoute les nouvelles bougies 5m/1h → l'historique fin s'allonge chaque jour.
  3. API futures charts : pagination from/to → historique profond des perpétuels.
  4. Archives CSV OHLCVT officielles de Kraken (support.kraken.com) : tout l'historique spot, tous intervalles.
Rien n'est interpolé : un trou reste un trou.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import pandas as pd

from ..api.errors import DataUnavailable
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from ..database.db import Database
from .candles import drop_unclosed, futures_rows_to_df, spot_rows_to_df
from .models import Instrument

log = logging.getLogger(__name__)

TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
CSV_INTERVALS = {5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    key TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (key, tf, ts)
) WITHOUT ROWID;
"""


class CandleStore:
    def __init__(self, db: Database):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def upsert(self, key: str, tf: str, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        rows = [(key, tf, int(ts.timestamp()), float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                for ts, r in zip(df.index, df[["open", "high", "low", "close", "volume"]].to_numpy())]
        with self.db._lock:
            self.db.conn.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
            self.db.conn.commit()
        return len(rows)

    def load(self, key: str, tf: str, limit: int | None = None, since: int | None = None) -> pd.DataFrame:
        q = "SELECT ts, open, high, low, close, volume FROM candles WHERE key=? AND tf=?"
        params: list = [key, tf]
        if since is not None:
            q += " AND ts >= ?"
            params.append(since)
        q += " ORDER BY ts DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self.db._lock:
            rows = self.db.conn.execute(q, params).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                                index=pd.DatetimeIndex([], tz="UTC"))
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("ts"), unit="s", utc=True)
        return df.sort_index()

    def coverage(self, key: str | None = None) -> list[dict]:
        q = ("SELECT key, tf, COUNT(*) n, MIN(ts) first, MAX(ts) last FROM candles "
             + ("WHERE key=? " if key else "") + "GROUP BY key, tf ORDER BY key, tf")
        return self.db.query(q, (key,) if key else ())

    def last_ts(self, key: str, tf: str) -> int | None:
        r = self.db.one("SELECT MAX(ts) AS t FROM candles WHERE key=? AND tf=?", (key, tf))
        return r["t"] if r and r["t"] is not None else None


def merge(stored: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    if stored is None or stored.empty:
        return live
    both = pd.concat([stored, live])
    return both[~both.index.duplicated(keep="last")].sort_index()


class HistoryService:
    def __init__(self, store: CandleStore, spot: KrakenSpotClient, futures: KrakenFuturesClient | None):
        self.store, self.spot, self.futures = store, spot, futures

    # -------------------------------------------------------------- récent
    def fetch_htf(self, inst: Instrument, max_age_h: float = 20) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        """Journalier + hebdomadaire. Rafraîchis au plus une fois par ~20 h (2 appels/jour/instrument)."""
        out = []
        for tf in ("1d", "1w"):
            last = self.store.last_ts(inst.key, tf)
            fresh = last is not None and time.time() - last < max_age_h * 3600 + TF_MIN[tf] * 60
            if not fresh:
                try:
                    if inst.venue == "spot":
                        df = spot_rows_to_df(self.spot.ohlc(inst.symbol, TF_MIN[tf], inst.api_asset_class))
                    elif self.futures:
                        df = futures_rows_to_df(self.futures.candles(inst.symbol, TF_MIN[tf], 720))
                    else:
                        df = None
                    if df is not None:
                        self.store.upsert(inst.key, tf, drop_unclosed(df, TF_MIN[tf]))
                except DataUnavailable as e:
                    log.warning("historique %s %s indisponible : %s", inst.display, tf, e)
            df = self.store.load(inst.key, tf)
            out.append(df if len(df) else None)
        return out[0], out[1]

    # -------------------------------------------------------------- profond
    def backfill_futures(self, inst: Instrument, tf: str = "15m", max_days: int = 730) -> int:
        """Remonte l'historique d'un perpétuel par pages successives (API charts from/to)."""
        if inst.venue != "futures" or not self.futures:
            return 0
        from ..api.kraken_futures import RESOLUTIONS
        res = RESOLUTIONS[TF_MIN[tf]]
        step = TF_MIN[tf] * 60 * 2000
        end = int(time.time())
        stop = end - max_days * 86400
        total = 0
        while end > stop:
            frm = max(stop, end - step)
            payload = self.futures.http.request("GET", f"/api/charts/v1/trade/{inst.symbol}/{res}",
                                                params={"from": frm, "to": end})
            candles = (payload or {}).get("candles") or []
            if not candles:
                break
            df = drop_unclosed(futures_rows_to_df(candles), TF_MIN[tf])
            total += self.store.upsert(inst.key, tf, df)
            first = int(df.index[0].timestamp()) if len(df) else frm
            if first >= end:
                break
            end = first - 1
        log.info("backfill %s %s : %d bougies", inst.display, tf, total)
        return total

    def import_kraken_csv(self, path: str | Path, insts: list[Instrument]) -> dict[str, int]:
        """Importe les fichiers OHLCVT officiels Kraken (<ALTNAME>_<minutes>.csv, sans en-tête).
        Accepte un fichier ou un dossier. Seuls les instruments découverts et les intervalles utiles sont importés."""
        p = Path(path).expanduser()
        files = [p] if p.is_file() else sorted(p.rglob("*.csv"))
        by_alt: dict[str, Instrument] = {}
        for i in insts:
            if i.venue != "spot":
                continue
            for name in {i.symbol, i.display.replace("/", ""), getattr(i, "altname", "") or ""}:
                if name:
                    by_alt[name.upper()] = i
            if i.base == "BTC":  # les fichiers Kraken utilisent XBT
                by_alt[i.display.replace("/", "").upper().replace("BTC", "XBT", 1)] = i
        report: dict[str, int] = {}
        for f in files:
            m = re.match(r"^(.+)_(\d+)\.csv$", f.name, re.IGNORECASE)
            if not m:
                continue
            alt, minutes = m.group(1).upper(), int(m.group(2))
            inst, tf = by_alt.get(alt), CSV_INTERVALS.get(minutes)
            if not inst or not tf:
                continue
            n = 0
            for chunk in pd.read_csv(f, header=None, names=["time", "open", "high", "low", "close", "volume", "trades"],
                                     chunksize=200_000):
                chunk.index = pd.to_datetime(chunk.pop("time").astype("int64"), unit="s", utc=True)
                n += self.store.upsert(inst.key, tf, chunk[["open", "high", "low", "close", "volume"]].astype(float))
            report[f"{inst.display} {tf}"] = n
            log.info("import CSV %s → %s %s : %d bougies", f.name, inst.display, tf, n)
        return report

    # -------------------------------------------------------------- lecture
    def history_15m(self, inst: Instrument, limit: int | None = None) -> pd.DataFrame:
        """Meilleur historique 15m disponible : 15m stocké, complété par le 5m agrégé (accumulé par les scans)."""
        from .candles import resample
        d15 = self.store.load(inst.key, "15m", limit)
        d5 = self.store.load(inst.key, "5m")
        if len(d5) >= 3:
            agg = resample(d5, 5, 15)
            d15 = merge(d15, agg[agg.index > d15.index[-1]] if len(d15) else agg)
        return d15.iloc[-limit:] if limit else d15
