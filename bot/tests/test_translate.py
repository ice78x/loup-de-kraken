"""Traduction des news (API MyMemory simulée) + explications en français."""
from datetime import datetime, timezone

import httpx

from kraken_assistant.database.db import Database
from kraken_assistant.news.engine import NewsItem
from kraken_assistant.news.translate import Translator, explain


def item(**kw):
    now = datetime.now(timezone.utc)
    base = dict(id="1", title="SEC approves spot Solana ETF", url="https://x", source="SEC", tier=1, scope="crypto",
                published_at=now, fetched_at=now, assets=["SOL"], categories=["ETF"], impact=3, direction_hint="haussier",
                verified=True)
    base.update(kw)
    return NewsItem(**base)


def test_traduction_et_memoire(tmp_path):
    calls = []

    def h(req):
        calls.append(dict(req.url.params))
        return httpx.Response(200, json={"responseStatus": 200, "responseData": {"translatedText": "La SEC approuve l&#39;ETF Solana au comptant"}})
    db = Database(tmp_path / "t.db")
    tr = Translator(db, transport=httpx.MockTransport(h), email="")
    assert tr.fr("SEC approves spot Solana ETF") == "La SEC approuve l'ETF Solana au comptant"
    assert calls[0]["langpair"] == "en|fr" and "de" not in calls[0]
    # 2e fois : depuis la mémoire, aucune nouvelle requête
    tr2 = Translator(db, transport=httpx.MockTransport(h), email="moi@exemple.fr")
    assert tr2.fr("SEC approves spot Solana ETF") == "La SEC approuve l'ETF Solana au comptant"
    assert len(calls) == 1


def test_quota_ou_panne_on_garde_l_anglais(tmp_path):
    def quota(req):
        return httpx.Response(200, json={"responseStatus": 429, "quotaFinished": True,
                                         "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}})
    tr = Translator(Database(tmp_path / "q.db"), transport=httpx.MockTransport(quota), email="")
    assert tr.fr("Bitcoin rallies") is None and tr.disabled
    assert tr.fr("Ether drops") is None                     # plus de requête après quota atteint

    def down(req):
        raise httpx.ConnectError("coupé")
    assert Translator(None, transport=httpx.MockTransport(down), email="").fr("Hello") is None


def test_explication_simple():
    e = explain(item())
    assert "ETF" in e and "plutôt favorable pour SOL" in e and "clôture 15 min" in e
    r = explain(item(is_rumor=True, verified=False, title="SOL ETF could be approved"))
    assert "rumeur" in r and "favorable" not in r
    m = explain(item(categories=["Fed"], assets=[], macro=True, direction_hint="incertain"))
    assert "Fed" in m and "tout le marché" in m
