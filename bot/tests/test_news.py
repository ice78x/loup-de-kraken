from datetime import datetime, timedelta, timezone

from kraken_assistant.analysis.catalysts import catalyst_for
from kraken_assistant.news.engine import NewsItem, classify, corroborate, parse_feed

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
ALIASES = {"chainlink": "LINK", "bitcoin": "BTC", "tesla": "TSLA"}
TICKERS = {"LINK", "BTC", "TSLA", "ETH"}

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Test headline about Chainlink exploit</title><link>https://example.org/a</link>
<pubDate>Wed, 30 Sep 2026 11:00:00 GMT</pubDate><description>x</description></item>
<item><title>No date item</title><link>https://example.org/b</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom title</title>
<link href="https://example.org/c"/><updated>2026-09-30T10:00:00Z</updated></entry></feed>"""


def item(title, source="S", tier=5, minutes_ago=30, scope="crypto"):
    return NewsItem("id" + title[:5] + source, title, "", source, tier, scope, NOW - timedelta(minutes=minutes_ago), NOW)


def test_parse_rss_et_atom_sans_inventer_de_date():
    items = parse_feed(RSS, {"name": "Src", "tier": 5}, NOW)
    assert len(items) == 1                         # l'item sans date est ignoré, pas daté arbitrairement
    assert items[0].published_at == datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc)
    a = parse_feed(ATOM, {"name": "A", "tier": 1}, NOW)
    assert a[0].url == "https://example.org/c"


def test_classification_et_lecture():
    n = classify(item("Chainlink protocol hit by exploit, funds drained"), ALIASES, TICKERS)
    assert n.assets == ["LINK"] and "Hack/Exploit" in n.categories and n.impact == 3
    assert n.direction_hint == "baissier"
    assert not n.verified                          # tier 5, source unique


def test_rumeur_jamais_verifiee():
    n = classify(item("SEC reportedly could approve new ETF", tier=2, scope="regulation"), ALIASES, TICKERS)
    assert n.is_rumor and not n.verified


def test_source_officielle_verifiee():
    n = classify(item("Federal Reserve issues FOMC statement", "Federal Reserve", 1, scope="macro"), ALIASES, TICKERS)
    assert n.verified and n.macro and n.impact == 3


def test_corroboration_deux_sources():
    a = classify(item("Bitcoin ETF records massive inflows this week", "CoinDesk"), ALIASES, TICKERS)
    b = classify(item("Bitcoin ETF sees massive inflows this week", "The Block"), ALIASES, TICKERS)
    corroborate([a, b])
    assert a.verified and b.verified and "The Block" in a.corroborated_by


def test_catalyseur_news_non_verifiee_ignoree():
    n = classify(item("Chainlink exploit drained funds"), ALIASES, TICKERS)
    ctx = catalyst_for("LINK", "crypto", [n], NOW)
    assert ctx.used == [] and ctx.ignored and ctx.points == {"LONG": 0.0, "SHORT": 0.0}


def test_catalyseur_verifie_oriente():
    n = classify(item("Chainlink exploit drained funds", "Chainlink Labs", 3), ALIASES, TICKERS)
    ctx = catalyst_for("LINK", "crypto", [n], NOW)
    assert ctx.points["SHORT"] > 0 > ctx.points["LONG"]


def test_ticker_courant_ignore():
    n = classify(item("THE market is NEW today"), ALIASES, TICKERS | {"THE", "NEW"})
    assert n.assets == []
