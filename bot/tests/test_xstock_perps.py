"""Perpétuels sur actions (PF_NVDAXUSD…) : Kraken les classe en « crypto » ; le bot les range avec les xStocks."""
from datetime import datetime, timezone

from kraken_assistant.market.instruments import classify_xstock_perps, us_market_open
from kraken_assistant.market.models import Instrument


def _inst(symbol, venue, aclass, base):
    return Instrument(symbol=symbol, display=symbol, venue=venue, asset_class=aclass, kind="perpetual" if venue == "futures" else "spot",
                      base=base, quote="USD", status="online", tradable=True, can_long=True, can_short=True,
                      max_leverage_long=10, max_leverage_short=10, allowed_leverages_long=[1], allowed_leverages_short=[1],
                      ordermin=0, costmin=0)


def test_perps_actions_reconnus_grace_aux_xstocks_spot():
    insts = [_inst("NVDAxUSD", "spot", "xstock", "NVDA"), _inst("PF_NVDAXUSD", "futures", "crypto", "NVDAX"),
             _inst("PF_XBTUSD", "futures", "crypto", "BTC"), _inst("PF_IMXUSD", "futures", "crypto", "IMX")]
    assert classify_xstock_perps(insts) == 1
    assert (insts[1].asset_class, insts[1].base) == ("xstock", "NVDA")
    assert insts[2].asset_class == "crypto" and insts[3].asset_class == "crypto"   # IMX n'est pas une action (pas de xStock « IM »)


def test_horaires_bourse_us():
    assert us_market_open(datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc))        # lundi 16 h Paris
    assert not us_market_open(datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc))    # lundi 14 h Paris : pas encore ouvert
    assert not us_market_open(datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc))    # dimanche
