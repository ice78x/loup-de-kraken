"""Trades du 03/10 (15:19) rejoués avec les vraies bougies 15 min Kraken :
ETH SHORT stop 2683,9 posé SOUS le haut du range (2686,8) → chassé à 2684,1 ; NEAR LONG stop 4,6427 posé AU-DESSUS du bas récent (4,6369)."""
from types import SimpleNamespace as NS

import pandas as pd

from kraken_assistant.config import Settings
from kraken_assistant.strategies.base import Setup, apply_filters

# 16 bougies 15 min (12:30 → 16:15 heure de Paris), [high, low]
ETH = [(2684.4, 2681.2), (2681.6, 2679.6), (2682.1, 2679.2), (2682.6, 2679.0), (2683.7, 2681.7), (2684.5, 2681.5), (2683.7, 2681.1),
       (2683.1, 2681.1), (2685.7, 2683.1), (2685.7, 2683.9), (2684.4, 2682.2), (2686.8, 2682.3), (2683.1, 2679.3), (2682.9, 2680.5),
       (2682.2, 2679.5), (2680.5, 2676.5)]
NEAR = [(4.663, 4.6484), (4.6846, 4.6608), (4.7227, 4.6751), (4.7166, 4.6829), (4.7094, 4.6943), (4.7125, 4.6977), (4.698, 4.6847),
        (4.6905, 4.68), (4.7134, 4.6817), (4.6895, 4.6693), (4.6809, 4.66), (4.6689, 4.64), (4.6568, 4.6442), (4.674, 4.6369),
        (4.6795, 4.6529), (4.6586, 4.6476)]


def _analyse(bars, atr):
    df = pd.DataFrame({"high": [h for h, _ in bars], "low": [lo for _, lo in bars]})
    return NS(inst=NS(can_short=True, can_long=True, tick_size=0), atr15=atr, liquidity=None, frames={"15m": df},
              catalyst=NS(blocks={}, has_major=False, warnings=[]), vol=NS(regime="normal"))


def test_eth_short_stop_au_dessus_du_range_puis_refus():
    st = Setup(inst_key="k", display="PF_ETHUSD", asset_class="crypto", strategy="t", direction="SHORT",
               entry_low=2680.3, entry_high=2680.3, sl=2683.9, tps=[2675.6, 2672.4, 2668.8],
               invalidation_price=2683.9, invalidation_text="", action="")
    apply_filters(st, _analyse(ETH, 3.3), Settings(_env_file=None))
    assert st.sl > 2686.8                                  # au-delà du haut du range : la mèche à 2684,1 ne l'aurait pas touché
    assert any("R:R" in r for r in st.rejections)          # avec un vrai stop, le gain visé ne vaut plus le risque → pas de trade


def test_near_long_stop_sous_le_bas_recent():
    st = Setup(inst_key="k", display="PF_NEARUSD", asset_class="crypto", strategy="t", direction="LONG",
               entry_low=4.6801, entry_high=4.6889, sl=4.6427, tps=[4.75, 4.80, 4.86],
               invalidation_price=4.6427, invalidation_text="", action="")
    apply_filters(st, _analyse(NEAR, 0.02), Settings(_env_file=None))
    assert st.sl < 4.6369
    assert any("plus bas des 4 dernières heures" in w for w in st.warnings)


def test_stop_minimum_en_pourcentage():
    st = Setup(inst_key="k", display="X", asset_class="crypto", strategy="t", direction="LONG", entry_low=100, entry_high=100,
               sl=99.9, tps=[101, 102, 103], invalidation_price=99.9, invalidation_text="", action="")
    apply_filters(st, NS(inst=NS(can_short=True, can_long=True), atr15=0.05, liquidity=None,
                         catalyst=NS(blocks={}, has_major=False, warnings=[]), vol=NS(regime="normal")), Settings(_env_file=None))
    assert abs(st.sl - 99.65) < 1e-9                       # 0,35 % minimum
