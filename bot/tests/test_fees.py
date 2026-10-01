from datetime import datetime, timezone

from kraken_assistant.risk.fees import XSTOCK_CHANGE, default_fees


def test_grille_kraken():
    assert default_fees("futures", "crypto", "BTC", "USD")[:2] == (0.05, 0.02)
    assert default_fees("spot", "crypto", "BTC", "USD")[:2] == (0.80, 0.40)
    assert default_fees("spot", "crypto", "USDT", "EUR")[:2] == (0.20, 0.20)
    avant = datetime(2026, 10, 4, tzinfo=timezone.utc)
    assert default_fees("spot", "xstock", "TSLAx", "USD", avant)[:2] == (0.10, 0.0)
    assert default_fees("spot", "xstock", "TSLAx", "USD", XSTOCK_CHANGE)[:2] == (0.08, 0.0)


def test_liquidation_regles_kraken():
    from kraken_assistant.risk.position_sizing import liq_fraction
    assert abs(liq_fraction(10, "futures") - 0.05) < 1e-12   # x10 : −5 % (maintenance 5 %)
    assert abs(liq_fraction(5, "futures") - 0.15) < 1e-12
    assert abs(liq_fraction(5, "spot") - 0.12) < 1e-12       # spot : 40 % de margin level
