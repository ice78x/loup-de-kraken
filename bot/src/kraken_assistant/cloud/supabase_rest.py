"""Client minimal Supabase (API REST PostgREST) pour le bot.

Le bot utilise la clé secrète Supabase (secret GitHub, jamais dans le site) : elle contourne la sécurité RLS,
donc elle ne doit JAMAIS être mise dans le code du site ni partagée.
Deux formats acceptés : la nouvelle « Secret key » (sb_secret_…) ou l'ancienne « service_role » (JWT eyJ…).
Les nouvelles clés ne sont pas des JWT : Supabase les refuse dans « Authorization: Bearer » (Invalid JWT),
on ne les envoie donc que dans l'en-tête « apikey ».
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SupabaseError(Exception):
    def __init__(self, msg: str, status: int | None = None, body: str = ""):
        super().__init__(msg)
        self.status, self.body = status, body

    def hint(self) -> str:
        """Explication en français pour un débutant (affichée dans le journal GitHub)."""
        b = self.body.lower()
        if self.status in (401, 403) or "invalid api key" in b or "jwt" in b:
            return ("Clé refusée par Supabase. Vérifie le secret GitHub SUPABASE_SERVICE_KEY : il faut la clé SECRÈTE "
                    "(sb_secret_… ou service_role), copiée en entier, sans espace.")
        if self.status == 404 or "pgrst205" in b or "does not exist" in b or "could not find the table" in b:
            return ("Table introuvable : le fichier supabase/schema.sql n'a pas été exécuté (ou pas en entier) "
                    "dans le SQL Editor de Supabase. Recolle-le en entier puis clique sur Run.")
        if "column" in b:
            return ("Colonne manquante : ta base n'est pas à jour. Recolle supabase/schema.sql dans le SQL Editor "
                    "de Supabase puis clique sur Run (rien n'est effacé).")
        if self.status is None:
            return "Supabase injoignable : vérifie le secret GitHub SUPABASE_URL (https://xxxx.supabase.co, rien après)."
        return "Erreur Supabase inattendue : envoie ces lignes à Claude."


def _clean(x: Any) -> Any:
    """JSON strict : NaN/infini → null (Supabase refuse « NaN »), types numpy → nombres Python."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if hasattr(x, "item") and not isinstance(x, (int, float)):  # numpy scalaire
        try:
            x = x.item()
        except (TypeError, ValueError):
            return str(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, (int, float)):
        return x
    return str(x)


def dumps(x: Any) -> str:
    return json.dumps(_clean(x), allow_nan=False, default=str)


class Supabase:
    def __init__(self, url: str, service_key: str, transport: httpx.BaseTransport | None = None):
        url, service_key = (url or "").strip(), (service_key or "").strip()
        if not url or not service_key:
            raise SupabaseError("SUPABASE_URL / SUPABASE_SERVICE_KEY manquants")
        if service_key.startswith("sb_publishable_"):
            raise SupabaseError("SUPABASE_SERVICE_KEY : c'est la clé publique (sb_publishable_). "
                                "Il faut la clé SECRÈTE (sb_secret_… ou service_role).")
        self.base = url.rstrip("/") + "/rest/v1"
        headers = {"apikey": service_key, "Content-Type": "application/json"}
        if service_key.startswith("eyJ"):  # ancienne clé service_role (JWT)
            headers["Authorization"] = f"Bearer {service_key}"
        self.client = httpx.Client(timeout=30, transport=transport, headers=headers)

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise SupabaseError(f"Supabase {r.status_code} ({r.request.method} {r.request.url.path}): {r.text[:300]}",
                                r.status_code, r.text)
        if not r.content:
            return None
        return r.json()

    def _send(self, method: str, url: str, **kw) -> Any:
        try:
            r = self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise SupabaseError(f"Supabase injoignable ({type(e).__name__}: {e})") from e
        return self._check(r)

    def select(self, table: str, params: dict | None = None) -> list[dict]:
        return self._send("GET", f"{self.base}/{table}", params={"select": "*", **(params or {})}) or []

    def insert(self, table: str, rows: list[dict] | dict, returning: bool = True) -> list[dict]:
        headers = {"Prefer": "return=representation" if returning else "return=minimal"}
        return self._send("POST", f"{self.base}/{table}", content=dumps(rows), headers=headers) or []

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if not rows:
            return
        headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
        for i in range(0, len(rows), 500):
            self._send("POST", f"{self.base}/{table}", params={"on_conflict": on_conflict},
                       content=dumps(rows[i:i + 500]), headers=headers)

    def update(self, table: str, filters: dict, data: dict) -> None:
        self._send("PATCH", f"{self.base}/{table}", params=filters, content=dumps(data),
                   headers={"Prefer": "return=minimal"})

    def delete(self, table: str, filters: dict) -> None:
        self._send("DELETE", f"{self.base}/{table}", params=filters, headers={"Prefer": "return=minimal"})
