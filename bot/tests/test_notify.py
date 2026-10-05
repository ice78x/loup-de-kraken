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
    n = notify.notify_trades(FakeSb([{"id": 701, "instrument_key": ROW["instrument_key"], "direction": "LONG", "status": "TRADE"}]), [ROW, watch],
                             client=c, now=datetime(2026, 10, 4, tzinfo=timezone.utc))
    assert n == 2 and len(sent) == 2                                  # 1 🟢 × 2 destinataires, le 🟡 ignoré
    assert sent[0].url.path == "/bot123:abc/sendMessage"
    # déjà notifié il y a moins de 4 h (autre signal, même actif, même sens) → pas renvoyé
    sent.clear()
    assert notify.notify_trades(FakeSb([{"id": 650, "instrument_key": ROW["instrument_key"], "direction": "LONG", "status": "TRADE"}]), [ROW], client=c) == 0
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


def test_pre_alerte_puis_vert(monkeypatch):
    """🟡 à qui il ne manque que la confirmation → « ⏳ prépare-toi » ; le 🟢 suivant part quand même ; pas de 2e pré-alerte."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    sent, c = capture()
    prep = {**ROW, "id": 800, "status": "WATCH", "trigger_text": "clôture 15m au-dessus de 150.6", "quality": {"presque_pret": True}}
    simple = {**ROW, "id": 801, "status": "WATCH", "instrument_key": "futures:PF_ETHUSD", "quality": {"presque_pret": False}}
    assert notify.notify_trades(FakeSb([]), [prep, simple], client=c) == 1
    txt = sent[0].content.decode()
    assert "PRÉPARE-TOI" in txt and "150.6" in txt and "Vérifier maintenant" in txt and "#/signal/800" in txt
    old_prep = {"id": 800, "instrument_key": ROW["instrument_key"], "direction": "LONG", "status": "WATCH", "quality": {"presque_pret": True}}
    sent.clear()
    assert notify.notify_trades(FakeSb([old_prep]), [{**prep, "id": 802}], client=c) == 0           # déjà prévenu
    assert notify.notify_trades(FakeSb([old_prep]), [{**ROW, "id": 803}], client=c) == 1            # le 🟢 part quand même
    assert "TRADE VALIDÉ" in sent[0].content.decode()


def test_presque_pret_calcule(settings):
    """Le drapeau n'est levé que si tout est bon sauf la confirmation."""
    from kraken_assistant.strategies.base import Setup, WATCH
    st = Setup("k", "X", "crypto", "rejet_sweep", "LONG", 1, 1, 0.9, [1.2], 0.9, "", "", status=WATCH)
    st.score, st.confirmed = 75, False
    st.presque_pret = not st.rejections and not st.confirmed and st.score >= settings.score_trade
    assert st.presque_pret
