"""06/10 (TAO LONG) : prix dans la zone, mais le piège datait de plus d'1 h → jamais confirmé.
Avant : « il manque : retour dans la zone » (faux, le prix y était) et pré-alerte Telegram envoyée pour rien."""
from types import SimpleNamespace as NS

import pytest

from kraken_assistant.analysis import breakout as bo
from kraken_assistant.config import Settings
from kraken_assistant.strategies import rejection
from kraken_assistant.strategies.base import Setup


def _run(monkeypatch, age):
    ev = bo.LevelEvent(301.73, "down", bo.FAKE_BREAKOUT, "LONG", sweep_extreme=301.09, bars_since_signal=age)
    monkeypatch.setattr(rejection.bo, "classify_level", lambda *a, **k: ev)
    monkeypatch.setattr(rejection, "score_setup", lambda *a, **k: None)
    monkeypatch.setattr(rejection, "finalize", lambda st, a, s: st)
    lv = NS(price=301.73, touches=4, timeframe="1w", strength=1.0)
    a = NS(atr15=0.8, atr1h=2.0, price=302.2, levels=[lv], htf=NS(levels=[]), all_level_prices=[301.73, 304.0, 306.2, 308.5],
           bars=None, rvol15_last=1.0, inst=NS(key="futures:PF_TAOUSD", display="PF_TAOUSD", asset_class="crypto"))
    return [st for st in rejection.find(a, Settings(_env_file=None)) if st.direction == "LONG"][0]


def test_piege_frais_dans_la_zone_est_confirme(monkeypatch):
    st = _run(monkeypatch, age=2)
    assert st.confirmed and not st.stale


def test_piege_trop_ancien_texte_honnete_et_pas_de_pre_alerte(monkeypatch):
    st = _run(monkeypatch, age=5)
    assert not st.confirmed and st.stale
    assert "zone" not in st.trigger and "75 min" in st.trigger and "ne le validera plus" in st.trigger


@pytest.mark.parametrize("stale,attendu", [(False, True), (True, False)])
def test_finalize_pas_de_pre_alerte_si_perime(monkeypatch, stale, attendu):
    from kraken_assistant.analysis.regime import Regime
    from kraken_assistant.strategies import base, quality
    monkeypatch.setattr(base, "apply_filters", lambda st, a, s: None)
    monkeypatch.setattr(quality, "score_quality", lambda st, a, s, c: {"regime": Regime("RANGE", 0.8), "components": {},
                                                                        "score": 80.0, "btc": "neutre", "net_rr": [1.5, 2.5, 3]})
    monkeypatch.setattr(quality, "kill_switch", lambda *a, **k: [])
    a = NS(htf=NS(history_days=0), catalyst=NS(has_major=False, points={}))
    st = Setup("k", "PF_X", "crypto", "rejet_sweep", "LONG", 1, 1, 0.9, [1.1], 0.9, "", "", stale=stale)
    st = base.finalize(st, a, Settings(_env_file=None))
    assert st.presque_pret is attendu and st.status == "WATCH"
