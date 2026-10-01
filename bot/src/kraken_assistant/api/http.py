"""Client HTTP commun : timeout, retries sur erreurs transitoires, limitation de débit."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from .errors import DataUnavailable

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval_s - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class HttpClient:
    def __init__(self, base_url: str, timeout_s: float, user_agent: str, min_interval_s: float = 0.0,
                 retries: int = 2, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.limiter = RateLimiter(min_interval_s)
        self.client = httpx.Client(timeout=timeout_s, headers={"User-Agent": user_agent}, transport=transport)

    def request(self, method: str, path: str, *, params: dict | None = None, content: str | bytes | None = None,
                headers: dict | None = None, retry: bool = True) -> Any:
        url = self.base_url + path
        attempts = (self.retries + 1) if retry else 1
        last_exc: Exception | None = None
        for i in range(attempts):
            self.limiter.wait()
            try:
                r = self.client.request(method, url, params=params, content=content, headers=headers)
                if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
                    log.warning("HTTP %s sur %s — nouvelle tentative", r.status_code, path)
                    time.sleep(1.5 * (i + 1))
                    continue
                if r.status_code >= 400:
                    raise DataUnavailable(f"HTTP {r.status_code} sur {path}")
                return r.json()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                log.warning("Réseau indisponible pour %s (%s) — tentative %d/%d", path, type(e).__name__,
                            i + 1, attempts)
                if i < attempts - 1:
                    time.sleep(1.5 * (i + 1))
            except ValueError as e:  # JSON invalide
                raise DataUnavailable(f"Réponse non JSON sur {path}") from e
        raise DataUnavailable(f"API injoignable ({path}): {type(last_exc).__name__ if last_exc else 'erreur'}")

    def close(self) -> None:
        self.client.close()
