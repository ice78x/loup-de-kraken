"""Faux serveur Kraken pour les tests de bout en bout.

⚠ DONNÉES SYNTHÉTIQUES : prix générés aléatoirement, uniquement pour vérifier que le pipeline fonctionne.
Aucune de ces valeurs ne représente le marché réel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import httpx


def gen_series(seed: int, start: float, n5: int = 8640, vol: float = 0.0025, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    idx = pd.date_range(end=end, periods=n5, freq="5min", tz="UTC")
    rets = rng.normal(drift, vol, n5)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]])
    wig = np.abs(rng.normal(0, vol * 0.6, n5)) * close
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wig, "low": np.minimum(open_, close) - wig,
                         "close": close, "volume": rng.uniform(20, 200, n5)}, index=idx)


def to_rows(df: pd.DataFrame, minutes: int) -> list:
    if minutes != 5:
        df = df.resample(f"{minutes}min", label="left", closed="left", origin="epoch").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    df = df.iloc[-720:]
    return [[int(ts.timestamp()), f"{r.open:.6f}", f"{r.high:.6f}", f"{r.low:.6f}", f"{r.close:.6f}",
             f"{r.close:.6f}", f"{r.volume:.4f}", 10] for ts, r in df.iterrows()]


class FakeKraken:
    def __init__(self, seed: int = 0):
        self.pairs = {
            "XXBTZEUR": {"altname": "XBTEUR", "wsname": "XBT/EUR", "base": "XXBT", "quote": "ZEUR", "status": "online",
                         "leverage_buy": [2, 3, 4, 5], "leverage_sell": [2, 3, 4, 5], "ordermin": "0.00005",
                         "costmin": "0.5", "tick_size": "0.1", "lot_decimals": 8, "pair_decimals": 1},
            "XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD", "base": "XXBT", "quote": "ZUSD", "status": "online",
                         "leverage_buy": [], "leverage_sell": [], "ordermin": "0.00005", "lot_decimals": 8},
            "XETHZEUR": {"altname": "ETHEUR", "wsname": "ETH/EUR", "base": "XETH", "quote": "ZEUR", "status": "online",
                         "leverage_buy": [2, 3], "leverage_sell": [2, 3], "ordermin": "0.001", "lot_decimals": 8},
            "LINKEUR": {"altname": "LINKEUR", "wsname": "LINK/EUR", "base": "LINK", "quote": "ZEUR", "status": "online",
                        "leverage_buy": [2, 3], "leverage_sell": [2, 3], "ordermin": "0.2", "lot_decimals": 8},
            "ZEURZUSD": {"altname": "EURUSD", "wsname": "EUR/USD", "base": "ZEUR", "quote": "ZUSD", "status": "online",
                         "leverage_buy": [], "leverage_sell": [], "ordermin": "10", "lot_decimals": 8},
            "PAXGEUR": {"altname": "PAXGEUR", "wsname": "PAXG/EUR", "base": "PAXG", "quote": "ZEUR", "status": "online",
                        "leverage_buy": [], "leverage_sell": [], "ordermin": "0.001", "lot_decimals": 8},
        }
        self.tokenized = {"TSLAxUSD": {"altname": "TSLAxUSD", "wsname": "TSLAx/USD", "base": "TSLAx", "quote": "ZUSD",
                                       "status": "online", "leverage_buy": [], "leverage_sell": [], "ordermin": "0.01",
                                       "lot_decimals": 4}}
        starts = {"ZEURZUSD": 1.17, "XXBTZEUR": 50000, "XXBTZUSD": 55000, "XETHZEUR": 2500, "LINKEUR": 14, "PAXGEUR": 2000, "TSLAxUSD": 250}
        self.series = {k: gen_series(seed + i, v) for i, (k, v) in enumerate(starts.items())}
        self.fut = gen_series(seed + 99, 150)
        self.calls: list[str] = []

    def ticker(self, keys):
        out = {}
        for k in keys:
            df = self.series[k]
            last = float(df["close"].iloc[-1])
            day = df.iloc[-288:]
            out[k] = {"a": [f"{last * 1.0002:.6f}", "1", "1"], "b": [f"{last * 0.9998:.6f}", "1", "1"],
                      "c": [f"{last:.6f}", "0.1"], "v": ["100", f"{day['volume'].sum() * 50:.2f}"],
                      "p": [f"{last:.6f}", f"{day['close'].mean():.6f}"], "t": [10, 1000],
                      "l": [f"{day['low'].min():.6f}"] * 2, "h": [f"{day['high'].max():.6f}"] * 2,
                      "o": f"{day['open'].iloc[0]:.6f}"}
        return out

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, q = request.url.path, dict(request.url.params)
        self.calls.append(path)
        if path == "/0/public/AssetPairs":
            res = self.tokenized if q.get("aclass_base") == "tokenized_asset" else self.pairs
        elif path == "/0/public/Ticker":
            keys = list(self.tokenized) if q.get("asset_class") == "tokenized_asset" else list(self.pairs)
            res = self.ticker(keys)
        elif path == "/0/public/OHLC":
            res = {q["pair"]: to_rows(self.series[q["pair"]], int(q["interval"])), "last": 0}
        elif path == "/0/public/Depth":
            last = float(self.series[q["pair"]]["close"].iloc[-1])
            res = {q["pair"]: {"bids": [[f"{last * (1 - i / 1000):.6f}", "50", 0] for i in range(1, 50)],
                               "asks": [[f"{last * (1 + i / 1000):.6f}", "50", 0] for i in range(1, 50)]}}
        elif path == "/0/public/SystemStatus":
            res = {"status": "online"}
        elif path == "/derivatives/api/v3/instruments":
            return httpx.Response(200, json={"result": "success", "instruments": [
                {"symbol": "PF_SOLUSD", "type": "flexible_futures", "base": "SOL", "quote": "USD", "tradeable": True,
                 "tickSize": 0.01, "contractSize": 1, "contractValueTradePrecision": 2, "countriesBanned": [],
                 "retailMarginLevels": [{"contracts": 0, "initialMargin": 0.1, "maintenanceMargin": 0.05}]}]})
        elif path == "/derivatives/api/v3/tickers":
            df = self.fut
            last = float(df["close"].iloc[-1])
            return httpx.Response(200, json={"result": "success", "tickers": [
                {"symbol": "PF_SOLUSD", "last": last, "bid": last * 0.9998, "ask": last * 1.0002,
                 "vol24h": float(df["volume"].iloc[-288:].sum() * 50), "volumeQuote": float(df["volume"].iloc[-288:].sum() * 50 * last),
                 "openInterest": 1000.0, "fundingRate": 0.0001, "change24h": 1.0, "suspended": False}]})
        elif path.startswith("/api/charts/v1/trade/"):
            res_map = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
            mins = res_map[path.rsplit("/", 1)[1]]
            rows = to_rows(self.fut, mins)
            return httpx.Response(200, json={"candles": [
                {"time": r[0] * 1000, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[6]} for r in rows],
                "more_candles": False})
        elif path == "/derivatives/api/v3/orderbook":
            last = float(self.fut["close"].iloc[-1])
            return httpx.Response(200, json={"result": "success", "orderBook": {
                "bids": [[last * (1 - i / 1000), 500] for i in range(1, 50)],
                "asks": [[last * (1 + i / 1000), 500] for i in range(1, 50)]}})
        else:
            return httpx.Response(404)
        return httpx.Response(200, json={"error": [], "result": res})


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("réseau coupé (test)")
