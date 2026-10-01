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
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SupabaseError(Exception):
    pass


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
            raise SupabaseError(f"Supabase {r.status_code}: {r.text[:300]}")
        if not r.content:
            return None
        return r.json()

    def select(self, table: str, params: dict | None = None) -> list[dict]:
        return self._check(self.client.get(f"{self.base}/{table}", params={"select": "*", **(params or {})})) or []

    def insert(self, table: str, rows: list[dict] | dict, returning: bool = True) -> list[dict]:
        headers = {"Prefer": "return=representation" if returning else "return=minimal"}
        return self._check(self.client.post(f"{self.base}/{table}", content=json.dumps(rows, default=str),
                                            headers=headers)) or []

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if not rows:
            return
        headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
        for i in range(0, len(rows), 500):
            self._check(self.client.post(f"{self.base}/{table}", params={"on_conflict": on_conflict},
                                         content=json.dumps(rows[i:i + 500], default=str), headers=headers))

    def update(self, table: str, filters: dict, data: dict) -> None:
        self._check(self.client.patch(f"{self.base}/{table}", params=filters, content=json.dumps(data, default=str),
                                      headers={"Prefer": "return=minimal"}))

    def delete(self, table: str, filters: dict) -> None:
        self._check(self.client.delete(f"{self.base}/{table}", params=filters, headers={"Prefer": "return=minimal"}))
