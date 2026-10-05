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


class MemSb:
    """Mini Supabase en mémoire : bot_settings, signals, telegram_subscribers."""
    def __init__(self):
        self.t = {"bot_settings": [], "signals": [], "telegram_subscribers": []}

    def select(self, table, params=None):
        rows = self.t[table]
        p = params or {}
        if "key" in p:
            rows = [r for r in rows if r.get("key") == p["key"][3:]]
        if p.get("active") == "eq.true":
            rows = [r for r in rows if r.get("active")]
        return [dict(r) for r in rows]

    def upsert(self, table, rows, key):
        k = key.split(",")[0]
        for r in rows:
            cur = next((x for x in self.t[table] if x.get(k) == r[k]), None)
            if cur:
                cur.update(r)
            else:
                self.t[table].append(dict(r))

    def update(self, table, filters, data):
        k, v = next(iter(filters.items()))
        for r in self.t[table]:
            if str(r.get(k)) == v[3:]:
                r.update(data)


def telegram(updates, blocked=()):
    sent = []

    def handler(req):
        if req.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": updates})
        import json as _j
        body = _j.loads(req.content)
        sent.append(body)
        if str(body["chat_id"]) in blocked:
            return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
        return httpx.Response(200, json={"ok": True})
    return sent, httpx.Client(transport=httpx.MockTransport(handler))


def test_abonnement_automatique_puis_stop(monkeypatch):
    """« Démarrer » sur le bot = abonné (bienvenue), « /stop » = désabonné ; la position de lecture avance."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sb = MemSb()
    ups = [{"update_id": 10, "message": {"chat": {"id": 555, "type": "private", "first_name": "Nora"}, "text": "/start"}},
           {"update_id": 11, "message": {"chat": {"id": -100777, "type": "group", "title": "Club"}, "text": "salut"}}]
    sent, c = telegram(ups)
    assert notify.poll_subscribers(sb, c) == {"nouveaux": 2, "partis": 0}
    assert {s["chat_id"] for s in sent} == {"555", "-100777"} and "Bienvenue" in sent[0]["text"]
    assert sb.select("bot_settings", {"key": "eq.telegram_offset"})[0]["value"] == 12
    assert sorted(notify.recipients(sb)) == ["-100777", "555"]
    sent, c = telegram([{"update_id": 12, "message": {"chat": {"id": 555, "type": "private"}, "text": "/stop"}}])
    assert notify.poll_subscribers(sb, c) == {"nouveaux": 0, "partis": 1}
    assert notify.recipients(sb) == ["-100777"]


def test_signal_envoye_aux_abonnes_et_bloques_retires(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    sb = MemSb()
    sb.t["telegram_subscribers"] = [{"chat_id": "555", "active": True}, {"chat_id": "666", "active": True}, {"chat_id": "777", "active": False}]
    sent, c = telegram([], blocked={"666"})
    n = notify.notify_trades(sb, [ROW], client=c)
    assert n == 2 and {s["chat_id"] for s in sent} == {"111", "555", "666"}           # 777 désabonné : rien
    assert next(r for r in sb.t["telegram_subscribers"] if r["chat_id"] == "666")["active"] is False   # a bloqué le bot
