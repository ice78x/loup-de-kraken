"""Stratégie « Cassure de canal (Turtle) » ajoutée le 13/10 : clôture 4h hors du canal 20 bougies, stop 2 × ATR 4h."""
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

from kraken_assistant.analysis import regime as R
from kraken_assistant.analysis.regime import Regime
from kraken_assistant.config import Settings
from kraken_assistant.strategies import STRATEGIES, donchian


def _frames(last_close, prev_close=100.5, minutes_after_close=30):
    idx = pd.date_range("2026-10-01", periods=60, freq="4h", tz="UTC")
    rng = np.random.default_rng(1)
    c = 100 + rng.uniform(-0.8, 0.8, 60)
    h, l = c + 0.6, c - 0.6
    c[-2], c[-1] = prev_close, last_close
    h[-1], l[-1] = max(h[-1], last_close + 0.2), min(l[-1], last_close - 0.2)
    h4 = pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx)
    end = idx[-1] + pd.Timedelta(hours=4) + pd.Timedelta(minutes=minutes_after_close)
    f15 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
                       index=pd.date_range(end=end - pd.Timedelta(minutes=15), periods=10, freq="15min"))
    return h4, f15


def _run(monkeypatch, last_close, **kw):
    monkeypatch.setattr(donchian, "score_setup", lambda *a, **k: None)
    monkeypatch.setattr(donchian, "finalize", lambda st, a, s: st)
    h4, f15 = _frames(last_close, **kw)
    a = NS(frames={"4h": h4, "15m": f15}, price=float(h4["close"].iloc[-1]), rvol15_last=1.0,
           inst=NS(key="futures:PF_XUSD", display="PF_XUSD", asset_class="crypto"))
    return donchian.find(a, Settings(_env_file=None))


def test_cassure_fraiche_du_canal_donne_un_long(monkeypatch):
    out = _run(monkeypatch, 103.0)
    assert len(out) == 1 and out[0].direction == "LONG" and out[0].confirmed and not out[0].stale
    st = out[0]
    risk = st.entry_high - st.sl
    assert [round((tp - st.entry_high) / risk, 2) for tp in st.tps] == [1.5, 3.0, 5.0]


def test_pas_de_signal_dans_le_canal_ni_sur_une_vieille_cassure(monkeypatch):
    assert _run(monkeypatch, 100.2) == []
    assert _run(monkeypatch, 103.0, prev_close=102.5) == []      # déjà dehors à la bougie 4h précédente


def test_cassure_de_plus_d_une_heure_jamais_validee(monkeypatch):
    st = _run(monkeypatch, 103.0, minutes_after_close=90)[0]
    assert st.stale and not st.confirmed and "ne la validera plus" in st.trigger


def test_cassure_vers_le_bas_donne_un_short(monkeypatch):
    out = _run(monkeypatch, 97.0, prev_close=99.8)
    assert len(out) == 1 and out[0].direction == "SHORT" and out[0].sl > out[0].entry_high


def test_enregistree_et_autorisee_seulement_en_tendance_ou_cassure():
    assert donchian.NAME in STRATEGIES
    assert Regime(R.TREND_UP, 1).allows(donchian.NAME, "LONG") and Regime(R.BREAKOUT_DOWN, 1).allows(donchian.NAME, "SHORT")
    assert not Regime(R.RANGE, 1).allows(donchian.NAME, "LONG") and not Regime(R.TREND_UP, 1).allows(donchian.NAME, "SHORT")
