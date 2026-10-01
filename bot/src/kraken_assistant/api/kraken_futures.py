"""Client Kraken Futures REST (https://docs.kraken.com/api/docs/futures-api).

Public : /derivatives/api/v3/instruments, /derivatives/api/v3/tickers
Bougies: /api/charts/v1/{tick_type}/{symbol}/{resolution}?from=&to= (secondes)
Privé  : headers APIKey / Nonce / Authent
Authent = base64( HMAC-SHA512( base64decode(secret), SHA256(postData + nonce + endpointPath) ) )
endpointPath = "/api/v3/..." (sans le préfixe /derivatives).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Any

from ..config import Settings
from .errors import AuthMissing, KrakenAPIError
from .http import HttpClient

RESOLUTIONS = {5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d", 10080: "1w"}


def sign_futures(endpoint_path: str, postdata: str, nonce: str, secret_b64: str) -> str:
    sha = hashlib.sha256((postdata + nonce + endpoint_path).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), sha, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


class KrakenFuturesClient:
    def __init__(self, settings: Settings, transport=None):
        self.s = settings
        self.http = HttpClient(settings.futures_base_url, settings.http_timeout_s, settings.user_agent,
                               0.25, transport=transport)
        self._last_nonce = 0

    @staticmethod
    def _check(endpoint: str, payload: Any) -> Any:
        if not isinstance(payload, dict):
            raise KrakenAPIError(endpoint, "réponse inattendue")
        if payload.get("result") == "error" or payload.get("error"):
            raise KrakenAPIError(endpoint, str(payload.get("error") or payload.get("errors")))
        return payload

    # ---------------------------------------------------------------- public
    def instruments(self) -> list[dict]:
        return self._check("instruments", self.http.request("GET", "/derivatives/api/v3/instruments")).get(
            "instruments", [])

    def tickers(self) -> list[dict]:
        return self._check("tickers", self.http.request("GET", "/derivatives/api/v3/tickers")).get("tickers", [])

    def candles(self, symbol: str, interval_min: int, lookback_bars: int = 720, tick_type: str = "trade") -> list[dict]:
        res = RESOLUTIONS.get(interval_min)
        if res is None:
            raise KrakenAPIError("charts", f"résolution {interval_min} min non supportée")
        to = int(time.time())
        frm = to - interval_min * 60 * lookback_bars
        payload = self.http.request("GET", f"/api/charts/v1/{tick_type}/{symbol}/{res}",
                                    params={"from": frm, "to": to})
        candles = (payload or {}).get("candles")
        if not candles:
            raise KrakenAPIError("charts", f"aucune bougie pour {symbol}")
        return candles

    # --------------------------------------------------------------- private
    def private(self, method: str, path: str, data: dict | None = None, *, retry: bool = True) -> Any:
        if not self.s.has_futures_keys:
            raise AuthMissing(f"Clés API futures absentes ({path})")
        nonce = str(max(int(time.time() * 1000), self._last_nonce + 1))
        self._last_nonce = int(nonce)
        postdata = urllib.parse.urlencode({k: v for k, v in (data or {}).items() if v is not None})
        endpoint_path = path.replace("/derivatives", "", 1)
        headers = {
            "APIKey": self.s.kraken_futures_api_key.get_secret_value(),
            "Nonce": nonce,
            "Authent": sign_futures(endpoint_path, postdata, nonce,
                                    self.s.kraken_futures_api_secret.get_secret_value()),
        }
        if method == "GET":
            payload = self.http.request("GET", path, params=data, headers=headers, retry=retry)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            payload = self.http.request("POST", path, content=postdata, headers=headers, retry=retry)
        return self._check(path, payload)

    def accounts(self) -> dict:
        return self.private("GET", "/derivatives/api/v3/accounts")

    def open_positions(self) -> list[dict]:
        return self.private("GET", "/derivatives/api/v3/openpositions").get("openPositions", [])

    def send_order(self, params: dict) -> dict:
        """Ordre futures réel. Ne jamais appeler directement : passer par execution.live.LiveBroker."""
        return self.private("POST", "/derivatives/api/v3/sendorder", params, retry=False)
