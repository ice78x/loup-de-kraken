"""Niveaux arrondis au pas de prix Kraken (ex. PUMP : pas 0,000001 ; 7 décimales refusées par Kraken pour les TP/SL)."""
from types import SimpleNamespace as NS

from kraken_assistant.config import Settings
from kraken_assistant.market.instruments import tick_decimals
from kraken_assistant.strategies.base import Setup, apply_filters, snap_to_tick


def _setup(direction, **kw):
    base = dict(inst_key="k", display="PF_PUMPUSD", asset_class="crypto", strategy="t", direction=direction,
                invalidation_text="", action="")
    return Setup(**{**base, **kw})


def _decimals_ok(x, d=6):
    return abs(round(x, d) - x) < 1e-12


def test_long_arrondi_prudent():
    st = _setup("LONG", entry_low=0.0054981, entry_high=0.0055043, sl=0.0053877, tps=[0.0056504, 0.0058119, 0.0060507],
                invalidation_price=0.0053877)
    snap_to_tick(st, 0.000001)
    assert st.entry_low == 0.005498 and st.entry_high == 0.005505      # zone élargie d'un pas au plus
    assert st.sl == 0.005387                                            # stop éloigné (jamais rapproché)
    assert st.tps == [0.00565, 0.005811, 0.00605]                       # TP rapprochés de l'entrée
    assert all(_decimals_ok(x) for x in [st.entry_low, st.entry_high, st.sl, *st.tps])


def test_short_arrondi_prudent():
    st = _setup("SHORT", entry_low=0.23896, entry_high=0.23988, sl=0.241154, tps=[0.237236, 0.233231, 0.229639],
                invalidation_price=0.2412, display="PF_WIFUSD")
    snap_to_tick(st, 0.0001)
    assert st.sl == 0.2412                                              # stop au-dessus, éloigné
    assert st.tps == [0.2373, 0.2333, 0.2297]                           # TP arrondis vers l'entrée
    assert st.entry_low == 0.2389 and st.entry_high == 0.2399


def test_valeur_deja_sur_le_pas_inchangee():
    st = _setup("LONG", entry_low=84500, entry_high=84600, sl=84000, tps=[85500, 86500, 87500], invalidation_price=84000)
    snap_to_tick(st, 1)
    assert (st.entry_low, st.entry_high, st.sl, st.tps) == (84500, 84600, 84000, [85500, 86500, 87500])


def test_apply_filters_arrondit_avec_le_pas_de_l_instrument():
    s = Settings(_env_file=None)
    a = NS(inst=NS(can_short=True, can_long=True, tick_size=0.000001), atr15=0.00002, liquidity=None,
           catalyst=NS(blocks={}, has_major=False, warnings=[]), vol=NS(regime="normal"))
    st = _setup("LONG", entry_low=0.0054981, entry_high=0.0055043, sl=0.0053877, tps=[0.0056504, 0.0058119, 0.0060507],
                invalidation_price=0.0053877)
    apply_filters(st, a, s)
    assert all(_decimals_ok(x) for x in [st.sl, *st.tps])


def test_tick_decimals():
    assert tick_decimals(0.000001) == 6
    assert tick_decimals(0.5) == 1
    assert tick_decimals(1) == 0
    assert tick_decimals(0.0001) == 4
    assert tick_decimals(0) == 8
