"""Moteur SWING en direct : stop suiveur jour par jour, risque ouvert, tâche journalière (faux Supabase). Données SYNTHÉTIQUES."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import httpx
import numpy as np
import pandas as pd

from kraken_assistant.cloud.supabase_rest import Supabase
from kraken_assistant.swing import live as L
from test_cloud import FakePostgrest


def _bars(closes, start="2026-08-01"):
    idx = pd.date_range(start, periods=len(closes), freq="1D", tz="UTC")
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c, "volume": 1.0}, index=idx)


def _pos(**kw):
    p = {"id": 1, "instrument_key": "futures:PF_XBTUSD", "display": "PF_XBTUSD", "direction": "LONG",
         "variant": "canal_20_10|trail|long", "signal_date": "2026-08-01", "signal_close": 100.0, "atr": 3.0,
         "entry_low": 99.25, "entry_high": 100.75, "stop_initial": 94.0, "stop_current": 94.0, "status": "ouvert", "history": []}
    p.update(kw)
    return p


def test_stop_suiveur_monte_puis_stop_touche():
    up = [100 * 1.02 ** i for i in range(15)]
    df = _bars(up + [up[-1] * 0.7])
    upd, ev = L.advance_position(_pos(), df)
    assert upd["entry_price"] == df["open"].iloc[1]                     # entrée = ouverture du lendemain du signal
    assert upd["status"] == "clos" and upd["r"] > 0                      # le stop suiveur a gardé du gain
    assert any("remonté" in e for e in ev) and "stop touché" in ev[-1]


def test_rien_ne_bouge_sans_nouvelle_bougie_et_stop_jamais_recule():
    df = _bars([100, 101, 102])
    p = _pos(stop_current=101.5, history=[{"date": "2026-08-03", "stop": 101.5, "close": 102}], entry_price=100)
    assert L.advance_position(p, df) == ({}, [])                         # dernier jour déjà traité
    p2 = _pos(stop_current=95.0, entry_price=100.0)
    upd, _ = L.advance_position(p2, _bars([100, 101, 99.5]))
    assert upd["stop_current"] >= 95.0


def test_risque_ouvert_libere_par_le_point_mort():
    a = _pos(entry_price=100, stop_current=94)                          # risque plein
    b = _pos(entry_price=100, stop_current=101)                         # stop au-dessus de l'entrée
    assert L.open_risk_units([a]) == 1.0 and L.open_risk_units([a, b]) == 1.0


def test_tache_journaliere_une_fois_par_jour_et_seulement_si_prouve(monkeypatch):
    pg = FakePostgrest()
    sb = Supabase("https://x.supabase.co", "service", transport=httpx.MockTransport(pg.handler))
    closes = list(100 + np.random.default_rng(1).uniform(-1, 1, 80)) + [110.0]
    df = _bars(closes, start="2026-07-30")                              # dernière bougie clôturée = 2026-10-18
    inst = NS(key="futures:PF_XBTUSD", display="PF_XBTUSD", asset_class="crypto", quote="USD", venue="futures", symbol="PF_XBTUSD")
    app = NS(discovery=NS(discover=lambda: [inst]))
    monkeypatch.setattr(L, "_daily", lambda app, i: df)
    monkeypatch.setattr("kraken_assistant.backtest.runner.pick_universe", lambda app, n, classes=None: [inst])
    now = datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc)
    # pas de backtest swing prouvé → aucun signal
    out = L.daily_job(sb, app, now)
    assert out["nouvelles"] == 0 and not pg.tables.get("swing_positions")
    assert L.daily_job(sb, app, now)["statut"] == "déjà fait"
    # backtest prouvé (pas une étude) → le signal est publié le jour suivant
    pg.tables["bot_settings"] = []
    pg.tables["backtest_runs"] = [{"id": 9, "created_at": "2026-10-18T05:00:00Z", "report": {"type": "swing", "par_classe": {
        "crypto": {"variante_retenue": "canal_55_20|trail|long", "prouve": True}}}}]
    out = L.daily_job(sb, app, now)
    rows = pg.tables["swing_positions"]
    assert out["nouvelles"] == 1 and rows[0]["direction"] == "LONG" and rows[0]["stop_initial"] < 110
    # une étude n'autorise jamais rien
    pg.tables["backtest_runs"][0]["report"]["etude"] = True
    assert L.swing_proof(sb) == {}


def test_attend_la_bougie_d_hier(monkeypatch):
    pg = FakePostgrest()
    sb = Supabase("https://x.supabase.co", "service", transport=httpx.MockTransport(pg.handler))
    inst = NS(key="futures:PF_XBTUSD", display="PF_XBTUSD", asset_class="crypto", quote="USD", venue="futures", symbol="PF_XBTUSD")
    monkeypatch.setattr(L, "_daily", lambda app, i: _bars([100] * 30, start="2026-09-18"))   # s'arrête le 17/10
    out = L.daily_job(sb, NS(discovery=NS(discover=lambda: [inst])), datetime(2026, 10, 19, 0, 2, tzinfo=timezone.utc))
    assert out["statut"] == "attente bougie" and not pg.tables.get("bot_settings")           # jour PAS marqué comme fait


def test_messages_simples():
    p = _pos(r=1.8, exit_price=120.0)
    assert "SWING LONG BTC" in L.msg_new(p) and "Paper" in L.msg_new(p)
    assert "+1,80 R" in L.msg_close(p).replace(".", ",")


def test_deux_canaux_prouves_et_demi_risque(monkeypatch):
    pg = FakePostgrest()
    sb = Supabase("https://x.supabase.co", "service", transport=httpx.MockTransport(pg.handler))
    rng = np.random.default_rng(2)
    # cassure du plus haut de 20 jours mais PAS de 55 jours : seule la variante 20 jours donne un signal
    closes = list(130 + rng.uniform(-1, 1, 40)) + list(100 + rng.uniform(-1, 1, 40)) + [104.0]
    df = _bars(closes, start="2026-07-30")
    insts = [NS(key=f"futures:PF_{c}USD", display=f"PF_{c}USD", asset_class="crypto", quote="USD", venue="futures", symbol=f"PF_{c}USD")
             for c in ("XBT", "A", "B", "C", "D", "E")]
    app = NS(discovery=NS(discover=lambda: insts), settings=NS(swing_risk_pct=0.5, swing_universe=40))
    monkeypatch.setattr(L, "_daily", lambda app, i: df)
    monkeypatch.setattr("kraken_assistant.backtest.runner.pick_universe", lambda app, n, classes=None: insts)
    pg.tables["backtest_runs"] = [{"id": 9, "created_at": "2026-10-18T05:00:00Z", "report": {"type": "swing", "par_classe": {
        "crypto": {"variante_retenue": "canal_55_20|trail|long", "prouve": True,
                   "variantes_prouvees": ["canal_20_10|trail|long", "canal_55_20|trail|long"]}}}}]
    out = L.daily_job(sb, app, datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc))
    rows = pg.tables["swing_positions"]
    assert all(r["variant"] == "canal_20_10|trail|long" for r in rows)
    assert out["nouvelles"] == 4 and out["refusees"] == 2                      # 0,5 % chacune → 4 dans les 2 %
    assert rows[0]["history"][0]["risque_pct"] == 0.5 and rows[0]["history"][0]["palier"] in (1, 2, 3, 4)


def test_message_avec_confiance():
    m = L.msg_new(_pos(), 1.0, 3)
    assert "Confiance : <b>3/4</b>" in m and "perte au stop = 1 %" in m
