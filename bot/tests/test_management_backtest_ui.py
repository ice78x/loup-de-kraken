import time

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import random_walk
from fake_kraken import FakeKraken, down
from kraken_assistant.app import App
from kraken_assistant.backtest.engine import BTParams, run_backtest
from kraken_assistant.database.db import Database
from kraken_assistant.market.candles import resample
from kraken_assistant.market.models import Instrument
from kraken_assistant.portfolio import management as mg
from kraken_assistant.portfolio.positions import Position
from kraken_assistant.risk.position_sizing import SizingInput, compute_position
from kraken_assistant.ui.server import create_app


def frames_from(d5):
    return {"5m": d5, "15m": resample(d5, 5, 15), "1h": resample(d5, 5, 60), "4h": resample(d5, 5, 240)}


def position(**kw):
    d = dict(id=1, source="paper", instrument_key="spot:X", display="X/EUR", base="X", venue="spot",
             asset_class="crypto", direction="LONG", entry=100.0, qty_initial=1.0, qty_remaining=1.0, sl=98.0,
             tp1=102.0, tp2=104.0, tp3=106.0, tp1_hit=False, tp2_hit=False, tp3_hit=False, status="open",
             eur_per_quote=1.0, fee_rate_pct=0.0, realized_pnl_eur=0.0, invalidation=98.5)
    d.update(kw)
    return Position(**d)


@pytest.fixture(scope="module")
def frames():
    return frames_from(random_walk(3000, start=100.0, vol=0.0008, seed=7))


def test_gestion_hold_tp_sl_invalidation(frames):
    last = float(frames["15m"]["close"].iloc[-1])
    p = position(entry=last, sl=last * 0.9, tp1=last * 1.2, tp2=last * 1.3, tp3=last * 1.4, invalidation=last * 0.92)
    assert mg.advise(p, frames, last).action in (mg.HOLD, mg.LET_RUN)
    assert mg.advise(p, frames, last * 1.21).action == mg.TAKE_TP
    assert mg.advise(p, frames, last * 0.89).action == mg.SL_HIT
    p2 = position(entry=last * 1.1, sl=last * 0.8, tp1=last * 1.3, tp2=last * 1.4, tp3=last * 1.5, invalidation=last * 1.05)
    assert mg.advise(p2, frames, last).action == mg.EXIT
    assert mg.advise(position(sl=None), frames, last).action == mg.SET_SL
    assert "DATA INSUFFISANTE" in mg.advise(p, None, None).details[0]


def test_gestion_pas_de_be_sans_tp1(frames):
    last = float(frames["15m"]["close"].iloc[-1])
    p = position(entry=last * 0.98, sl=last * 0.95, tp1=last * 1.1, tp2=last * 1.2, tp3=last * 1.3, invalidation=None)
    adv = mg.advise(p, frames, last)                 # prix favorable mais TP1 non atteint
    assert adv.new_sl is None


def test_r_net_de_frais():
    plan = compute_position(SizingInput(capital_eur=90, risk_percent=1, entry=100, stop_loss=98, direction="LONG",
                                        take_profits=[103, 106, 110], fee_rate_pct=0.4, allowed_leverages=[1]))
    assert all(n < b for n, b in zip(plan.r_multiples_net, plan.r_multiples))
    assert plan.r_multiples_net[0] == pytest.approx((3 - 0.004 * 203) / (2 + 0.004 * 198), abs=0.01)


def test_backtest_tourne_et_mesure():
    d15 = random_walk(1100, start=100.0, vol=0.003, seed=11, freq="15min")
    inst = Instrument("T", "T/EUR", "spot", "crypto", "spot", "T", "EUR", "online", True, True, True,
                      allowed_leverages_short=[2])
    from kraken_assistant.config import Settings
    t0 = time.time()
    res = run_backtest(d15, inst, Settings(_env_file=None), BTParams(fee_pct=0.1, warmup_bars=400))
    m = res.metrics()
    assert time.time() - t0 < 240
    assert "trades" in m
    if m["trades"]:
        assert {"win_rate_pct", "profit_factor", "max_drawdown_pct", "expectancy_r"} <= set(m)
    assert any("news" in n for n in res.notes)


def test_dashboard_et_api(settings, tmp_path):
    fk = FakeKraken(2)
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": False,
                                    "min_volume_24h_eur_crypto": 1000, "min_volume_24h_eur_other": 100})
    core = App.build(s, spot_transport=httpx.MockTransport(fk.handler), news_transport=httpx.MockTransport(down),
                     db=Database(tmp_path / "ui.db"))
    with TestClient(create_app(core, start_scheduler=False)) as c:
        assert c.get("/api/health").json()["live_armed"] is False
        assert "Kraken Assistant" in c.get("/").text
        out = c.post("/api/command", json={"command": "SCAN"}).json()["text"]
        assert out.splitlines()[0][0] in "🟢🟡🛑🔴"
        d = c.get("/api/dashboard").json()
        assert d["mode"] == "PAPER / ANALYSE" and d["capital"]["risk_capital_eur"] == 90.0
        assert d["opportunities"] and d["last_scan"]
