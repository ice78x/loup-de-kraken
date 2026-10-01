"""News engine : collecte RSS/Atom, classification, association aux actifs, vérification.

Règles :
  - Seul ce que la source a publié est un FAIT (titre, source, heure).
  - Catégorie, impact et sens probable sont des INTERPRÉTATIONS (règles explicites, affichées comme telles).
  - Rumeur (conditionnel, "sources say"...) = jamais un fait, jamais un déclencheur.
  - Tier 1-3 = source primaire → vérifiée. Tier 4-5 → vérifiée seulement si ≥ 2 sources indépendantes.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from ..config import Settings

log = logging.getLogger(__name__)

CATEGORIES: dict[str, tuple[list[str], int, bool]] = {
    # nom: (mots-clés, impact 1-3, macro?)
    "Fed": (["fomc", "federal reserve", "powell", "federal open market", "fed chair", "fed "], 3, True),
    "BCE": (["ecb", "european central bank", "lagarde", "bce"], 3, True),
    "Inflation": (["cpi", "consumer price", "inflation", "pce", "personal consumption", "ppi", "producer price"], 3, True),
    "Emploi": (["nonfarm", "payroll", "unemployment", "jobless", "employment situation", "labor market"], 3, True),
    "Taux": (["rate cut", "rate hike", "interest rate", "basis points", "rate decision"], 3, True),
    "Géopolitique": (["war ", "sanction", "tariff", "missile", "invasion", "opec", "ceasefire", "embargo",
                      "geopolit", "military"], 3, True),
    "Régulation": (["sec ", "cftc", "regulat", "lawsuit", "court", "judge", "ruling", "settlement", "bill ",
                    "legislation", "mica", "stablecoin law", "enforcement", "charges"], 2, False),
    "ETF": ([" etf", "etfs", "spot etf"], 3, False),
    "Hack/Exploit": (["hack", "exploit", "drained", "stolen", "breach", "attacker"], 3, False),
    "Faillite": (["bankrupt", "insolven", "chapter 11", "collapse"], 3, False),
    "Liquidations": (["liquidat"], 2, False),
    "Listing": (["listing", "will list", "now available on kraken", "launches trading", "lists "], 2, False),
    "Delisting": (["delist"], 3, False),
    "Upgrade/Fork": (["upgrade", "hard fork", "mainnet", "network upgrade", " fork"], 2, False),
    "Partenariat/Institutionnel": (["partnership", "partners with", "institutional", "blackrock", "fidelity",
                                    "treasury reserve", "acquires", "acquisition"], 2, False),
    "Token unlock": (["token unlock", "unlocks", "unlock "], 2, False),
    "Gros transferts": (["whale", "large transfer", "moved $", "transferred $"], 1, False),
    "Résultats": (["earnings", "quarterly results", "revenue", "guidance", " eps", "profit warning"], 3, False),
    "Incident exchange": (["outage", "degraded", "incident", "maintenance"], 1, False),
}
BEARISH = ["hack", "exploit", "drained", "stolen", "delist", "lawsuit", "sues", "charges", "ban ", "bans ",
           "bankrupt", "outflow", "plunge", "tumble", "slump", "crash", "falls", "drops", "sell-off", "selloff",
           "rate hike", "hotter", "rejects", "denies", "denied", "misses", "warning", "halt", "tariff", "sanction"]
BULLISH = ["approv", "launch", "listing", "partnership", "inflow", "surge", "rally", "record high", "all-time high",
           "beats", "rate cut", "cooler", "eases", "adopt", "wins", "dismiss", "upgrade", "soars", "jumps"]
RUMOR = ["reportedly", "rumor", "rumour", "sources say", "according to sources", "people familiar", "could ",
         "may ", "might ", "considering", "weighs", "speculat", "unconfirmed", "plans to", "?"]
TICKER_STOP = {"THE", "FOR", "AND", "ARE", "NOT", "ALL", "NEW", "CAN", "HAS", "ONE", "TWO", "OUT", "NOW", "ANY",
               "GAS", "FUN", "WIN", "KEY", "BIG", "TOP", "CEO", "SEC", "ETF", "USD", "EUR", "API", "GDP", "CPI",
               "PCE", "FED", "ECB", "IPO", "ATH", "DAO", "NFT", "DEX", "CEX", "CFTC", "FOMC", "USA", "BIS", "IMF",
               "OPEC", "WAR", "LAW", "BAN", "AI", "US", "UK", "EU", "UP", "YEN", "PPI", "EPS", "WEF", "RWA"}


@dataclass
class NewsItem:
    id: str
    title: str
    url: str
    source: str
    tier: int
    scope: str
    published_at: datetime
    fetched_at: datetime
    summary: str = ""
    assets: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    impact: int = 0                   # 0 aucun, 1 faible, 2 moyen, 3 fort
    macro: bool = False
    direction_hint: str = "incertain"  # "haussier" | "baissier" | "incertain"
    is_rumor: bool = False
    verified: bool = False
    corroborated_by: list[str] = field(default_factory=list)

    @property
    def impact_label(self) -> str:
        return {0: "—", 1: "faible", 2: "moyen", 3: "fort"}[self.impact]

    @property
    def fact(self) -> str:
        return f"{self.source} a publié : « {self.title} »"

    @property
    def interpretation(self) -> str:
        cats = ", ".join(self.categories) or "non classée"
        who = ", ".join(self.assets) if self.assets else ("marché global (macro)" if self.macro else "aucun actif identifié")
        rum = " Formulation conditionnelle/rumeur : NON exploitable." if self.is_rumor else ""
        ver = "" if self.verified else " Non vérifiée (source unique non primaire)."
        return (f"[règles automatiques] Catégorie : {cats}. Actifs : {who}. Impact potentiel : {self.impact_label}. "
                f"Lecture : {self.direction_hint}.{rum}{ver}")

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["published_at"] = self.published_at.isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        d["impact_label"], d["fact"], d["interpretation"] = self.impact_label, self.fact, self.interpretation
        return d


_TAG_RE = re.compile(r"<[^>]+>")


def _text(el: ET.Element | None) -> str:
    return html.unescape(_TAG_RE.sub("", (el.text or "") if el is not None else "")).strip()


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, source: dict, fetched_at: datetime) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    out: list[NewsItem] = []
    atom = "{http://www.w3.org/2005/Atom}"
    items = root.findall(".//item")
    is_atom = not items
    if is_atom:
        items = root.findall(f".//{atom}entry")
    for it in items:
        if is_atom:
            title = _text(it.find(f"{atom}title"))
            link_el = it.find(f"{atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            date = _parse_date(_text(it.find(f"{atom}published")) or _text(it.find(f"{atom}updated")))
            summary = _text(it.find(f"{atom}summary"))
        else:
            title = _text(it.find("title"))
            link = _text(it.find("link"))
            date = _parse_date(_text(it.find("pubDate")) or _text(it.find("{http://purl.org/dc/elements/1.1/}date")))
            summary = _text(it.find("description"))[:400]
        if not title or date is None:
            continue  # sans heure de publication, une news n'est pas exploitable
        nid = hashlib.sha1(f"{source['name']}|{title}|{link}".encode()).hexdigest()[:16]
        out.append(NewsItem(nid, title, link, source["name"], int(source["tier"]), source.get("scope", ""),
                            date.astimezone(timezone.utc), fetched_at, summary))
    return out


def classify(item: NewsItem, aliases: dict[str, str], tickers: set[str]) -> NewsItem:
    low = f" {item.title.lower()} "
    body = f"{low} {item.summary.lower()[:300]} "
    cats, impact, macro = [], 0, False
    for name, (kws, imp, is_macro) in CATEGORIES.items():
        if any(k in low for k in kws):
            cats.append(name)
            impact = max(impact, imp)
            macro = macro or is_macro
    assets: list[str] = []
    for alias, tk in aliases.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low):
            assets.append(tk)
    for w in re.findall(r"\$?\b[A-Z][A-Z0-9]{2,9}\b", item.title):
        t = w.lstrip("$")
        if t in tickers and (t not in TICKER_STOP or w.startswith("$")):
            assets.append(t)
    item.assets = sorted(set(assets))
    item.categories, item.impact, item.macro = cats, impact, macro
    if item.scope == "macro" and not cats:
        item.macro, item.impact = True, 1
    b = sum(k in body for k in BEARISH)
    u = sum(k in body for k in BULLISH)
    item.direction_hint = "baissier" if b > u else "haussier" if u > b else "incertain"
    item.is_rumor = any(k in low for k in RUMOR)
    item.verified = item.tier <= 3 and not item.is_rumor
    return item


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", t.lower())}


def corroborate(items: list[NewsItem], window_h: float = 12.0, min_sim: float = 0.3) -> None:
    """Une news tier 4-5 devient vérifiée si une autre source indépendante rapporte la même chose."""
    for a in items:
        if a.verified or a.is_rumor:
            continue
        ta = _tokens(a.title)
        for b in items:
            if b.source == a.source or b.is_rumor:
                continue
            if abs((a.published_at - b.published_at).total_seconds()) > window_h * 3600:
                continue
            tb = _tokens(b.title)
            sim = len(ta & tb) / max(1, len(ta | tb))
            same_subject = bool(set(a.assets) & set(b.assets)) or (a.macro and b.macro and set(a.categories) & set(b.categories))
            if sim >= min_sim or (same_subject and sim >= 0.2):
                a.corroborated_by.append(b.source)
        a.corroborated_by = sorted(set(a.corroborated_by))
        if a.corroborated_by:
            a.verified = True


class NewsEngine:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.sources = settings.load_toml("news_sources.toml").get("source", [])
        self.source_status: dict[str, str] = {}
        self.transport = transport

    def _fetch_one(self, src: dict, now: datetime) -> list[NewsItem]:
        try:
            with httpx.Client(timeout=10, headers={"User-Agent": self.s.user_agent}, follow_redirects=True,
                              transport=self.transport) as c:
                r = c.get(src["url"])
            if r.status_code >= 400:
                self.source_status[src["name"]] = f"HTTP {r.status_code}"
                return []
            items = parse_feed(r.text, src, now)
            self.source_status[src["name"]] = f"OK ({len(items)})"
            return items
        except (httpx.HTTPError, ET.ParseError) as e:
            self.source_status[src["name"]] = f"échec ({type(e).__name__})"
            return []

    def fetch(self, aliases: dict[str, str], tickers: set[str], now: datetime | None = None) -> list[NewsItem]:
        now = now or datetime.now(timezone.utc)
        if not self.s.news_enabled:
            return []
        with ThreadPoolExecutor(max_workers=6) as ex:
            batches = list(ex.map(lambda s: self._fetch_one(s, now), self.sources))
        items = [i for b in batches for i in b]
        items += self._finnhub_earnings(now)
        cutoff = now - timedelta(hours=self.s.news_max_age_hours)
        items = [i if i.scope == "calendar" else classify(i, aliases, tickers) for i in items
                 if i.scope == "calendar" or cutoff <= i.published_at <= now + timedelta(minutes=5)]
        items = [i for i in items if i.scope != "calendar" or set(i.assets) & tickers]
        seen, uniq = set(), []
        for i in sorted(items, key=lambda x: x.published_at, reverse=True):
            key = (i.source, i.title.lower())
            if key not in seen:
                seen.add(key)
                uniq.append(i)
        corroborate(uniq)
        ok = sum(v.startswith("OK") for v in self.source_status.values())
        log.info("news=%d (sources OK %d/%d)", len(uniq), ok, len(self.source_status))
        return uniq

    def _finnhub_earnings(self, now: datetime) -> list[NewsItem]:
        key = self.s.finnhub_api_key.get_secret_value()
        if not key:
            return []
        try:
            with httpx.Client(timeout=10, transport=self.transport) as c:
                r = c.get("https://finnhub.io/api/v1/calendar/earnings",
                          params={"from": now.date().isoformat(), "to": (now + timedelta(days=2)).date().isoformat(),
                                  "token": key})
            data = r.json().get("earningsCalendar", []) if r.status_code == 200 else []
            self.source_status["Finnhub earnings"] = f"OK ({len(data)})" if r.status_code == 200 else f"HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            self.source_status["Finnhub earnings"] = f"échec ({type(e).__name__})"
            return []
        out = []
        for e in data:
            sym = str(e.get("symbol", "")).upper()
            title = f"Résultats {sym} prévus le {e.get('date')} ({e.get('hour') or 'heure n.c.'})"
            out.append(NewsItem(hashlib.sha1(title.encode()).hexdigest()[:16], title, "", "Finnhub (calendrier)", 3,
                                "calendar", now, now, assets=[sym], categories=["Résultats"], impact=3,
                                verified=True))
        return out
