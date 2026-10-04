"""Pertes MON et WLD du 04/10 : résistance à 0,4–0,5R avant le TP1, et marché parfois sans aucun échange."""
from types import SimpleNamespace as NS

import pandas as pd

from kraken_assistant.config import Settings
from kraken_assistant.scanner.scan import REFUS_DEFINITIFS
from kraken_assistant.strategies.base import Setup, apply_filters


def _a(volumes):
    df = pd.DataFrame({"high": [1.0] * len(volumes), "low": [0.5] * len(volumes), "volume": volumes})
    return NS(inst=NS(can_short=True, can_long=True, tick_size=0), atr15=0.01, liquidity=None, frames={"15m": df},
              catalyst=NS(blocks={}, has_major=False, warnings=[]), vol=NS(regime="normal"))


def _st(**kw):
    base = dict(inst_key="k", display="PF_WLDUSD", asset_class="crypto", strategy="rejet_sweep", direction="LONG", entry_low=0.5875,
                entry_high=0.59, sl=0.5, tps=[0.77, 0.86, 0.95], invalidation_price=0.5, invalidation_text="", action="")
    return Setup(**{**base, **kw})


def test_niveau_gene_avant_tp1_pas_de_vert_mais_reste_a_surveiller():
    st = _st(warnings=["niveau gênant proche (0.5R)"])
    apply_filters(st, _a([100] * 24), Settings(_env_file=None))
    assert any("niveau gênant" in r for r in st.rejections)
    assert "cassure" in st.trigger
    assert not any(any(k in r for k in REFUS_DEFINITIFS) for r in st.rejections)   # peut redevenir valable après la cassure


def test_marche_sans_echange_refuse():
    st = _st()
    apply_filters(st, _a([100] * 20 + [0, 0, 0, 50]), Settings(_env_file=None))
    assert any("peu actif" in r for r in st.rejections)
    st2 = _st()
    apply_filters(st2, _a([100] * 23 + [0]), Settings(_env_file=None))
    assert not any("peu actif" in r for r in st2.rejections)
