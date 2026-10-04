"""Moteur v2 : régime de marché, contexte BTC, score qualité, coupe-circuits, preuve statistique, walk-forward.
Données SYNTHÉTIQUES (tests de logique uniquement)."""
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from conftest import random_walk
from kraken_assistant.analysis import regime as R
from kraken_assistant.analysis.regime import MarketContext, Regime, regime_from_frames
from kraken_assistant.backtest.engine import Arrays, BTParams, BTTrade, Candidate, metrics
from kraken_assistant.backtest.walkforward import edge_table, proven, walk_forward_v2
from kraken_assistant.cloud.learning import degraded_strategies
from kraken_assistant.market.candles import resample
from kraken_assistant.strategies.quality import edge_key, grade, kill_switch, net_rr


def frames(df15):
    h1 = resample(df15, 15, 60)
    return h1, resample(h1, 60, 240)


# ------------------------------------------------------------------ régime
def test_tendance_haussiere_nette():
    h1, h4 = frames(random_walk(96 * 40, 100, 0.002, seed=3, freq="15min", drift=0.0009))
    rg = regime_from_frames(h1, h4, "up")
    assert rg.name in (R.TREND_UP, R.BREAKOUT_UP) and rg.bias == "LONG"
    assert rg.allows("tendance_pullback", "LONG") or rg.allows("cassure_retest", "LONG")
    assert not rg.allows("tendance_pullback", "SHORT")


def test_tendance_baissiere_nette():
    h1, h4 = frames(random_walk(96 * 40, 100, 0.002, seed=4, freq="15min", drift=-0.0009))
    rg = regime_from_frames(h1, h4, "down")
    assert rg.name in (R.TREND_DOWN, R.BREAKOUT_DOWN) and rg.bias == "SHORT"


def test_marche_sans_direction_jamais_en_tendance():
    """Bruit pur oscillant autour d'un prix : jamais une tendance (range, incertain ou chaotique)."""
    n = 96 * 40
    t = np.arange(n)
    close = 100 + 1.5 * np.sin(t / 40) + np.random.default_rng(5).normal(0, 0.05, n)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": np.r_[close[0], close[:-1]], "close": close}, index=idx)
    df["high"] = df[["open", "close"]].max(axis=1) + 0.05
    df["low"] = df[["open", "close"]].min(axis=1) - 0.05
    df["volume"] = 100.0
    rg = regime_from_frames(*frames(df), "range")
    assert rg.name not in (R.TREND_UP, R.TREND_DOWN)
    assert rg.bias is None or rg.name.startswith("BREAKOUT")


def test_volatilite_extreme_pas_de_trade():
    df = random_walk(96 * 30, 100, 0.002, seed=6, freq="15min")
    shock = random_walk(16, float(df["close"].iloc[-1]), 0.03, seed=7, freq="15min",
                        end=df.index[-1] + pd.Timedelta(minutes=15 * 16))
    rg = regime_from_frames(*frames(pd.concat([df, shock])), "range")
    assert rg.name == R.HIGH_VOL and not rg.allows("rejet_sweep", "LONG")


# ------------------------------------------------------------------ contexte BTC
def test_btc_contre_le_trade_bloque_les_altcoins():
    btc = Regime(R.TREND_DOWN, confidence=0.8)
    v, pts, why = MarketContext(btc=btc).check("SOL", "crypto", "LONG")
    assert v == "bloque" and pts == 0 and "BTC" in why[0]
    assert MarketContext(btc=btc).check("SOL", "crypto", "SHORT")[0] == "favorable"
    assert MarketContext(btc=btc).check("BTC", "crypto", "LONG")[0] == "neutre"        # BTC lui-même : pas concerné
    assert MarketContext(btc=btc).check("NVDA", "xstock", "LONG")[0] == "neutre"


def test_btc_tres_volatil_ou_choc_bloque():
    assert MarketContext(btc=Regime(R.HIGH_VOL, 1)).check("ETH", "crypto", "SHORT")[0] == "bloque"
    assert MarketContext(btc=Regime(R.RANGE, 0.6, move_4h_atr=-3.0)).check("ETH", "crypto", "LONG")[0] == "bloque"


# ------------------------------------------------------------------ score qualité et coupe-circuits
def _st(strategy="rejet_sweep", direction="LONG"):
    from kraken_assistant.strategies.base import Setup
    return Setup("k", "PF_XUSD", "crypto", strategy, direction, 99.5, 100, 98, [103, 104.5, 106], 98, "", "",
                 confirmed=True)


def _a(rg, btc=None, s4="range", s1="range"):
    return NS(regime=rg, context=MarketContext(btc=btc), inst=NS(base="X", asset_class="crypto", venue="futures", taker_fee_pct=None),
              structures={"4h": NS(trend=s4), "1h": NS(trend=s1)})


def test_r_net_de_frais():
    st = _st()
    nr = net_rr(st, 0.05, 0.02)
    assert nr[1] < st.r_multiples()[1] and nr[1] == pytest.approx((4.5 - 0.02 - 0.0209) / (2 + 0.02 + 0.049), abs=0.01)


def test_coupe_circuits(settings):
    s = settings.model_copy(update={"require_proven_edge": True, "v2_edges": {}})
    q = {"regime": Regime(R.CHAOTIC, 1), "net_rr": [1.4, 2.0, 2.8]}
    k = kill_switch(_st(), _a(q["regime"]), s, q)
    assert any("chaotique" in x for x in k) and any("non démontré" in x for x in k)
    q = {"regime": Regime(R.TREND_DOWN, 0.8), "net_rr": [1.4, 2.0, 2.8]}
    k = kill_switch(_st(), _a(q["regime"], s4="down", s1="up"), s, q)
    assert any("non adaptée" in x for x in k) and any("conflit" in x for x in k)


def test_preuve_statistique(settings):
    rg = Regime(R.RANGE, 0.8)
    q = {"regime": rg, "net_rr": [1.4, 2.0, 2.8]}
    key = edge_key("rejet_sweep", R.RANGE)
    ok = settings.model_copy(update={"v2_edges": {key: {"n": 40, "expectancy_r": 0.25, "profit_factor": 1.5}}})
    assert kill_switch(_st(), _a(rg), ok, q) == []
    bad = settings.model_copy(update={"v2_edges": {key: {"n": 40, "expectancy_r": -0.1, "profit_factor": 0.8}}})
    assert any("perd en backtest" in x for x in kill_switch(_st(), _a(rg), bad, q))
    few = settings.model_copy(update={"v2_edges": {key: {"n": 8, "expectancy_r": 0.9, "profit_factor": 3}}})
    assert any("non démontré" in x for x in kill_switch(_st(), _a(rg), few, q))
    off = settings.model_copy(update={"require_proven_edge": False})
    assert kill_switch(_st(), _a(rg), off, q) == []


def test_notes(settings):
    assert [grade(x, settings) for x in (95, 85, 75, 60)] == ["A+", "A", "B", "C"]


# ------------------------------------------------------------------ dégradation
def test_serie_de_pertes_suspend_la_strategie():
    rows = [{"strategy": "rejet_sweep", "status": "TRADE", "r": -1.0, "created_at": f"2026-10-0{i}"} for i in range(1, 6)]
    rows += [{"strategy": "tendance_pullback", "status": "TRADE", "r": r, "created_at": f"2026-10-0{i}"}
             for i, r in enumerate([-1, 1.2, -1, 2.0, -1], 1)]
    bad = degraded_strategies(rows)
    assert list(bad) == ["rejet_sweep"] and "5 pertes" in bad["rejet_sweep"]


# ------------------------------------------------------------------ métriques et walk-forward
def test_metriques_completes():
    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    tr = [BTTrade("k", "s", "LONG", t0 + pd.Timedelta(hours=i), t0 + pd.Timedelta(hours=i + 1), r, "x", "RANGE", "crypto")
          for i, r in enumerate([1.5, -1, -1, -1, 2.0, -1, 0.5])]
    m = metrics(tr)
    assert m["trades"] == 7 and m["pire_serie_pertes"] == 3 and m["expectancy_r"] == pytest.approx(0.0, abs=1e-9)
    assert m["profit_factor"] == pytest.approx(4.0 / 4.0) and m["max_drawdown_pct"] > 2.9
    assert m["par_regime"]["RANGE"]["trades"] == 7 and "sharpe_par_trade" in m


def _cands_and_arrays():
    """2 « stratégies » synthétiques : A gagne toujours, B perd toujours, réparties dans le temps."""
    n = 4000
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    o = np.full(n, 100.0)
    h, l, c = o.copy(), o.copy(), o.copy()
    cands = []
    for k, i in enumerate(range(100, n - 20, 60)):
        win = k % 2 == 0
        h[i + 1], l[i + 1] = 100.2, 99.7                      # remplissage de l'ordre limite (zone 99.8–100)
        if win:
            h[i + 3] = 107.0                                  # tous les TP
        else:
            l[i + 3] = 97.0                                   # stop
        cands.append(Candidate("k", "crypto", i, idx[i], "A" if win else "B", "LONG", 99.8, 100.0, 98.0, (102, 104, 106),
                               70, 2.0, quality=85, regime=R.RANGE, legacy_trade=True))
    arrays = {"k": Arrays(o, h, l, c, idx)}
    return cands, arrays


def test_walk_forward_n_utilise_que_le_passe(settings):
    cands, arrays = _cands_and_arrays()
    s = settings.model_copy(update={"edge_min_trades": 5})
    rep = walk_forward_v2(cands, arrays, s, BTParams(fee_pct=0.05, maker_fee_pct=0.02), folds=5)
    assert rep["avant"]["trades"] > rep["apres"]["trades"] > 0
    assert set(rep["apres"]["par_strategie"]) == {"A"}                 # B, perdante sur le passé, n'est jamais jouée
    assert rep["apres"]["expectancy_r"] > 0 > rep["avant"]["expectancy_r"] or rep["avant"]["expectancy_r"] < rep["apres"]["expectancy_r"]
    assert rep["edges"][edge_key("A", R.RANGE)]["prouve"] and not rep["edges"][edge_key("B", R.RANGE)]["prouve"]
    assert rep["folds"][0]["combinaisons_prouvees"] == [edge_key("A", R.RANGE)]


def test_table_des_edges(settings):
    e = edge_table([("x|RANGE", 1.0)] * 15 + [("x|RANGE", -1.0)] * 10)
    assert e["x|RANGE"]["n"] == 25 and e["x|RANGE"]["profit_factor"] == 1.5
    assert proven(e["x|RANGE"], settings)
    e["x|RANGE"].update(oos_n=8, oos_expectancy_r=-0.2)
    assert not proven(e["x|RANGE"], settings)                         # positif sur tout, mais négatif hors échantillon


def test_detection_v2_bout_en_bout(settings):
    """La détection rejouée enregistre ancien score, qualité, régime et coupe-circuits, avec le contexte BTC."""
    from kraken_assistant.backtest.engine import ContextSeries, detect, regime_series
    from kraken_assistant.market.models import Instrument
    btc = random_walk(1500, 100, 0.004, seed=31, freq="15min")
    ends, regs = regime_series(btc)
    assert len(regs) > 0 and len(ends) == len(regs)
    alt = random_walk(1500, 10, 0.005, seed=32, freq="15min")
    inst = Instrument("PF_AUSD", "PF_AUSD", "futures", "crypto", "perpetual", "A", "USD", "online", True, True, True)
    cands = detect(alt, inst, settings, warmup=400, ctx=ContextSeries(ends, regs))
    assert cands, "la marche aléatoire doit produire au moins un setup"
    c = cands[0]
    assert 0 <= c.quality <= 100 and c.regime and isinstance(c.kill, tuple)


def test_backtest_cloud_bout_en_bout(settings, tmp_path, monkeypatch):
    """Commande cloud « backtest » : univers → backfill → détection → walk-forward → résumé, sur un faux Kraken."""
    import httpx
    import fake_kraken as fkm
    from kraken_assistant.app import App
    from kraken_assistant.backtest.runner import run_v2, summary_text
    from kraken_assistant.database.db import Database
    fk = fkm.FakeKraken(3)
    fk.fut = fkm.gen_series(77, 150, n5=3 * 96 * 24)                      # 24 jours de bougies 5 min
    orig = fkm.to_rows
    monkeypatch.setattr(fkm, "to_rows", lambda df, m: orig(df, m) if m != 15 else
                        [[int(ts.timestamp()), r.open, r.high, r.low, r.close, r.close, r.volume, 1]
                         for ts, r in df.resample("15min", label="left", closed="left", origin="epoch").agg(
                             {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().iterrows()])
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": True, "perps_only": True})
    app = App.build(s, spot_transport=httpx.MockTransport(fk.handler), futures_transport=httpx.MockTransport(fk.handler),
                    news_transport=httpx.MockTransport(fkm.down), db=Database(tmp_path / "bt.db"))
    rep = run_v2(app, days=30, max_instruments=3, workers=1, folds=3)
    assert "avant" in rep and "apres" in rep and rep["instruments"], rep.get("message")
    assert rep["regles"]["frais"].startswith("taker 0.05")
    txt = summary_text(rep)
    assert "AVANT" in txt and "APRÈS" in txt
    print(txt)
