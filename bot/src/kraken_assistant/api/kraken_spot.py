"""Client Kraken Spot REST (https://docs.kraken.com/api/docs/rest-api).

Public  : GET  /0/public/{Method}
Privé   : POST /0/private/{Method}, form-encoded, headers API-Key / API-Sign.
API-Sign = base64( HMAC-SHA512( base64decode(secret), uri_path + SHA256(nonce + postdata) ) )
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
import urllib.parse
from typing import Any

from ..config import Settings
from .errors import AuthMissing, KrakenAPIError
from .http import HttpClient


def sign_spot(uri_path: str, postdata: str, nonce: str, secret_b64: str) -> str:
    sha = hashlib.sha256((nonce + postdata).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), uri_path.encode() + sha, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


class _Nonce:
    def __init__(self) -> None:
        self._last = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            n = max(int(time.time() * 1000), self._last + 1)
            self._last = n
            return str(n)


class KrakenSpotClient:
    def __init__(self, settings: Settings, transport=None):
        self.s = settings
        self.http = HttpClient(settings.spot_base_url, settings.http_timeout_s, settings.user_agent,
                               settings.public_min_interval_s, transport=transport)
        self._nonce = _Nonce()

    # ------------------------------------------------------------------ core
    @staticmethod
    def _unwrap(endpoint: str, payload: Any) -> Any:
        if not isinstance(payload, dict):
            raise KrakenAPIError(endpoint, "réponse inattendue")
        errs = payload.get("error") or []
        # Les "W..." sont des avertissements ; seules les "E..." sont bloquantes.
        blocking = [e for e in errs if not str(e).startswith("W")]
        if blocking:
            raise KrakenAPIError(endpoint, blocking)
        if "result" not in payload:
            raise KrakenAPIError(endpoint, "champ result absent")
        return payload["result"]

    def public(self, method: str, params: dict | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        return self._unwrap(method, self.http.request("GET", f"/0/public/{method}", params=clean))

    def private(self, method: str, data: dict | None = None, *, retry: bool = True) -> Any:
        if not self.s.has_spot_keys:
            raise AuthMissing(f"Clés API spot absentes ({method})")
        path = f"/0/private/{method}"
        nonce = self._nonce.next()
        body = {"nonce": nonce, **{k: v for k, v in (data or {}).items() if v is not None}}
        postdata = urllib.parse.urlencode(body)
        headers = {
            "API-Key": self.s.kraken_api_key.get_secret_value(),
            "API-Sign": sign_spot(path, postdata, nonce, self.s.kraken_api_secret.get_secret_value()),
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        return self._unwrap(method, self.http.request("POST", path, content=postdata, headers=headers,
                                                      retry=retry))

    # ---------------------------------------------------------------- public
    def server_time(self) -> dict:
        return self.public("Time")

    def system_status(self) -> dict:
        return self.public("SystemStatus")

    def asset_pairs(self, aclass_base: str | None = None, country_code: str | None = None) -> dict[str, dict]:
        return self.public("AssetPairs", {"aclass_base": aclass_base, "country_code": country_code})

    def ticker(self, pair: str | None = None, asset_class: str | None = None) -> dict[str, dict]:
        return self.public("Ticker", {"pair": pair, "asset_class": asset_class})

    def ohlc(self, pair: str, interval: int, asset_class: str | None = None, since: int | None = None) -> list:
        res = self.public("OHLC", {"pair": pair, "interval": interval, "asset_class": asset_class,
                                   "since": since})
        rows = [v for k, v in res.items() if k != "last"]
        if not rows:
            raise KrakenAPIError("OHLC", f"aucune bougie pour {pair}")
        return rows[0]

    def depth(self, pair: str, count: int = 50, asset_class: str | None = None) -> dict:
        res = self.public("Depth", {"pair": pair, "count": count, "asset_class": asset_class})
        return next(iter(res.values()))

    # --------------------------------------------------------------- private
    def balance(self) -> dict[str, str]:
        return self.private("Balance")

    def trade_balance(self, asset: str = "ZEUR") -> dict:
        return self.private("TradeBalance", {"asset": asset})

    def open_positions(self) -> dict[str, dict]:
        return self.private("OpenPositions", {"docalcs": "true"})

    def open_orders(self) -> dict:
        return self.private("OpenOrders")

    def trade_volume(self, pairs: list[str]) -> dict:
        """Frais réels du compte pour les paires données (champ fees / fees_maker)."""
        return self.private("TradeVolume", {"pair": ",".join(pairs)})

    def add_order(self, params: dict, *, validate: bool) -> dict:
        """Ordre spot. `validate=True` = vérification sans passage au carnet.
        Ne jamais appeler directement : passer par execution.live.LiveBroker."""
        data = dict(params)
        if validate:
            data["validate"] = "true"
        return self.private("AddOrder", data, retry=False)
