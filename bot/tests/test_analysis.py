"""Indicateurs, structure et classification des cassures (données synthétiques)."""
import numpy as np
import pandas as pd
import pytest

from conftest import make_df, random_walk
from kraken_assistant.analysis import breakout as bo
from kraken_assistant.analysis.indicators import atr, ema, rsi
from kraken_assistant.analysis.structure import classify_trend, find_swings
from kraken_assistant.market.candles import resample, validate_frame


def test_rsi_bornes_et_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    s = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                   46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])
    r = rsi(s).iloc[-1]
    assert 0 < r < 100


def test_atr_constant():
    df = make_df([(10, 11, 9, 10)] * 30)
    assert atr(df).iloc[-1] == pytest.approx(2.0)


def test_ema_converge():
    s = pd.Series([5.0] * 50)
    assert ema(s, 20).iloc[-1] == pytest.approx(5.0)


def test_swings_tendance_haussiere():
    # zigzag montant : HH / HL
    pts = []
    for k in range(6):
        b = 100 + k * 5
        pts += [b, b + 2, b + 4, b + 6, b + 4, b + 3, b + 2]
    df = make_df([(p, p + 0.5, p - 0.5, p) for p in pts])
    sw = find_swings(df, 2, 2)
    trend, labels = classify_trend(sw)
    assert trend == "up"
    assert "HH" in labels and "HL" in labels


def test_resample_buckets_complets():
    d5 = random_walk(30, freq="5min")
    d15 = resample(d5, 5, 15)
    assert len(d15) == 10
    assert d15["high"].iloc[0] == pytest.approx(d5["high"].iloc[:3].max())
    assert d15["volume"].iloc[0] == pytest.approx(d5["volume"].iloc[:3].sum())


def test_validation_detecte_incoherences():
    d = random_walk(200, freq="5min", end=pd.Timestamp.now(tz="UTC").floor("5min") - pd.Timedelta(minutes=5))
    assert validate_frame(d, "5m") == []
    bad = d.copy()
    bad.iloc[50, bad.columns.get_loc("high")] = bad["low"].iloc[50] - 1
    assert any("incohérentes" in x for x in validate_frame(bad, "5m"))
    stale = random_walk(200, freq="5min", end=pd.Timestamp("2025-01-01", tz="UTC"))
    assert any("périmées" in x for x in validate_frame(stale, "5m"))


# ---------- scénarios de cassure sur 15m ----------
RANGE = [(99.0, 99.8, 98.4, 99.2), (99.2, 99.9, 98.6, 98.9), (98.9, 99.7, 98.3, 99.4), (99.4, 99.95, 98.8, 99.0)] * 10


def _scenario(tail, vols_tail):
    rows = RANGE + tail
    vols = [100.0] * len(RANGE) + vols_tail
    return make_df(rows, volume=vols)


def test_cassure_confirmee_avec_retest():
    tail = [(99.3, 101.2, 99.2, 101.0),   # cassure clôturée au-dessus de 100 avec volume
            (101.0, 101.3, 100.4, 100.9),
            (100.9, 101.0, 100.05, 100.6),  # retest : mèche basse proche de 100, clôture au-dessus
            (100.6, 101.4, 100.5, 101.3)]   # confirmation : clôture > plus haut du retest
    df = _scenario(tail, [300, 120, 90, 150])
    ev = bo.classify_level(df, 100.0, "up", atr15=1.2)
    assert ev.state == bo.CONFIRMED_RETEST and ev.implied_direction == "LONG"
    assert ev.retest_extreme == pytest.approx(100.05)


def test_meche_seule_nest_pas_une_cassure():
    tail = [(99.3, 100.9, 99.2, 99.5)]     # mèche au-dessus de 100, clôture dessous
    df = _scenario(tail, [100])
    ev = bo.classify_level(df, 100.0, "up", atr15=1.2)
    assert ev.state in (bo.REJECTION, bo.NONE)
    assert ev.implied_direction != "LONG"


def test_sweep_de_liquidite():
    tail = [(99.3, 100.9, 99.1, 99.4), (99.4, 99.5, 98.7, 98.8)]  # mèche + volume puis clôture plus bas
    df = _scenario(tail, [400, 150])
    ev = bo.classify_level(df, 100.0, "up", atr15=1.2)
    assert ev.state == bo.SWEEP and ev.implied_direction == "SHORT"
    assert not ev.needs_close_confirmation


def test_fausse_cassure():
    tail = [(99.3, 101.0, 99.2, 100.8), (100.8, 100.9, 99.3, 99.5)]  # cassure puis réintégration
    df = _scenario(tail, [300, 200])
    ev = bo.classify_level(df, 100.0, "up", atr15=1.2)
    assert ev.state == bo.FAKE_BREAKOUT and ev.implied_direction == "SHORT"


def test_cassure_sans_volume():
    tail = [(99.3, 100.6, 99.2, 100.5)]
    df = _scenario(tail, [60])
    assert bo.classify_level(df, 100.0, "up", atr15=1.2).state == bo.NO_VOLUME


def test_mouvement_trop_etendu():
    tail = [(99.3, 101.5, 99.2, 101.4), (101.4, 103.5, 101.3, 103.4), (103.4, 104.9, 103.3, 104.8)]
    df = _scenario(tail, [300, 300, 300])
    assert bo.classify_level(df, 100.0, "up", atr15=1.2).state == bo.EXTENDED


def test_symetrie_cassure_baissiere():
    rng = [(101.0, 101.7, 100.2, 100.8), (100.8, 101.4, 100.1, 101.1), (101.1, 101.7, 100.3, 100.6),
           (100.6, 101.2, 100.05, 101.0)] * 10
    tail = [(100.7, 100.8, 98.8, 99.0), (99.0, 99.6, 98.7, 99.1), (99.1, 99.95, 99.0, 99.4), (99.4, 99.5, 98.6, 98.7)]
    df = make_df(rng + tail, volume=[100.0] * 40 + [300, 120, 90, 150])
    ev = bo.classify_level(df, 100.0, "down", atr15=1.2)
    assert ev.state == bo.CONFIRMED_RETEST and ev.implied_direction == "SHORT"
    assert ev.retest_extreme == pytest.approx(99.95)
