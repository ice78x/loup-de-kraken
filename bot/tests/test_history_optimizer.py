"""Historique local, contexte long terme, simulation, optimiseur (données SYNTHÉTIQUES)."""
import numpy as np
import pandas as pd
import pytest

from conftest import random_walk
from kraken_assistant.analysis.htf import htf_context
from kraken_assistant.backtest import optimizer as opt
from kraken_assistant.backtest.engine import Arrays, BTParams, Candidate, detect, simulate
from kraken_assistant.database.db import Database
from kraken_assistant.market.candles import resample
from kraken_assistant.market.history import CandleStore, HistoryService, merge
from kraken_assistant.market.models import Instrument
from kraken_assistant.risk.position_sizing import SizingInput, compute_position
from kraken_assistant.scanner.scan import apply_edges
from kraken_assistant.strategies.base import ACTION_ENTER, TRADE, WATCH, Setup


def inst(key="T", display="BTC/EUR", altname="XBTEUR", aclass="crypto"):
    return Instrument(key, display, "spot", aclass, "spot", "BTC", "EUR", "online", True, True, True,
                      allowed_leverages_short=[2], altname=altname)


# ------------------------------------------------------------------ stockage
def test_store_upsert_load_merge(tmp_path):
    st = CandleStore(Database(tmp_path / "c.db"))
    d = random_walk(100, freq="5min")
    assert st.upsert("spot:T", "5m", d) == 100
    assert st.upsert("spot:T", "5m", d.iloc[-10:]) == 10          # pas de doublons (clé primaire)
    back = st.load("spot:T", "5m")
    assert len(back) == 100
    assert np.allclose(back["close"].to_numpy(), d["close"].to_numpy())
    assert len(st.load("spot:T", "5m", limit=20)) == 20
    m = merge(back.iloc[:60], d.iloc[50:])
    assert len(m) == 100 and m.index.is_monotonic_increasing


def test_import_csv_officiel_kraken(tmp_path, settings):
    d = random_walk(50, freq="15min")
    f = tmp_path / "XBTEUR_15.csv"
    rows = np.column_stack([d.index.as_unit('s').asi8, d[["open", "high", "low", "close", "volume"]].to_numpy(),
                            np.full(len(d), 7)])
    np.savetxt(f, rows, delimiter=",", fmt=["%d", "%.6f", "%.6f", "%.6f", "%.6f", "%.4f", "%d"])
    (tmp_path / "XBTEUR_1.csv").write_text("")                      # intervalle non utilisé : ignoré
    hs = HistoryService(CandleStore(Database(tmp_path / "h.db")), None, None)
    rep = hs.import_kraken_csv(tmp_path, [inst()])
    assert rep == {"BTC/EUR 15m": 50}
    assert len(hs.history_15m(inst())) == 50


def test_history_15m_complete_avec_le_5m_accumule(tmp_path):
    hs = HistoryService(CandleStore(Database(tmp_path / "h.db")), None, None)
    d5 = random_walk(300, freq="5min")
    hs.store.upsert("spot:T", "5m", d5)
    d15 = hs.history_15m(inst())
    assert len(d15) == 100


# ------------------------------------------------------------------ contexte long terme
def test_htf_context_tendance_et_niveaux():
    d1 = random_walk(600, start=100, vol=0.02, seed=4, freq="1D", drift=0.004)
    w1 = resample(d1, 1440, 10080)
    ctx = htf_context(d1, w1, float(d1["close"].iloc[-1]))
    assert ctx.history_days >= 590
    assert ctx.ath == pytest.approx(max(d1["high"].max(), w1["high"].max()))
    assert ctx.levels and all(abs(lv.price / d1["close"].iloc[-1] - 1) <= 0.25 for lv in ctx.levels)
    assert 0 <= ctx.range_position <= 1
    assert htf_context(None, None, 100).notes


# ------------------------------------------------------------------ frais maker/taker
def test_entree_limite_moins_chere_que_marche():
    base = dict(capital_eur=90, risk_percent=1, entry=100, stop_loss=98, direction="LONG",
                take_profits=[103, 106, 110], fee_rate_pct=0.40, maker_fee_pct=0.25, allowed_leverages=[1])
    taker = compute_position(SizingInput(**base))
    maker = compute_position(SizingInput(**base, entry_is_maker=True))
    assert maker.position_size > taker.position_size                # moins de frais → un peu plus de taille
    assert maker.estimated_loss_at_sl_eur <= 0.90 + 1e-9 and taker.estimated_loss_at_sl_eur <= 0.90 + 1e-9
    assert maker.r_multiples_net[1] > taker.r_multiples_net[1]


# ------------------------------------------------------------------ simulation
def arrays(rows, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return Arrays.of(df)


def cand(**kw):
    d = dict(key="k", asset_class="crypto", i=0, ts=pd.Timestamp("2026-01-01", tz="UTC"), strategy="s",
             direction="LONG", entry_low=99.5, entry_high=100.0, sl=98.0, tps=(102.0, 104.0, 106.0), score=70, r2=2.0)
    d.update(kw)
    return Candidate(**d)


def test_simulation_tp_et_break_even_confirme():
    A = arrays([(100.5, 100.6, 100.3, 100.5),     # i=0 : bougie de détection
                (100.4, 100.5, 99.9, 100.2),      # entrée (limite 100)
                (100.2, 102.2, 100.1, 102.0),     # TP1
                (102.0, 102.3, 101.0, 101.5),     # clôture > entrée+0,3R (1)
                (101.5, 101.8, 101.0, 101.2),     # (2) → SL au BE
                (101.2, 101.3, 99.5, 99.8)])      # retour sous l'entrée → sortie BE
    r, j, why = simulate(cand(), A, BTParams(fee_pct=0, maker_fee_pct=0))
    assert why == "SL ajusté" and j == 5
    assert r == pytest.approx(0.3 * 2 / 2)          # 30 % × 2R = 0,6R ; reste sorti à 0


def test_simulation_sl_avant_tp_et_non_declenche():
    A = arrays([(100.5, 100.6, 100.3, 100.5), (100.2, 102.5, 97.5, 101.0)])
    r, _, why = simulate(cand(), A, BTParams(fee_pct=0, maker_fee_pct=0))
    assert why == "SL" and r == pytest.approx(-1.0)
    A2 = arrays([(100.5, 100.6, 100.3, 100.5)] + [(101, 101.5, 100.5, 101)] * 20)
    r2, _, why2 = simulate(cand(), A2, BTParams(fee_pct=0))
    assert r2 is None and why2 == "non déclenché"


def test_simulation_frais_reduisent_le_r():
    A = arrays([(100.5, 100.6, 100.3, 100.5), (100.2, 102.5, 97.5, 101.0)])
    r, _, _ = simulate(cand(), A, BTParams(fee_pct=0.4, maker_fee_pct=0.25))
    assert r < -1.0


# ------------------------------------------------------------------ pas de look-ahead
def test_detection_sans_look_ahead(settings):
    d15 = random_walk(1000, start=100, vol=0.004, seed=21, freq="15min")
    full = detect(d15, inst(), settings, warmup=400)
    part = detect(d15.iloc[:850], inst(), settings, warmup=400)
    key = lambda c: (c.i, c.strategy, c.direction, round(c.sl, 8), round(c.score, 3))
    assert [key(c) for c in full if c.i < 849] == [key(c) for c in part if c.i < 849]


# ------------------------------------------------------------------ optimiseur
def test_optimiseur_enregistre_et_scanner_applique(settings, tmp_path):
    db = Database(tmp_path / "o.db")
    s = settings.model_copy(update={"optimizer_max_bars": 700, "optimizer_min_trades": 3})
    data = {f"spot:T{k}": (inst(f"T{k}", f"T{k}/EUR", f"T{k}EUR"), random_walk(1100, 100, 0.004, 30 + k, "15min"))
            for k in range(2)}
    data = {i.key: (i, df) for i, df in data.values()}
    rep = opt.optimize(db, s, data, {k: (0.1, 0.05) for k in data}, workers=1)
    edges = opt.load_edges(db)
    assert len(edges) == len(opt.STRATEGIES) and len(rep["resultats"]) == len(edges)
    for e in edges.values():
        assert e.status in (opt.ADOPTED, opt.DISABLED, opt.UNPROVEN)
        if e.status == opt.UNPROVEN:
            assert (e.score_threshold, e.min_rr_tp2) == (s.score_trade, s.min_rr_tp2)
    # application au scanner
    e = next(iter(edges.values()))
    st = Setup("spot:X", "X/EUR", e.asset_class, e.strategy, "LONG", 99, 100, 98, [102, 104, 106], 98.5, "",
               ACTION_ENTER, confirmed=True, score=80, status=TRADE)
    e.status = opt.DISABLED
    apply_edges([st], {(e.asset_class, e.strategy): e}, s)
    assert st.status == WATCH and "désactivée" in st.rejections[0]
    st2 = Setup("spot:X", "X/EUR", e.asset_class, e.strategy, "LONG", 99, 100, 98, [102, 104, 106], 98.5, "",
                ACTION_ENTER, confirmed=True, score=62, status=TRADE)
    e.status, e.score_threshold, e.min_rr_tp2 = opt.ADOPTED, 70, 1.5
    apply_edges([st2], {(e.asset_class, e.strategy): e}, s)
    assert st2.status == WATCH                        # score 62 < seuil optimisé 70
    assert "hors échantillon" in st2.edge_note
