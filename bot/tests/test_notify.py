"""Notifications Telegram des 🟢 : message lisible, jamais de 🟡, pas de doublon, rien sans configuration."""
from datetime import datetime, timezone

import httpx

from kraken_assistant.cloud import notify

ROW = {"id": 701, "status": "TRADE", "display": "PF_SOLUSD", "instrument_key": "futures:PF_SOLUSD", "direction": "LONG",
       "score": 84.2, "grade": "A", "regime": "TREND_UP", "entry_low": 150.2, "entry_high": 150.6, "sl": 148.9,
       "tp1": 152.0, "tp2": 153.5, "tp3": 155.0, "rr_net": [0.8, 1.7, 2.6], "invalidation": "Clôture 15m sous 148.9",
       "action": "ENTRÉE (ordre limite dans la zone)"}


class FakeSb:
    def __init__(self, recent):
        self.recent = recent

    def select(self, table, params):
        return self.recent


def capture():
    sent = []

    def handler(req):
        sent.append(req)
        return httpx.Response(200, json={"ok": True})
    return sent, httpx.Client(transport=httpx.MockTransport(handler))


def test_message_court_et_complet():
    m = notify.signal_message(ROW)
    assert m.splitlines()[0] == "<b>🟢 TRADE VALIDÉ</b>" and "LONG ↑ SOL" in m
    for x in ("150.2", "148.9", "152", "153.5", "155", "R:R net TP2 = 1.7", "1 %", "#/signal/701", "pas garantie"):
        assert x in m
    assert "sûr" not in m and "garanti " not in m
    assert notify.signal_message({**ROW, "grade": "A+"}).startswith("<b>🔥 TRADE A+</b>")


def test_rien_sans_configuration(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    sent, c = capture()
    assert notify.notify_trades(FakeSb([]), [ROW], client=c) == 0 and not sent


def test_envoi_sans_doublon_ni_jaune(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111, 222")
    sent, c = capture()
    watch = {**ROW, "id": 702, "status": "WATCH", "display": "PF_ETHUSD", "instrument_key": "futures:PF_ETHUSD"}
    n = notify.notify_trades(FakeSb([{"id": 701, "instrument_key": ROW["instrument_key"], "direction": "LONG"}]), [ROW, watch],
                             client=c, now=datetime(2026, 10, 4, tzinfo=timezone.utc))
    assert n == 2 and len(sent) == 2                                  # 1 🟢 × 2 destinataires, le 🟡 ignoré
    assert sent[0].url.path == "/bot123:abc/sendMessage"
    # déjà notifié il y a moins de 4 h (autre signal, même actif, même sens) → pas renvoyé
    sent.clear()
    assert notify.notify_trades(FakeSb([{"id": 650, "instrument_key": ROW["instrument_key"], "direction": "LONG"}]), [ROW], client=c) == 0
    assert not sent


def test_bienvenue_une_seule_fois(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    sent, c = capture()

    class Sb:
        rows = []

        def select(self, table, params):
            return self.rows

        def upsert(self, table, rows, key):
            self.rows = rows

    sb = Sb()
    assert notify.welcome_once(sb, client=c) is True and len(sent) == 1 and "Notifications activées" in sent[0].content.decode()
    assert sb.rows[0]["key"] == "telegram_bienvenue"
    assert notify.welcome_once(sb, client=c) is False and len(sent) == 1
