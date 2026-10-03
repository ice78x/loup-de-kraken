"""Le club ne trade que les futures perpétuels : le bot n'analyse que les contrats PF_…"""
from types import SimpleNamespace as NS

from kraken_assistant.config import Settings
from kraken_assistant.scanner.scan import select_candidates


def _inst(key, venue, base):
    return NS(key=key, venue=venue, base=base, quote="USD", asset_class="crypto", can_short=True, account_access="inconnu")


def test_seuls_les_perpetuels_sont_analyses():
    s = Settings(_env_file=None)
    assert s.perps_only is True
    app = NS(settings=s, taxonomy=NS(quotes=["USD"]))
    insts = [_inst("spot:XBTUSD", "spot", "BTC"), _inst("futures:PF_XBTUSD", "futures", "BTC"),
             _inst("spot:PROMPTUSD", "spot", "PROMPT")]
    t = NS(volume_24h_base=1e6, vwap_24h=100.0, last=100.0, spread_pct=0.01, range_24h_pct=3.0)
    tickers = {i.key: t for i in insts}
    chosen, stats = select_candidates(app, insts, tickers, {"USD": 0.9, "EUR": 1.0}, [], set(), None, "normal")
    assert [c.key for c in chosen] == ["futures:PF_XBTUSD"]   # PROMPT (spot seulement) n'est jamais proposé
    assert stats["tradables"] == 1
