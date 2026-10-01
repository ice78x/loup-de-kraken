"""Bot cloud → Supabase (faux PostgREST en mémoire) + suivi des trades membres. Données SYNTHÉTIQUES."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from fake_kraken import FakeKraken, down
from kraken_assistant.app import App
from kraken_assistant.cloud import run as cloud
from kraken_assistant.cloud.supabase_rest import Supabase, SupabaseError
from kraken_assistant.cloud.tracker import advance_trade
from kraken_assistant.database.db import Database
from kraken_assistant.scanner.scan import scan


class FakePostgrest:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.seq = 0

    def _match(self, row, params):
        for k, v in params.items():
            if k in ("select", "on_conflict"):
                continue
            op, _, val = v.partition(".")
            cur = row.get(k)
            if op == "eq" and str(cur).lower() != val.lower():
                return False
            if op == "lt" and not (str(cur) < val):
                return False
        return True

    def handler(self, req: httpx.Request) -> httpx.Response:
        table = req.url.path.split("/rest/v1/")[1]
        params = dict(req.url.params)
        rows = self.tables.setdefault(table, [])
        if req.method == "GET":
            return httpx.Response(200, json=[r for r in rows if self._match(r, params)])
        if req.method == "POST":
            data = json.loads(req.content)
            data = data if isinstance(data, list) else [data]
            out = []
            for d in data:
                if "on_conflict" in params:
                    keys = params["on_conflict"].split(",")
                    ex = next((r for r in rows if all(r.get(k) == d.get(k) for k in keys)), None)
                    if ex:
                        ex.update(d)
                        continue
                self.seq += 1
                d = {"id": self.seq, **d}
                rows.append(d)
                out.append(d)
            return httpx.Response(201, json=out)
        if req.method == "PATCH":
            for r in rows:
                if self._match(r, params):
                    r.update(json.loads(req.content))
            return httpx.Response(204)
        if req.method == "DELETE":
            self.tables[table] = [r for r in rows if not self._match(r, params)]
            return httpx.Response(204)
        return httpx.Response(405)


def test_overrides_bornes_et_types():
    o = cloud.settings_overrides([
        {"key": "score_trade", "value": 99}, {"key": "min_rr_tp2", "value": "2.5"},
        {"key": "disabled_strategies", "value": ["news_momentum"]}, {"key": "live_trading", "value": True},
        {"key": "universe_max_crypto", "value": "abc"}])
    assert o["score_trade"] == 85                       # borné
    assert o["min_rr_tp2"] == 2.5
    assert o["disabled_strategies"] == ["news_momentum"]
    assert "live_trading" not in o                      # jamais modifiable depuis le site
    assert "universe_max_crypto" not in o


def _trade(**kw):
    t = {"id": 1, "status": "ouvert", "direction": "LONG", "entry_price": 100, "sl": 98, "tp1": 102, "tp2": 104,
         "tp3": 106, "qty": 1.0, "qty_remaining": 1.0, "eur_per_quote": 1, "fee_pct": 0, "realized_pnl_eur": 0,
         "risk_eur": 2.0, "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
         "opened_at": "2026-01-01T00:00:00+00:00", "last_checked": "2026-01-01T00:00:00+00:00", "events": []}
    t.update(kw)
    return t


def bars(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_tracker_tp_partiels_puis_cloture():
    upd, ev = advance_trade(_trade(), bars([(100, 102.5, 99.5, 102), (102, 104.2, 101.5, 104), (104, 106.5, 103, 106)]))
    assert upd["status"] == "clos" and upd["close_reason"] == "TP3"
    assert upd["realized_pnl_eur"] == pytest.approx(0.3 * 2 + 0.4 * 4 + 0.3 * 6)
    assert upd["r_multiple"] == pytest.approx(upd["realized_pnl_eur"] / 2)
    assert len(ev) == 3 and len(upd["events"]) == 3


def test_tracker_sl_prioritaire_et_short():
    upd, _ = advance_trade(_trade(), bars([(100, 102.5, 97.5, 101)]))
    assert upd["status"] == "clos" and upd["realized_pnl_eur"] == pytest.approx(-2.0)
    s = _trade(direction="SHORT", sl=102, tp1=98, tp2=96, tp3=94)
    upd, _ = advance_trade(s, bars([(100, 100.5, 97.8, 98.5)]))
    assert upd["tp1_hit"] and upd["qty_remaining"] == pytest.approx(0.7) and "status" not in upd


def test_tracker_rien_sans_bougie():
    upd, ev = advance_trade(_trade(), bars([]))
    assert ev == [] and "status" not in upd


def test_scan_envoie_au_site_et_suit_les_trades(settings, tmp_path):
    fk = FakeKraken(4)
    pg = FakePostgrest()
    sb = Supabase("https://x.supabase.co", "service", transport=httpx.MockTransport(pg.handler))
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": False,
                                    "min_volume_24h_eur_crypto": 1000, "min_volume_24h_eur_other": 100})
    app = App.build(s, spot_transport=httpx.MockTransport(fk.handler), news_transport=httpx.MockTransport(down),
                    db=Database(tmp_path / "c.db"))
    last = float(fk.series["LINKEUR"]["close"].iloc[-1])
    opened = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    pg.tables["trades"] = [{"id": 7, "status": "ouvert", "mode": "paper", "instrument_key": "spot:LINKEUR",
                            "display": "LINK/EUR", "venue": "spot", "api_symbol": "LINKEUR", "api_asset_class": None,
                            "direction": "LONG", "entry_price": last, "sl": last * 0.5, "tp1": last * 3, "tp2": last * 4,
                            "tp3": last * 5, "qty": 1, "qty_remaining": 1, "eur_per_quote": 1, "fee_pct": 0.4,
                            "realized_pnl_eur": 0, "risk_eur": 1, "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
                            "opened_at": opened, "last_checked": opened, "events": [], "auto_track": True}]
    rep = scan(app)
    sid = cloud.push_scan(sb, rep)
    cloud.push_instruments(sb, app)
    cloud.track_trades(sb, app)
    assert pg.tables["scans"][0]["verdict"] == rep.verdict and sid
    sigs = pg.tables.get("signals", [])
    assert len(sigs) == len(rep.trades) + len([w for w in rep.watch if w.inst_key in rep.analyses])
    for s_ in sigs:
        assert s_["candles"] and len(s_["candles"][0]) == 5 and s_["status"] in ("TRADE", "WATCH")
    assert any(i["key"] == "spot:LINKEUR" for i in pg.tables["instruments"])
    t = pg.tables["trades"][0]
    assert t["status"] == "ouvert" and t["advice"] and t["last_checked"] != opened


@pytest.mark.parametrize("key,bearer", [("sb_secret_abc123", False), ("eyJhbGciOiJIUzI1NiJ9.x.y", True)])
def test_cles_supabase_nouvelles_et_anciennes(key, bearer):
    """Nouvelle clé secrète (sb_secret_) : seulement dans apikey (Supabase refuse un Bearer non-JWT).
    Ancienne clé service_role (JWT) : apikey + Authorization."""
    seen = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json=[])
    Supabase(" https://x.supabase.co/ ", f" {key}\n", transport=httpx.MockTransport(h)).select("scans")
    assert seen["apikey"] == key
    assert ("authorization" in seen) is bearer
    if bearer:
        assert seen["authorization"] == f"Bearer {key}"


def test_cle_publique_refusee_pour_le_bot():
    with pytest.raises(SupabaseError, match="SECRÈTE"):
        Supabase("https://x.supabase.co", "sb_publishable_abc")


def test_nan_et_numpy_envoyes_en_json_strict():
    """Données réelles : NaN/inf/numpy ne doivent jamais casser l'envoi (Supabase refuse « NaN »)."""
    import numpy as np
    got = {}

    def h(req: httpx.Request) -> httpx.Response:
        got["body"] = json.loads(req.content)  # json strict : lèverait sur NaN
        return httpx.Response(201, json=[{"id": 1}])
    sb = Supabase("https://x.supabase.co", "sb_secret_x", transport=httpx.MockTransport(h))
    sb.insert("scans", {"a": float("nan"), "b": np.float64(1.5), "c": [np.int64(3), float("inf")], "d": {"e": np.nan}})
    assert got["body"] == {"a": None, "b": 1.5, "c": [3, None], "d": {"e": None}}


@pytest.mark.parametrize("status,body,mot", [
    (401, '{"message":"Invalid API key"}', "SECRÈTE"),
    (404, '{"code":"PGRST205","message":"Could not find the table public.scans"}', "schema.sql"),
    (400, '{"message":"Could not find the \'x\' column of \'scans\'"}', "schema.sql"),
])
def test_erreur_supabase_expliquee(status, body, mot, monkeypatch, capsys):
    def h(req):
        return httpx.Response(status, text=body)
    sb = Supabase("https://x.supabase.co", "sb_secret_x", transport=httpx.MockTransport(h))
    with pytest.raises(SupabaseError) as e:
        sb.insert("scans", {"a": 1})
    assert mot in e.value.hint()
    monkeypatch.setattr(cloud, "_main", lambda cmd: sb.insert("scans", {}))
    assert cloud.main(["scan"]) == 1
    assert "🛑 ERREUR SUPABASE" in capsys.readouterr().out
