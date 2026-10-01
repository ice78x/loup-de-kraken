import httpx
import pytest

from kraken_assistant.api.errors import AuthMissing, DataUnavailable, KrakenAPIError
from kraken_assistant.api.kraken_futures import sign_futures
from kraken_assistant.api.kraken_spot import KrakenSpotClient, sign_spot
from kraken_assistant.logging_setup import SecretRedactor
from kraken_assistant.market.instruments import Taxonomy, parse_futures_instrument, parse_spot_pair


def test_signature_spot_vecteur_officiel_kraken():
    # Vecteur publié dans la documentation Kraken (Spot REST authentication)
    sig = sign_spot("/0/private/AddOrder",
                    "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25",
                    "1616492376594",
                    "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg==")
    assert sig == "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="


def test_signature_futures_deterministe():
    a = sign_futures("/api/v3/openpositions", "", "1", "a2V5")
    assert a == sign_futures("/api/v3/openpositions", "", "1", "a2V5")
    assert a != sign_futures("/api/v3/openpositions", "", "2", "a2V5")


def test_erreur_kraken_remonte(settings):
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"error": ["EGeneral:Invalid arguments"]}))
    c = KrakenSpotClient(settings.model_copy(update={"public_min_interval_s": 0}), transport=t)
    with pytest.raises(KrakenAPIError):
        c.ticker()


def test_api_injoignable(settings):
    def boom(r):
        raise httpx.ConnectError("down")
    c = KrakenSpotClient(settings.model_copy(update={"public_min_interval_s": 0}), transport=httpx.MockTransport(boom))
    c.http.retries = 0
    with pytest.raises(DataUnavailable):
        c.server_time()


def test_prive_sans_cle(settings):
    with pytest.raises(AuthMissing):
        KrakenSpotClient(settings).balance()


def test_masquage_des_secrets():
    r = SecretRedactor(["SUPERSECRETKEY123"])
    assert "SUPERSECRETKEY123" not in r.redact("header API-Key: SUPERSECRETKEY123")
    assert "abc" not in r.redact("API-Sign=abc")


def tax(settings):
    return Taxonomy.load(settings)


def test_parse_paire_spot(settings):
    info = {"altname": "LINKEUR", "wsname": "LINK/EUR", "base": "LINK", "quote": "ZEUR", "status": "online",
            "leverage_buy": [2, 3], "leverage_sell": [2, 3], "ordermin": "0.2", "costmin": "0.5",
            "tick_size": "0.001", "lot_decimals": 8, "pair_decimals": 3}
    i = parse_spot_pair("LINKEUR", info, tax(settings), None)
    assert i.asset_class == "crypto" and i.can_short and i.max_leverage_long == 3 and i.quote == "EUR"
    assert i.allowed_leverages_long == [1, 2, 3]


def test_parse_xstock_et_matiere_premiere(settings):
    x = parse_spot_pair("TSLAxUSD", {"altname": "TSLAxUSD", "wsname": "TSLAx/USD", "base": "TSLAx", "quote": "ZUSD",
                                     "status": "online", "leverage_buy": [], "leverage_sell": []},
                        tax(settings), "tokenized_asset")
    assert x.asset_class == "xstock" and x.base == "TSLA" and not x.can_short
    g = parse_spot_pair("PAXGEUR", {"altname": "PAXGEUR", "base": "PAXG", "quote": "ZEUR", "status": "online"},
                        tax(settings), None)
    assert g.asset_class == "commodity"


def test_paire_non_tradable_ou_exclue(settings):
    assert not parse_spot_pair("X", {"base": "BTC", "quote": "ZEUR", "status": "reduce_only"}, tax(settings), None).tradable
    assert parse_spot_pair("USDTEUR", {"base": "USDT", "quote": "ZEUR", "status": "online"}, tax(settings), None) is None
    assert parse_spot_pair("BTCGBP", {"base": "XXBT", "quote": "ZGBP", "status": "online"}, tax(settings), None) is None


def test_futures_pays_interdit(settings):
    info = {"symbol": "PF_XBTUSD", "type": "flexible_futures", "base": "BTC", "quote": "USD", "tradeable": True,
            "retailMarginLevels": [{"contracts": 0, "initialMargin": 0.1, "maintenanceMargin": 0.05}],
            "contractValueTradePrecision": 4, "tickSize": 1, "countriesBanned": ["FR"]}
    i = parse_futures_instrument(info, tax(settings), "FR", 10)
    assert not i.tradable
    info["countriesBanned"] = []
    i = parse_futures_instrument(info, tax(settings), "FR", 10)
    assert i.tradable and i.max_leverage_long == 10 and i.can_short
