"""scan() — pipeline complet :

 1 instruments  2 prix  3 OHLCV  4 volumes  5 positions  6 news  7 catalyseurs  8 analyse marchés
 9 filtrage des setups  10 calcul du risque  11 risque cumulé  12 trades valides  13 niveaux à surveiller

Une donnée critique absente → "DATA INSUFFISANTE — PAS DE TRADE". Rien n'est inventé.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..analysis.catalysts import catalyst_for
from ..analysis.correlation import correlation
from ..analysis.liquidity import check_book, liquidity_report
from ..analysis.market_analysis import MarketAnalysis, analyze_market
from ..api.errors import DataUnavailable
from ..app import App
from ..database.db import utcnow
from ..market.instruments import us_market_open, tradable_universe
from ..market.models import Instrument, Ticker
from ..market.prices import eur_per_quote
from ..news.engine import NewsItem
from ..portfolio.management import Advice, advise
from ..risk.daily_loss import realized_pnl_today
from ..risk.portfolio_risk import RiskSnapshot
from ..risk.position_sizing import PositionPlan, SizingInput, compute_position
from ..strategies import STRATEGIES
from ..backtest.optimizer import ADOPTED, DISABLED, load_edges
from ..strategies.base import ACTION_ENTER, TRADE, WATCH, Setup

log = logging.getLogger(__name__)


@dataclass
class Signal:
    setup: Setup
    plan: PositionPlan
    risk_pct: float
    fee_pct: float
    fee_source: str
    catalyst_label: str
    news: list[NewsItem]
    warnings: list[str]
    inst: Instrument
    signal_id: int | None = None
    maker_fee_pct: float | None = None


@dataclass
class ScanReport:
    ts: datetime
    mode: str
    verdict: str                          # TRADE | WATCH | NONE | DATA
    trades: list[Signal] = field(default_factory=list)
    watch: list[Setup] = field(default_factory=list)
    no_trade_reasons: list[str] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    advice: list[Advice] = field(default_factory=list)
    risk: RiskSnapshot | None = None
    capital: dict = field(default_factory=dict)
    opportunities: list[dict] = field(default_factory=list)
    data_issues: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    duration_s: float = 0.0
    paper_events: list[str] = field(default_factory=list)
    scan_id: int | None = None
    # objets internes (non sérialisés) utiles aux intégrations (site web)
    analyses: dict = field(default_factory=dict, repr=False)
    fx: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        def sig(x: Signal) -> dict:
            return {"signal_id": x.signal_id, "setup": setup_dict(x.setup), "plan": x.plan.to_dict(),
                    "risk_pct": x.risk_pct, "fee_pct": x.fee_pct, "fee_source": x.fee_source,
                    "catalyst": x.catalyst_label, "news": [n.to_dict() for n in x.news], "warnings": x.warnings}
        return {"ts": self.ts.isoformat(), "mode": self.mode, "verdict": self.verdict,
                "trades": [sig(t) for t in self.trades], "watch": [setup_dict(w) for w in self.watch],
                "no_trade_reasons": self.no_trade_reasons, "news": [n.to_dict() for n in self.news],
                "advice": [a.__dict__ for a in self.advice],
                "risk": self.risk.__dict__ | {"positions": [p.__dict__ for p in self.risk.positions]} if self.risk else None,
                "capital": self.capital, "opportunities": self.opportunities, "data_issues": self.data_issues,
                "counts": self.counts, "duration_s": self.duration_s, "paper_events": self.paper_events,
                "scan_id": self.scan_id}


def setup_dict(s: Setup) -> dict:
    d = {k: v for k, v in s.__dict__.items() if k != "event"}
    d["event"] = s.event.describe() if s.event else None
    d["r_multiples"] = s.r_multiples()
    return d


# ---------------------------------------------------------------- univers
def _vol_eur(t: Ticker, epq: float) -> float:
    return t.volume_24h_base * (t.vwap_24h or t.last) * epq


def select_candidates(app: App, insts: list[Instrument], tickers: dict[str, Ticker], fx: dict[str, float],
                      news: list[NewsItem], position_keys: set[str], focus: set[str] | None,
                      mode: str) -> tuple[list[Instrument], dict]:
    s = app.settings
    if mode == "cible" and focus:  # vérification express d'un seul setup (bouton « Vérifier maintenant » du site)
        chosen = [i for i in insts if i.key in focus]
        return chosen, {"tradables": len(insts), "candidats": len(chosen)}
    if s.perps_only:  # le club ne trade que les perpétuels : on n'analyse que les contrats PF_…
        insts = [i for i in insts if i.venue == "futures"]
    # Actions (xStocks) : seulement quand la bourse américaine est ouverte — sinon le prix est plat et trompeur.
    if s.xstocks_us_hours_only and not us_market_open():
        insts = [i for i in insts if i.asset_class != "xstock"]
    fut_verified = s.perps_only or any(i.venue == "futures" and i.account_access == "vérifié" for i in insts)
    stats = {"tradables": len(insts), "avec_ticker": 0, "liquides": 0}
    best: dict[tuple[str, str], tuple[float, Instrument, float]] = {}
    for i in insts:
        t = tickers.get(i.key)
        if not t or i.quote not in fx:
            continue
        stats["avec_ticker"] += 1
        v = _vol_eur(t, fx[i.quote])
        min_v = s.min_volume_24h_eur_crypto if i.asset_class == "crypto" else s.min_volume_24h_eur_other
        sp = t.spread_pct
        if v < min_v or sp is None or sp > s.max_spread_pct:
            continue
        stats["liquides"] += 1
        pref = 0.0
        if i.venue == "futures":
            pref = 3.0 if fut_verified else -3.0
        elif i.quote in app.taxonomy.quotes:
            pref = 1.0 - 0.5 * app.taxonomy.quotes.index(i.quote)
        pref += 1.0 if i.can_short else 0.0
        activity = math.log10(max(v, 1)) + min(t.range_24h_pct, 15) / 3
        k = (i.base, i.asset_class)
        cand = (pref, i, activity)
        if k not in best or (pref, v) > (best[k][0], _vol_eur(tickers[best[k][1].key], fx[best[k][1].quote])):
            best[k] = cand
    pool = [(act, inst) for _, inst, act in best.values()]
    by_class: dict[str, list] = {"crypto": [], "xstock": [], "commodity": []}
    for act, inst in pool:
        by_class.setdefault(inst.asset_class, []).append((act, inst))
    limits = {"crypto": s.universe_max_crypto, "xstock": s.universe_max_xstocks, "commodity": s.universe_max_commodities}
    if mode == "urgent":
        limits = {k: max(3, v // 3) for k, v in limits.items()}
    chosen: dict[str, Instrument] = {}
    for cls, items in by_class.items():
        for _, inst in sorted(items, key=lambda x: -x[0])[: limits.get(cls, 5)]:
            chosen[inst.key] = inst
    # Toujours inclure : positions ouvertes, actifs avec news vérifiée, focus urgent
    news_bases = {a for n in news if n.verified and n.impact >= 2 for a in n.assets}
    for _, inst in pool:
        if inst.key in position_keys or inst.base in news_bases or (focus and (inst.key in focus or inst.base in focus)):
            chosen[inst.key] = inst
    all_by_key = {i.key: i for i in insts}
    for k in position_keys:
        if k in all_by_key:
            chosen.setdefault(k, all_by_key[k])
    stats["candidats"] = len(chosen)
    return list(chosen.values()), stats


# ---------------------------------------------------------------- scan
def scan(app: App, mode: str = "normal", focus: set[str] | None = None) -> ScanReport:
    if not app.scan_lock.acquire(blocking=False):
        raise RuntimeError("un scan est déjà en cours — réessaie dans une minute")
    try:
        return _scan(app, mode, focus)
    finally:
        app.scan_lock.release()


def _scan(app: App, mode: str, focus: set[str] | None) -> ScanReport:
    s = app.settings
    t0 = time.time()
    now = datetime.now(timezone.utc)
    rep = ScanReport(now, mode, "NONE")
    log.info("SCAN START mode=%s", mode)

    # 1. instruments ------------------------------------------------------------
    try:
        all_insts = app.discovery.discover()
    except DataUnavailable as e:
        return _abort(app, rep, f"instruments Kraken indisponibles ({e})", t0)
    rep.data_issues += app.discovery.warnings
    insts = tradable_universe(all_insts)
    log.info("instruments=%d tradables=%d", len(all_insts), len(insts))

    # 2. prix -------------------------------------------------------------------
    try:
        tickers = app.prices.fetch(insts)
    except DataUnavailable as e:
        return _abort(app, rep, f"prix Kraken indisponibles ({e})", t0)
    rep.data_issues += app.prices.warnings
    fx: dict[str, float] = {"EUR": 1.0}
    try:
        fx["USD"] = eur_per_quote("USD", all_insts, tickers)
    except DataUnavailable as e:
        rep.data_issues.append(f"{e} — instruments en USD exclus")

    # 5. positions + capital ------------------------------------------------------
    try:
        if s.has_spot_keys or s.has_futures_keys:
            app.kraken_sync.sync(all_insts, tickers)
            rep.data_issues += app.kraken_sync.warnings
        rep.capital = app.capital()
    except DataUnavailable as e:
        return _abort(app, rep, str(e), t0)
    capital = rep.capital["risk_capital_eur"]
    if capital <= 0:
        return _abort(app, rep, "capital nul ou négatif", t0)

    # 6-7. news ------------------------------------------------------------------
    tickers_set = {i.base for i in insts}
    news = app.news.fetch(app.taxonomy.aliases, tickers_set, now)
    if s.news_enabled and not any(v.startswith("OK") for v in app.news.source_status.values()):
        rep.data_issues.append("données news absentes (aucune source joignable) — analyse technique uniquement, "
                               "catalyseurs non évalués")
    rep.news = [n for n in news if n.impact >= 2][:15]
    for n in news[:200]:
        app.db.execute("INSERT OR IGNORE INTO news(id,title,url,source,tier,published_at,fetched_at,payload) "
                       "VALUES(?,?,?,?,?,?,?,?)", (n.id, n.title, n.url, n.source, n.tier, n.published_at.isoformat(),
                                                   n.fetched_at.isoformat(), json.dumps(n.to_dict(), default=str)))
    log.info("news=%d (impact>=2: %d)", len(news), len(rep.news))

    # univers
    open_pos = app.positions.open_positions(include_pending=True)
    pos_keys = {p.instrument_key for p in open_pos}
    candidates, stats = select_candidates(app, insts, tickers, fx, news, pos_keys, focus, mode)
    log.info("candidates=%d (liquides=%d)", len(candidates), stats.get("liquides", 0))

    # 3-4. OHLCV + analyse -----------------------------------------------------------
    analyses: dict[str, MarketAnalysis] = {}
    frames_by_key: dict[str, dict] = {}
    setups: list[Setup] = []
    for inst in candidates:
        t = tickers.get(inst.key)
        if inst.quote not in fx or not t:
            rep.data_issues.append(f"{inst.display}: prix/devise indisponible")
            continue
        try:
            frames = app.candles.frames(inst)
        except DataUnavailable as e:
            rep.data_issues.append(f"{inst.display}: DATA INSUFFISANTE ({e})")
            continue
        frames_by_key[inst.key] = frames
        min_v = s.min_volume_24h_eur_crypto if inst.asset_class == "crypto" else s.min_volume_24h_eur_other
        liq = liquidity_report(t, fx[inst.quote], min_v, s.max_spread_pct, inst.venue == "futures")
        cat = catalyst_for(inst.base, inst.asset_class, news, now)
        try:
            a = analyze_market(inst, frames, t.last, liq, cat, t)
        except (ValueError, IndexError, KeyError) as e:
            rep.data_issues.append(f"{inst.display}: analyse impossible ({type(e).__name__})")
            continue
        analyses[inst.key] = a
        for name, fn in STRATEGIES.items():
            if name in s.disabled_strategies:
                continue
            try:
                setups += fn(a, s)
            except (ValueError, IndexError, KeyError, ZeroDivisionError) as e:
                log.warning("stratégie %s échouée sur %s: %s", name, inst.display, e)
    rep.counts = {**stats, "analysés": len(analyses), "setups": len(setups)}
    rep.analyses, rep.fx = analyses, fx
    if s.use_optimized_params:
        apply_edges(setups, load_edges(app.db), s)
    apply_live_edges(setups, s)

    # 5 bis. positions : paper update + conseils de gestion ------------------------------
    for p in open_pos:
        frames = frames_by_key.get(p.instrument_key)
        inst = next((i for i in all_insts if i.key == p.instrument_key), None)
        if frames is None and inst is not None:
            try:
                frames = app.candles.frames(inst)
                frames_by_key[p.instrument_key] = frames
            except DataUnavailable as e:
                rep.data_issues.append(f"position {p.display}: bougies indisponibles ({e})")
        t = tickers.get(p.instrument_key)
        price = t.last if t else None
        if p.source == "paper" and frames is not None:
            rep.paper_events += app.paper.update(p.id, frames["5m"], frames, price, now)
            p = app.positions.get(p.id)
        if p and p.status == "open":
            rep.advice.append(advise(p, frames, price, s.tp_split))
    open_pos = app.positions.open_positions()

    # 10-11. risque ------------------------------------------------------------
    realized = realized_pnl_today(app.db, s.timezone, now)
    snap = app.risk.snapshot(capital, open_pos, realized)
    rep.risk = snap

    trades_ts = sorted([x for x in setups if x.status == TRADE], key=lambda x: (-x.score, x.display))
    accepted: list[Signal] = []
    extra_risk = 0.0
    seen_inst: set[str] = set()
    for st in trades_ts:
        if len(accepted) >= s.max_signals_per_scan:
            st.status, st.trigger = WATCH, st.trigger or "limite de signaux par scan atteinte"
            continue
        if st.inst_key in seen_inst:
            st.status = WATCH
            st.rejections.append("autre setup déjà retenu sur cet instrument")
            continue
        a = analyses[st.inst_key]
        inst = a.inst
        if inst.venue == "futures" and inst.account_access != "vérifié" and not s.perps_only:
            st.status = WATCH
            st.rejections.append("compte futures non vérifié (ajoute une clé API futures en lecture)")
            continue
        opposite = [o for o in setups if o.inst_key == st.inst_key and o.direction != st.direction and o.confirmed
                    and not o.rejections]
        if opposite:
            st.status = WATCH
            st.rejections.append("signaux contradictoires sur le même actif — marché incertain")
            continue
        tmp = RiskSnapshot(**{**snap.__dict__, "open_risk_eur": snap.open_risk_eur + extra_risk,
                              "available_risk_eur": max(0.0, snap.available_risk_eur - extra_risk)})
        dec = app.risk.allowed_risk_pct(tmp, st.exceptional)
        if not dec.ok:
            st.status = WATCH
            st.rejections += dec.reasons
            continue
        corrs: dict[int, float] = {}
        for pr in snap.positions:
            pos = next((p for p in open_pos if p.id == pr.position_id), None)
            f = frames_by_key.get(pos.instrument_key) if pos else None
            if f is not None:
                c = correlation(a.frames["1h"], f["1h"])
                if c is not None:
                    corrs[pr.position_id] = c
        cdec = app.risk.check_candidate(tmp, inst.base, st.direction, corrs)
        for other in accepted:
            c = correlation(a.frames["1h"], analyses[other.setup.inst_key].frames["1h"])
            if c is not None and abs(c) >= s.correlation_block:
                cdec.ok = False
                cdec.reasons.append(f"trop corrélé au signal {other.setup.display} (corr {c:+.2f})")
        if not cdec.ok:
            st.status = WATCH
            st.rejections += cdec.reasons
            continue
        fee, maker, fee_src = app.fee_for(inst)
        allowed_lev = inst.allowed_leverages_long if st.direction == "LONG" else inst.allowed_leverages_short
        plan = compute_position(SizingInput(
            capital_eur=capital, risk_percent=dec.risk_pct, entry=st.sizing_entry, stop_loss=st.sl,
            direction=st.direction, take_profits=st.tps, tp_split=s.tp_split, fee_rate_pct=fee,
            maker_fee_pct=maker, entry_is_maker=st.action != ACTION_ENTER,
            eur_per_quote=fx[inst.quote], ordermin=inst.ordermin, costmin=inst.costmin,
            lot_decimals=inst.lot_decimals, allowed_leverages=allowed_lev, max_leverage=s.max_leverage,
            available_margin_eur=capital, venue=inst.venue))
        if not plan.ok:
            st.status = WATCH
            st.rejections += plan.errors
            continue
        net2 = plan.r_multiples_net[1] if len(plan.r_multiples_net) > 1 else 0.0
        if net2 < s.min_net_rr_tp2:
            st.status = WATCH
            st.rejections.append(f"rendement net de frais insuffisant (TP2 = {net2:.1f}R net)")
            continue
        if plan.fees_at_sl_eur / max(plan.estimated_loss_at_sl_eur, 1e-9) > s.max_fee_share_of_risk:
            st.status = WATCH
            st.rejections.append("frais trop élevés par rapport à la distance du SL")
            continue
        try:
            book = app.books.stats(inst)
            check_book(a.liquidity, book, plan.notional_quote, s.max_spread_pct)
            if not a.liquidity.ok:
                st.status = WATCH
                st.rejections += a.liquidity.issues
                continue
        except DataUnavailable as e:
            st.status = WATCH
            st.rejections.append(f"carnet d'ordres indisponible ({e}) — liquidité non vérifiable")
            continue
        warns = st.warnings + dec.warnings + cdec.warnings + plan.warnings
        if inst.account_access != "vérifié":
            warns.append("accès compte non vérifié par API (pas de clé) — vérifie que l'actif est tradable sur ton compte")
        if fee_src.startswith("défaut"):
            warns.append(f"frais estimés {maker:.2f} % maker / {fee:.2f} % taker (défaut, pas ceux de ton compte)")
        sig = Signal(st, plan, dec.risk_pct, fee, fee_src, a.catalyst.label(), a.catalyst.used[:2], warns, inst,
                     maker_fee_pct=maker)
        sig.signal_id = _journal(app, sig, TRADE)
        accepted.append(sig)
        seen_inst.add(st.inst_key)
        extra_risk += plan.estimated_loss_at_sl_eur
    rep.trades = accepted

    # 13. niveaux à surveiller -----------------------------------------------------
    # Un 🟡 doit pouvoir devenir un 🟢 avec la confirmation. Un setup refusé pour une raison qui ne changera pas
    # (gain trop faible pour le risque, stop trop serré, liquidité, stratégie bloquée…) n'est pas publié.
    watch = [x for x in setups if x.status == WATCH and x.score >= s.score_watch
             and not any(any(k in r for k in REFUS_DEFINITIFS) for r in x.rejections)]
    best_w: dict[str, Setup] = {}
    for w in sorted(watch, key=lambda x: -x.score):
        if w.inst_key not in best_w and w.inst_key not in seen_inst:
            best_w[w.inst_key] = w
    rep.watch = list(best_w.values())[:6]
    for w in rep.watch:
        _journal_watch(app, w)

    # Opportunités (tableau de bord)
    for key, a in analyses.items():
        best = max((x for x in setups if x.inst_key == key), key=lambda x: (x.status == TRADE, x.score), default=None)
        if best and best.status == TRADE and key in seen_inst:
            state = best.direction
        elif best and best.score >= s.score_watch:
            state = f"SURVEILLER {best.direction}"
        else:
            state = "WAIT"
        rep.opportunities.append({"key": key, "display": a.inst.display, "asset_class": a.inst.asset_class,
                                  "state": state, "score": best.score if best else None,
                                  "price": a.price, **a.summary()})
    rep.opportunities.sort(key=lambda o: (o["state"] == "WAIT", -(o["score"] or 0)))

    # Verdict
    if rep.trades:
        rep.verdict = TRADE
    else:
        rep.no_trade_reasons = _why_no_trade(rep, setups, snap)
        rep.verdict = WATCH if rep.watch else "NONE"
    if not analyses:
        rep.verdict = "DATA"
        rep.no_trade_reasons = ["DATA INSUFFISANTE — aucun marché n'a pu être analysé"] + rep.no_trade_reasons
    rep.duration_s = round(time.time() - t0, 1)
    rep.counts.update(valid_setups=len(rep.trades), watch=len(rep.watch))
    log.info("valid_setups=%d watch=%d risk_check=%s duration=%.1fs", len(rep.trades), len(rep.watch),
             "PASS" if not snap.daily_limit_hit else "STOP_DAILY_LOSS", rep.duration_s)
    _save(app, rep)
    return rep


def apply_edges(setups: list[Setup], edges: dict, s) -> None:
    """Applique les réglages issus de l'historique (optimiseur walk-forward) à chaque setup."""
    for st in setups:
        e = edges.get((st.asset_class, st.strategy))
        if not e:
            st.edge_note = "historique : pas encore optimisé (commande OPTIMISER)"
            continue
        st.edge_note = e.note()
        if e.status == DISABLED:
            st.rejections.append(f"stratégie {st.strategy} désactivée sur {st.asset_class} "
                                 f"(historique hors échantillon négatif : {e.oos_expectancy:+.2f}R)")
            st.status = WATCH
        elif e.status == ADOPTED and st.confirmed and not st.rejections:
            rs = st.r_multiples()
            if len(rs) > 1 and rs[1] < e.min_rr_tp2:
                st.rejections.append(f"R:R TP2 {rs[1]:.1f} < minimum optimisé {e.min_rr_tp2:.1f}")
                st.status = WATCH
            else:
                st.status = TRADE if st.score >= e.score_threshold else WATCH


REFUS_DEFINITIFS = ("impossible", "R:R", "SL trop serré", "désactivée", "perd en vrai", "trop étendu", "volatilité extrême",
                    "liquidité", "spread", "profondeur", "delisting", "peu actif")


def apply_live_edges(setups: list[Setup], s) -> None:
    """Résultats RÉELS des signaux passés (même stratégie, même classe d'actifs) : affichés sur chaque setup,
    et une combinaison qui perd en vrai sur assez de trades ne peut plus donner de 🟢."""
    for st in setups:
        e = (s.live_edges or {}).get(f"{st.strategy}|{st.asset_class}")
        if not e or not e.get("n"):
            continue
        n, wr, ar = e["n"], e.get("win_rate"), e.get("avg_r")
        note = f"résultats réels : {n} trade{'s' if n > 1 else ''}" + (f", {wr:.0f} % gagnants" if wr is not None else "") + \
            (f", {ar:+.2f}R en moyenne" if ar is not None else "")
        st.edge_note = f"{st.edge_note} · {note}" if st.edge_note else note
        if n >= s.live_min_trades and ar is not None and ar < s.live_block_avg_r and st.status == TRADE:
            st.status = WATCH
            st.rejections.append(f"{st.strategy} sur {st.asset_class} perd en vrai ({ar:+.2f}R en moyenne sur {n} trades) : pas de 🟢")


def _why_no_trade(rep: ScanReport, setups: list[Setup], snap: RiskSnapshot) -> list[str]:
    reasons: list[str] = []
    if snap.daily_limit_hit:
        reasons.append("perte journalière max atteinte — STOP nouveaux trades")
    if snap.available_risk_pct < 0.5:
        reasons.append(f"risque cumulé trop important (disponible {snap.available_risk_pct:.2f} %)")
    counts: dict[str, int] = {}
    for x in setups:
        for r in x.rejections:
            key = r.split("(")[0].strip()
            counts[key] = counts.get(key, 0) + 1
    for r, n in sorted(counts.items(), key=lambda kv: -kv[1])[:4]:
        reasons.append(f"{r} ({n} setup{'s' if n > 1 else ''})")
    unconfirmed = sum(1 for x in setups if not x.confirmed)
    if setups and unconfirmed:
        reasons.append(f"aucune entrée confirmée sur {unconfirmed} setup(s) en formation")
    if not setups:
        reasons.append("aucune configuration technique exploitable détectée")
    return reasons


def _journal(app: App, sig: Signal, status: str) -> int:
    st, p = sig.setup, sig.plan
    src = "; ".join(f"{n.source} ({n.published_at:%d/%m %H:%M} UTC)" for n in sig.news) or "données de marché Kraken"
    return app.db.insert("signals", {
        "ts": utcnow(), "instrument_key": st.inst_key, "display": st.display, "asset_class": st.asset_class,
        "direction": st.direction, "status": status, "strategy": st.strategy, "score": st.score,
        "entry_low": st.entry_low, "entry_high": st.entry_high, "entry": st.sizing_entry, "sl": st.sl,
        "tp1": st.tps[0] if st.tps else None, "tp2": st.tps[1] if len(st.tps) > 1 else None,
        "tp3": st.tps[2] if len(st.tps) > 2 else None, "leverage": p.leverage, "risk_percent": sig.risk_pct,
        "risk_amount": p.estimated_loss_at_sl_eur, "position_size": p.position_size, "notional_eur": p.notional_eur,
        "catalyst": sig.catalyst_label, "technical_reason": " | ".join(st.reasons), "source": src,
        "invalidation": st.invalidation_text, "outcome_status": "open",
        "payload": json.dumps({"setup": setup_dict(st), "plan": p.to_dict()}, default=str)})


def _journal_watch(app: App, st: Setup) -> None:
    app.db.insert("signals", {
        "ts": utcnow(), "instrument_key": st.inst_key, "display": st.display, "asset_class": st.asset_class,
        "direction": st.direction, "status": WATCH, "strategy": st.strategy, "score": st.score,
        "entry_low": st.entry_low, "entry_high": st.entry_high, "entry": st.sizing_entry, "sl": st.sl,
        "tp1": st.tps[0] if st.tps else None, "tp2": st.tps[1] if len(st.tps) > 1 else None,
        "tp3": st.tps[2] if len(st.tps) > 2 else None, "technical_reason": " | ".join(st.reasons),
        "invalidation": st.invalidation_text, "result": "NOT_TAKEN", "outcome_status": "watch",
        "payload": json.dumps(setup_dict(st), default=str)})


def _abort(app: App, rep: ScanReport, reason: str, t0: float) -> ScanReport:
    rep.verdict = "DATA"
    rep.no_trade_reasons = [f"DATA INSUFFISANTE — PAS DE TRADE : {reason}"]
    rep.duration_s = round(time.time() - t0, 1)
    log.error("SCAN ABORT: %s", reason)
    _save(app, rep)
    return rep


def _save(app: App, rep: ScanReport) -> None:
    rep.scan_id = app.db.insert("scans", {
        "ts": rep.ts.isoformat(timespec="seconds"), "mode": rep.mode, "instruments": rep.counts.get("tradables", 0),
        "candidates": rep.counts.get("candidats", 0), "analyzed": rep.counts.get("analysés", 0),
        "valid": len(rep.trades), "watch": len(rep.watch), "duration_s": rep.duration_s, "verdict": rep.verdict,
        "report": json.dumps(rep.to_dict(), default=str)})
    app.state["last_report"] = rep
    app.state["last_scan_at"] = rep.ts
    app.state["next_scan_at"] = rep.ts + timedelta(minutes=app.settings.scan_interval_minutes)
