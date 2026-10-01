"""SCAN URGENT : détection de mouvements brutaux / news majeures / liquidations probables entre deux scans,
puis re-analyse immédiate des actifs concernés (+ positions ouvertes)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..analysis.liquidity import liquidation_proxy
from ..api.errors import DataUnavailable
from ..app import App
from ..market.instruments import tradable_universe
from .scan import ScanReport, scan

log = logging.getLogger(__name__)


def detect_triggers(app: App) -> tuple[list[str], set[str]]:
    """Compare les prix actuels au dernier instantané (réel). Retourne (raisons, clés/bases à analyser)."""
    s = app.settings
    reasons: list[str] = []
    focus: set[str] = set()
    insts = tradable_universe(app.discovery.discover())
    tickers = app.prices.fetch(insts)
    snap = app.db.kv_get("watch_snapshot", {})
    now = datetime.now(timezone.utc)
    new_snap = {}
    by_key = {i.key: i for i in insts}
    for k, t in tickers.items():
        inst = by_key.get(k)
        if not inst:
            continue
        new_snap[k] = {"p": t.last, "oi": t.open_interest, "ts": now.isoformat()}
        old = snap.get(k)
        if not old or not old.get("p"):
            continue
        age_min = (now - datetime.fromisoformat(old["ts"])).total_seconds() / 60
        if age_min > 45:
            continue
        ch = (t.last / old["p"] - 1) * 100
        thr = s.urgent_move_pct_crypto if inst.asset_class == "crypto" else s.urgent_move_pct_other
        vol_ok = t.volume_24h_base * (t.vwap_24h or t.last) > 0
        if abs(ch) >= thr and vol_ok:
            reasons.append(f"mouvement brutal {inst.display} {ch:+.1f} % en {age_min:.0f} min")
            focus.add(k)
        if liq := liquidation_proxy(old.get("oi"), t.open_interest, ch):
            reasons.append(f"{inst.display}: {liq}")
            focus.add(k)
    app.db.kv_set("watch_snapshot", new_snap)
    seen = set(app.db.kv_get("urgent_news_seen", []))
    news = app.news.fetch(app.taxonomy.aliases, {i.base for i in insts}, now)
    for n in news:
        if n.verified and n.impact >= 3 and n.id not in seen and (now - n.published_at).total_seconds() < 3 * 3600:
            reasons.append(f"news majeure : {n.title} ({n.source})")
            focus.update(n.assets)
            seen.add(n.id)
    app.db.kv_set("urgent_news_seen", list(seen)[-500:])
    return reasons, focus


def urgent_scan(app: App, focus: set[str] | None = None, reasons: list[str] | None = None) -> ScanReport:
    log.warning("SCAN URGENT (%s)", "; ".join(reasons or ["manuel"]))
    rep = scan(app, mode="urgent", focus=focus or set())
    rep.no_trade_reasons = [f"déclencheur : {r}" for r in (reasons or [])] + rep.no_trade_reasons
    return rep


def watch_tick(app: App) -> ScanReport | None:
    """Appelé par le scheduler toutes les WATCH_INTERVAL_MINUTES."""
    try:
        reasons, focus = detect_triggers(app)
    except DataUnavailable as e:
        log.warning("surveillance urgente impossible : %s", e)
        return None
    if reasons:
        return urgent_scan(app, focus, reasons)
    return None
