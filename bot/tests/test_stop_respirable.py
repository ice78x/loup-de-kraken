"""Stop trop serré (ex. WIF SHORT du 02/10, stop à ~0,5 ATR 15 min) : le bot l'éloigne à 1,2 ATR, puis revérifie le R:R."""
from types import SimpleNamespace as NS

from kraken_assistant.config import Settings
from kraken_assistant.strategies.base import Setup, apply_filters


def _analyse(atr15):
    return NS(inst=NS(can_short=True, can_long=True), atr15=atr15, liquidity=None,
              catalyst=NS(blocks={}, has_major=False, warnings=[]), vol=NS(regime="normal"))


def test_stop_serre_eloigne_puis_rr_verifie():
    s = Settings(_env_file=None)
    atr = 0.0023  # ≈ 1 % du prix de WIF
    st = Setup(inst_key="k", display="WIF/USD", asset_class="crypto", strategy="cassure_retest", direction="SHORT",
               entry_low=0.23896, entry_high=0.23988, sl=0.24115, tps=[0.23723, 0.23323, 0.22963],
               invalidation_price=0.2407, invalidation_text="", action="")
    apply_filters(st, _analyse(atr), s)
    assert abs((st.sl - st.sizing_entry) - 1.2 * atr) < 1e-12          # stop à 1,2 ATR au-dessus de l'entrée
    assert any("stop éloigné" in w for w in st.warnings)
    assert any("R:R" in r for r in st.rejections)                       # avec un vrai stop, ce setup ne vaut plus le risque


def test_stop_deja_large_inchange():
    s = Settings(_env_file=None)
    st = Setup(inst_key="k", display="X", asset_class="crypto", strategy="t", direction="LONG", entry_low=99, entry_high=100,
               sl=97, tps=[104, 106, 109], invalidation_price=97, invalidation_text="", action="")
    apply_filters(st, _analyse(1.0), s)
    assert st.sl == 97
