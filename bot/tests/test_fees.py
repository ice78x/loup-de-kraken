from datetime import datetime, timezone

from kraken_assistant.risk.fees import XSTOCK_CHANGE, default_fees


def test_grille_kraken():
    assert default_fees("futures", "crypto", "BTC", "USD")[:2] == (0.05, 0.02)
    assert default_fees("spot", "crypto", "BTC", "USD")[:2] == (0.80, 0.40)
    assert default_fees("spot", "crypto", "USDT", "EUR")[:2] == (0.20, 0.20)
    avant = datetime(2026, 10, 4, tzinfo=timezone.utc)
    assert default_fees("spot", "xstock", "TSLAx", "USD", avant)[:2] == (0.10, 0.0)
    assert default_fees("spot", "xstock", "TSLAx", "USD", XSTOCK_CHANGE)[:2] == (0.08, 0.0)
