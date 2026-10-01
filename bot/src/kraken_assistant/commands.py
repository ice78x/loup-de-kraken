"""Commandes texte partagées par le CLI et le dashboard.

SCAN · SCAN URGENT · POSITIONS · GESTION [id] · RISQUE · PORTFOLIO · STATUS · NEWS · JOURNAL
PAPER OPEN <signal> · PAPER CLOSE <id> · PAPER TP <id> <1-3> · PAPER SL <id> <prix> · PAPER STATS
PAPER HISTORY · PAPER DEPOSIT <€> · POSITION SET <id> sl= tp1= tp2= tp3= inv=
CALC <capital> <risque%> <entrée> <sl> [levier] · BACKTEST <paire> [stratégie] [csv]
HISTORIQUE · HISTORIQUE IMPORT <fichier|dossier> · HISTORIQUE BACKFILL · OPTIMISER [crypto|xstock|commodity|paire] · EDGE
LIVE PREPARE <signal> · CONFIRMER <ticket> <code> · AIDE
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .api.errors import DataUnavailable, LiveTradingDisabled
from .app import App
from .backtest.engine import BTParams, load_kraken_csv, run_backtest
from .market.candles import futures_rows_to_df, spot_rows_to_df
from .market.instruments import tradable_universe
from .market.prices import eur_per_quote
from .portfolio.management import advise
from .portfolio.pnl import paper_capital, paper_stats
from .risk.daily_loss import realized_pnl_today
from .risk.position_sizing import SizingInput, compute_position
from .scanner.formatter import LINE, eur, format_advice, format_news_item, format_report, hhmm, px
from .scanner.scan import Signal, scan
from .scanner.urgent import urgent_scan
from .strategies import STRATEGIES

log = logging.getLogger(__name__)

HELP = __doc__


def execute(app: App, text: str) -> str:
    raw = " ".join(text.strip().split())
    cmd = raw.upper()
    try:
        if cmd in ("SCAN",):
            return format_report(scan(app))
        if cmd in ("SCAN URGENT", "URGENT"):
            return format_report(urgent_scan(app, reasons=["demande manuelle"]))
        if cmd == "POSITIONS":
            return cmd_positions(app)
        if cmd.startswith("GESTION"):
            return cmd_gestion(app, raw)
        if cmd in ("RISQUE", "RISK"):
            return cmd_risk(app)
        if cmd == "PORTFOLIO":
            return cmd_portfolio(app)
        if cmd == "STATUS":
            return cmd_status(app)
        if cmd == "NEWS":
            return cmd_news(app)
        if cmd == "JOURNAL":
            return cmd_journal(app)
        if cmd.startswith("PAPER"):
            return cmd_paper(app, raw)
        if cmd.startswith("POSITION SET"):
            return cmd_position_set(app, raw)
        if cmd.startswith("CALC"):
            return cmd_calc(app, raw)
        if cmd.startswith("HISTORIQUE") or cmd.startswith("HISTORY"):
            return cmd_history(app, raw)
        if cmd.startswith("OPTIMISER") or cmd.startswith("OPTIMIZE"):
            return cmd_optimize(app, raw)
        if cmd == "EDGE":
            return cmd_edge(app)
        if cmd.startswith("BACKTEST"):
            return cmd_backtest(app, raw)
        if cmd.startswith("LIVE PREPARE"):
            return cmd_live_prepare(app, raw)
        if cmd.startswith("CONFIRMER"):
            parts = raw.split()
            if len(parts) != 3:
                return "Usage : CONFIRMER <ticket> <code>"
            res = app.live.execute(parts[1], parts[2])
            return "ORDRE RÉEL ENVOYÉ À KRAKEN\n" + json.dumps(res, indent=1, default=str)
        return HELP
    except LiveTradingDisabled as e:
        return f"🔒 {e}"
    except DataUnavailable as e:
        return f"🛑 DATA INSUFFISANTE — PAS DE TRADE\n• {e}"
    except (ValueError, RuntimeError) as e:
        return f"⚠ {e}"
    except Exception as e:  # jamais de plantage silencieux : message clair + trace complète dans le log
        log.exception("commande %r : erreur inattendue", raw)
        return (f"🛑 ERREUR INTERNE — PAS DE TRADE\n• {type(e).__name__}: {e}\n"
                "• Détail complet dans logs/assistant.log (envoie-le pour correction)")


# ------------------------------------------------------------------ helpers
def _market_now(app: App):
    insts = app.discovery.discover()
    tickers = app.prices.fetch(tradable_universe(insts))
    return insts, tickers


def _find_inst(insts, name: str):
    n = name.upper().replace("-", "/")
    for i in insts:
        if n in (i.symbol.upper(), i.display.upper(), i.display.upper().replace("/", ""), i.key.upper()):
            return i
    return None


# ------------------------------------------------------------------ positions / risque
def cmd_positions(app: App) -> str:
    pos = app.positions.open_positions(include_pending=True)
    holds = app.positions.holdings()
    if not pos and not holds:
        return "📂 POSITIONS\nAucune position ouverte (paper ou Kraken)."
    try:
        _, tickers = _market_now(app)
    except DataUnavailable:
        tickers = {}
    cap = app.capital()["risk_capital_eur"]
    out = ["📂 POSITIONS", LINE]
    for p in pos:
        t = tickers.get(p.instrument_key)
        price = t.last if t else None
        pnl = (p.unrealized_quote(price) * (p.eur_per_quote or 0)) if price and p.entry else None
        pr = app.risk.position_risk(p, cap)
        tps = " / ".join(f"{px(x)}{' ✓' if h else ''}" for x, h in ((p.tp1, p.tp1_hit), (p.tp2, p.tp2_hit), (p.tp3, p.tp3_hit)))
        out += [f"#{p.id} {p.display} {p.direction} [{p.source}] — {p.status.upper()}",
                f"  Entrée {px(p.entry) if p.entry else ('zone ' + px(p.entry_low) + '–' + px(p.entry_high) if p.entry_low else 'inconnue')}"
                f" · Prix {px(price) if price else 'indisponible'} · P&L {eur(pnl) if pnl is not None else '—'}",
                f"  SL {px(p.sl)} · TP {tps}",
                f"  Qté restante {p.qty_remaining:g}/{p.qty_initial:g} · Risque restant {eur(pr.risk_eur)}"
                + (" (hypothèse, SL inconnu)" if pr.assumed else ""), ""]
    if holds:
        out += ["💰 AVOIRS SPOT (hors budget de risque — pas de SL défini)"]
        for h in holds:
            t = tickers.get(h.instrument_key)
            val = h.qty_remaining * t.last if t else None
            out.append(f"  #{h.id} {h.display} {h.qty_remaining:g} ≈ {px(val) if val else '—'} {h.display.split('/')[-1]}"
                       f"  → pour le gérer : POSITION SET {h.id} entry=.. sl=..")
    return "\n".join(out)


def cmd_gestion(app: App, raw: str) -> str:
    parts = raw.split()
    pos = app.positions.open_positions()
    if len(parts) > 1:
        pos = [p for p in pos if str(p.id) == parts[1]]
    if not pos:
        return "Aucune position ouverte à gérer."
    insts, tickers = _market_now(app)
    by_key = {i.key: i for i in insts}
    out = ["🧭 GESTION POSITION (conseil — aucune action exécutée)", LINE]
    for p in pos:
        inst = by_key.get(p.instrument_key)
        frames = None
        if inst:
            try:
                frames = app.candles.frames(inst)
            except DataUnavailable as e:
                out.append(f"#{p.id} {p.display}: DATA INSUFFISANTE ({e})")
                continue
        t = tickers.get(p.instrument_key)
        out.append(format_advice(advise(p, frames, t.last if t else None, app.settings.tp_split)))
    return "\n".join(out)


def cmd_risk(app: App) -> str:
    cap = app.capital()
    snap = app.risk.snapshot(cap["risk_capital_eur"], app.positions.open_positions(),
                             realized_pnl_today(app.db, app.settings.timezone))
    s = app.settings
    state = "🛑 STOP — limite journalière atteinte" if snap.daily_limit_hit else (
        "🟢 budget disponible" if snap.available_risk_pct >= s.risk_min_pct else "🟡 budget quasi épuisé")
    lines = [f"⚖️ RISQUE — {state}", LINE,
             f"Capital ({cap['mode']}) : {eur(cap['risk_capital_eur'])}",
             f"Risque ouvert : {eur(snap.open_risk_eur)} ({snap.open_risk_pct:.2f} %) / max {s.max_open_risk_pct:.1f} %",
             f"Risque disponible : {eur(snap.available_risk_eur)} ({snap.available_risk_pct:.2f} %)",
             f"P&L réalisé du jour : {eur(snap.realized_today_eur)} (limite -{eur(snap.daily_limit_eur)})",
             f"Risque par trade : normal {s.risk_normal_pct} % ({eur(cap['risk_capital_eur'] * s.risk_normal_pct / 100)})"
             f" · exceptionnel {s.risk_exceptional_pct} %",
             f"Exposition : {', '.join(f'{k}×{v}' for k, v in snap.exposure.items()) or 'aucune'}"]
    lines += [f"⚠ {n}" for n in snap.notes]
    return "\n".join(lines)


def cmd_portfolio(app: App) -> str:
    cap = app.capital()
    pc = cap["paper"]
    lines = ["💼 PORTFOLIO", LINE, f"Mode : {cap['mode']}",
             f"PAPER : capital initial {eur(pc['initial'])} + dépôts {eur(pc['deposits'])} + P&L réalisé "
             f"{eur(pc['realized'])} = {eur(pc['equity'])}"]
    if cap.get("kraken_equity_eur") is not None:
        lines.append(f"KRAKEN : equity {eur(cap['kraken_equity_eur'])} (TradeBalance)")
    elif app.settings.has_spot_keys:
        lines.append(f"KRAKEN : illisible ({cap.get('kraken_error', 'erreur')})")
    else:
        lines.append("KRAKEN : pas de clé API — solde réel non lu")
    lines += ["", cmd_positions(app)]
    return "\n".join(lines)


def cmd_status(app: App) -> str:
    s = app.settings
    rep = app.state.get("last_report")
    lines = ["🩺 STATUS", LINE,
             f"Mode : {'LIVE ARMÉ ⚠️' if s.live_armed else 'PAPER / ANALYSE (live OFF)'}",
             f"Clés spot : {'oui' if s.has_spot_keys else 'non'} · futures : {'oui' if s.has_futures_keys else 'non'}",
             f"Dernier scan : {hhmm(app.state.get('last_scan_at'))} · Prochain : {hhmm(app.state.get('next_scan_at'))}",
             f"Scheduler : {'actif' if s.scheduler_enabled else 'désactivé'} (scan {s.scan_interval_minutes} min, "
             f"veille urgente {s.watch_interval_minutes} min)"]
    try:
        st = app.spot.system_status()
        lines.append(f"Kraken : {st.get('status', '?')}")
    except DataUnavailable as e:
        lines.append(f"Kraken : INJOIGNABLE ({e})")
    if app.news.source_status:
        lines.append("Sources news : " + ", ".join(f"{k} {v}" for k, v in app.news.source_status.items()))
    if rep and rep.data_issues:
        lines += ["", "Problèmes de données au dernier scan :"] + [f"• {d}" for d in rep.data_issues[:12]]
    return "\n".join(lines)


def cmd_news(app: App) -> str:
    insts = app.discovery.discover()
    items = app.news.fetch(app.taxonomy.aliases, {i.base for i in insts})
    rel = [n for n in items if n.impact >= 2][:10]
    if not items:
        return "📰 NEWS\nAucune news récupérée (sources injoignables ou désactivées). Rien n'est inventé."
    return "📰 NEWS (impact moyen/fort, 24h)\n" + LINE + "\n" + "\n\n".join(format_news_item(n) for n in rel)


def cmd_journal(app: App) -> str:
    rows = app.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 15")
    if not rows:
        return "📓 JOURNAL vide."
    out = ["📓 JOURNAL (15 derniers signaux)", LINE]
    for r in rows:
        r_txt = "" if r["r_achieved"] is None else f" ({r['r_achieved']:+.2f}R)"
        score = f"{r['score']:.0f}" if r["score"] is not None else "—"
        out.append(f"#{r['id']} {r['ts'][:16]} {r['status']} {r['direction']} {r['display']} "
                   f"E {px(r['entry'])} SL {px(r['sl'])} · {r['strategy']} · score {score} · "
                   f"{r['result'] or r['outcome_status']}{r_txt}")
    return "\n".join(out)


def cmd_position_set(app: App, raw: str) -> str:
    parts = raw.split()
    if len(parts) < 4:
        return "Usage : POSITION SET <id> sl=.. tp1=.. tp2=.. tp3=.. inv=.. entry=.."
    pid = int(parts[2])
    kv = dict(p.lower().split("=", 1) for p in parts[3:] if "=" in p)
    mapping = {"sl": "sl", "tp1": "tp1", "tp2": "tp2", "tp3": "tp3", "inv": "invalidation", "entry": "entry"}
    levels = {mapping[k]: float(v) for k, v in kv.items() if k in mapping}
    if not app.positions.get(pid):
        return "position introuvable"
    app.positions.set_levels(pid, **levels)
    if "sl" in levels:
        app.db.execute("UPDATE positions SET sl_initial=COALESCE(sl_initial, ?) WHERE id=?", (levels["sl"], pid))
    return f"Position #{pid} mise à jour : {levels}"


# ------------------------------------------------------------------ paper
def _signal_from_report(app: App, sid: int) -> Signal | None:
    rep = app.state.get("last_report")
    if rep:
        for s in rep.trades:
            if s.signal_id == sid:
                return s
    return None


def cmd_paper(app: App, raw: str) -> str:
    parts = raw.split()
    sub = parts[1].upper() if len(parts) > 1 else "STATS"
    if sub == "OPEN":
        if len(parts) < 3:
            return "Usage : PAPER OPEN <numéro de signal>"
        sig = _signal_from_report(app, int(parts[2]))
        if not sig:
            return "Signal introuvable dans le dernier scan (relance SCAN : un signal n'est valable que sur le scan courant)."
        insts, tickers = _market_now(app)
        t = tickers.get(sig.setup.inst_key)
        if not t:
            return "🛑 Prix actuel indisponible — ouverture paper impossible (aucun prix inventé)."
        epq = eur_per_quote(sig.inst.quote, insts, tickers)
        pid = app.paper.open_from_setup(sig.setup, sig.plan, epq, sig.fee_pct, t.bid, t.ask, sig.signal_id,
                                        sig.inst.base, sig.catalyst_label, sig.maker_fee_pct)
        p = app.positions.get(pid)
        return (f"🧪 PAPER #{pid} {p.direction} {p.display} — "
                + (f"exécuté à {px(p.entry)}" if p.status == "open" else
                   f"ordre limite en attente (zone {px(p.entry_low)}–{px(p.entry_high)}, prix actuel {px(t.last)})"))
    if sub in ("CLOSE", "TP", "SL"):
        if len(parts) < 3:
            return "Usage : PAPER CLOSE <id> | PAPER TP <id> <1-3> | PAPER SL <id> <prix>"
        pid = int(parts[2])
        p = app.positions.get(pid)
        if not p or p.source != "paper":
            return "position paper introuvable"
        if sub == "SL":
            app.paper.move_sl(pid, float(parts[3]), "manuel")
            return f"🧪 PAPER #{pid} SL → {parts[3]}"
        _, tickers = _market_now(app)
        t = tickers.get(p.instrument_key)
        if not t:
            return "🛑 Prix actuel indisponible — rien n'est exécuté."
        exit_px = t.bid if p.direction == "LONG" else t.ask
        if sub == "CLOSE":
            p2 = app.paper.close(pid, exit_px)
            return f"🧪 PAPER #{pid} fermée à {px(exit_px)} · P&L réalisé {eur(p2.realized_pnl_eur)}"
        k = int(parts[3]) if len(parts) > 3 else 1
        p2 = app.paper.take_partial(pid, exit_px, app.settings.tp_split[k - 1], k)
        return f"🧪 PAPER #{pid} TP{k} pris à {px(exit_px)} · reste {p2.qty_remaining:g}"
    if sub == "DEPOSIT":
        amt = float(parts[2])
        app.db.insert("cash_movements", {"ts": datetime.now(timezone.utc).isoformat(), "amount_eur": amt,
                                         "note": "dépôt paper"})
        return f"🧪 Dépôt paper de {eur(amt)} enregistré. Le risque se calcule sur le capital réel du compte, jamais sur des dépôts futurs."
    if sub == "HISTORY":
        rows = app.db.query("SELECT * FROM positions WHERE source='paper' ORDER BY id DESC LIMIT 20")
        if not rows:
            return "Aucun trade paper."
        return "🧪 HISTORIQUE PAPER\n" + LINE + "\n" + "\n".join(
            f"#{r['id']} {r['display']} {r['direction']} {r['status']} E {px(r['entry'])} P&L {eur(r['realized_pnl_eur'])}"
            f" · {r['strategy']}" for r in rows)
    initial = float(app.db.kv_get("paper_initial_capital", app.settings.capital_eur))
    st = paper_stats(app.db, initial)
    cap = paper_capital(app.db, initial)
    if st["trades"] == 0:
        return f"🧪 PAPER — capital {eur(cap['equity'])}\n{st['message']}"
    lines = [f"🧪 PAPER — capital {eur(cap['equity'])}", LINE,
             f"Trades {st['trades']} · gagnants {st['gagnants']} · perdants {st['perdants']} · win rate {st['win_rate_pct']} %",
             f"Profit moyen {eur(st['profit_moyen_eur'])} · perte moyenne {eur(st['perte_moyenne_eur'])}",
             f"R moyen {st['r_moyen']} · profit factor {st['profit_factor']} · drawdown max {st['max_drawdown_pct']} %"]
    for title, key in (("Par actif", "par_actif"), ("Par stratégie", "par_strategie"), ("Par catalyseur", "par_catalyseur")):
        lines.append(f"{title} : " + " · ".join(f"{k} {v['trades']}t {eur(v['pnl_eur'])}" for k, v in st[key].items()))
    return "\n".join(lines)


# ------------------------------------------------------------------ outils
def cmd_calc(app: App, raw: str) -> str:
    p = raw.split()
    if len(p) < 5:
        return "Usage : CALC <capital €> <risque %> <entrée> <sl> [levier]  (devise de cotation = EUR supposée)"
    cap, risk, entry, sl = map(float, p[1:5])
    lev = int(p[5]) if len(p) > 5 else None
    plan = compute_position(SizingInput(capital_eur=cap, risk_percent=risk, entry=entry, stop_loss=sl,
                                        direction="LONG" if sl < entry else "SHORT",
                                        fee_rate_pct=app.settings.default_spot_taker_fee_pct,
                                        allowed_leverages=list(range(1, app.settings.max_leverage + 1)),
                                        max_leverage=app.settings.max_leverage, leverage=lev))
    if not plan.ok:
        return "❌ " + "; ".join(plan.errors)
    return (f"🧮 Risque {eur(plan.risk_amount_eur)} · SL à {plan.sl_distance_pct:.2f} %\n"
            f"Taille {plan.position_size:g} · notionnel {eur(plan.notional_eur)} · levier x{plan.leverage} · "
            f"marge {eur(plan.margin_required_eur)}\nPerte estimée au SL (frais inclus) {eur(plan.estimated_loss_at_sl_eur)}"
            + ("\n⚠ " + "\n⚠ ".join(plan.warnings) if plan.warnings else ""))


def cmd_backtest(app: App, raw: str) -> str:
    p = raw.split()
    if len(p) < 2:
        return f"Usage : BACKTEST <paire> [stratégie: all|{'|'.join(STRATEGIES)}] [fichier.csv]"
    insts = app.discovery.discover()
    inst = _find_inst(insts, p[1])
    if not inst:
        return f"Instrument {p[1]} introuvable parmi les instruments Kraken découverts."
    strat = p[2] if len(p) > 2 and p[2] in (*STRATEGIES, "all") else "all"
    csv = next((x for x in p[2:] if x.endswith(".csv")), None)
    if csv:
        df15 = load_kraken_csv(csv)
    else:
        # Priorité à l'historique local (le plus long), complété par l'API si plus court
        df15 = app.history.history_15m(inst)
        if len(df15) < 720:
            api = (spot_rows_to_df(app.spot.ohlc(inst.symbol, 15, inst.api_asset_class)) if inst.venue == "spot"
                   else futures_rows_to_df(app.futures.candles(inst.symbol, 15, 2000)))
            from .market.history import merge
            df15 = merge(df15, api)
    fee, maker, _ = app.fee_for(inst)
    res = run_backtest(df15, inst, app.settings, BTParams(strategy=strat, fee_pct=fee, maker_fee_pct=maker,
                                                          capital=app.capital()["risk_capital_eur"],
                                                          tp_split=app.settings.tp_split))
    m = res.metrics()
    lines = [f"📊 BACKTEST {inst.display} · {strat}", LINE]
    if m["trades"] == 0:
        lines.append(m["message"])
    else:
        lines += [f"Période {m['periode']} ({m['bougies_15m']} bougies 15m, {res.candidates} setups détectés)",
                  f"Trades {m['trades']} · win rate {m['win_rate_pct']} % · profit factor {m['profit_factor']}",
                  f"Expectancy {m['expectancy_r']}R · R moyen gagnant {m['r_moyen_gagnant']} · perdant {m['r_moyen_perdant']}",
                  f"Drawdown max {m['max_drawdown_pct']} % · capital final {eur(m['capital_final'])}"]
    lines += ["", "Limites : " + " · ".join(res.notes),
              "Un résultat passé sur un petit échantillon ne prouve pas qu'une stratégie est rentable."]
    return "\n".join(lines)


def _days(n: int, tf: str) -> str:
    mins = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}[tf]
    d = n * mins / 1440
    return f"{d / 365:.1f} ans" if d >= 365 else f"{d:.0f} j"


def cmd_history(app: App, raw: str) -> str:
    parts = raw.split(maxsplit=2)
    sub = parts[1].upper() if len(parts) > 1 else ""
    insts = tradable_universe(app.discovery.discover())
    if sub == "IMPORT":
        if len(parts) < 3:
            return ("Usage : HISTORIQUE IMPORT <fichier.csv ou dossier>\n"
                    "Fichiers OHLCVT officiels Kraken (ex. XBTEUR_15.csv), à télécharger depuis support.kraken.com")
        rep = app.history.import_kraken_csv(parts[2], insts)
        if not rep:
            return "Aucun fichier reconnu (format attendu : <PAIRE>_<minutes>.csv, ex. XBTEUR_15.csv)."
        return "📥 IMPORT HISTORIQUE\n" + LINE + "\n" + "\n".join(f"{k} : {v:,} bougies".replace(",", " ")
                                                                  for k, v in rep.items())
    if sub == "BACKFILL":
        out, _ = [], app.prices
        insts_all, tickers = _market_now(app)
        fx = {"EUR": 1.0}
        try:
            fx["USD"] = eur_per_quote("USD", insts_all, tickers)
        except DataUnavailable:
            pass
        from .scanner.scan import select_candidates
        cands, _ = select_candidates(app, insts, tickers, fx, [], set(), None, "normal")
        for inst in cands:
            try:
                d1, w1 = app.history.fetch_htf(inst, max_age_h=0)
                n = app.history.backfill_futures(inst, "15m") if inst.venue == "futures" else 0
                out.append(f"{inst.display} : jour {len(d1) if d1 is not None else 0} · semaine "
                           f"{len(w1) if w1 is not None else 0}" + (f" · 15m +{n}" if n else ""))
            except DataUnavailable as e:
                out.append(f"{inst.display} : échec ({e})")
        return "📥 BACKFILL (jour/semaine via API ; 15m profond pour les perpétuels)\n" + LINE + "\n" + "\n".join(out) + \
            "\n\nPour l'historique 15m complet du spot : HISTORIQUE IMPORT <archives CSV Kraken>."
    cov = app.history.store.coverage()
    if not cov:
        return ("📚 HISTORIQUE vide pour l'instant.\nIl se remplit à chaque scan. Pour aller plus loin :\n"
                "• HISTORIQUE BACKFILL (jour/semaine + perpétuels 15m)\n• HISTORIQUE IMPORT <archives CSV Kraken>")
    by: dict[str, dict] = {}
    for r in cov:
        by.setdefault(r["key"], {})[r["tf"]] = r["n"]
    names = {i.key: i.display for i in app.discovery.discover()}
    lines = ["📚 HISTORIQUE LOCAL (profondeur par unité de temps)", LINE]
    for k, tfs in sorted(by.items(), key=lambda kv: -kv[1].get("15m", 0) - kv[1].get("5m", 0) / 3):
        lines.append(f"{names.get(k, k)} : " + " · ".join(f"{tf} {_days(n, tf)}" for tf, n in sorted(
            tfs.items(), key=lambda x: ["5m", "15m", "1h", "4h", "1d", "1w"].index(x[0]))))
    return "\n".join(lines[:40])


def cmd_optimize(app: App, raw: str) -> str:
    from .backtest.optimizer import optimize
    parts = raw.split()
    scope = parts[1].lower() if len(parts) > 1 else None
    insts = tradable_universe(app.discovery.discover())
    if scope in ("crypto", "xstock", "commodity"):
        insts = [i for i in insts if i.asset_class == scope]
    elif scope:
        i = _find_inst(insts, scope)
        insts = [i] if i else []
    keys_with_data = {r["key"] for r in app.history.store.coverage() if r["tf"] in ("5m", "15m")}
    data, fees = {}, {}
    for inst in insts:
        if inst.key not in keys_with_data:
            continue
        df15 = app.history.history_15m(inst)
        if len(df15):
            data[inst.key] = (inst, df15)
            t, m, _ = app.fee_for(inst)
            fees[inst.key] = (t, m)
    if not data:
        return ("⚙️ OPTIMISER : pas d'historique 15m local.\nLance d'abord des scans (l'historique s'accumule), "
                "HISTORIQUE BACKFILL (perpétuels) ou HISTORIQUE IMPORT (archives CSV Kraken).")
    rep = optimize(app.db, app.settings, data, fees)
    app.db.kv_set("last_optimization", datetime.now(timezone.utc).isoformat())
    lines = ["⚙️ OPTIMISATION WALK-FORWARD (validée hors échantillon)", LINE,
             f"Instruments utilisés : {len(rep['instruments'])}"]
    if rep["ignores"]:
        lines.append(f"Ignorés (historique trop court) : {len(rep['ignores'])}")
    for e in rep["resultats"]:
        icon = {"adopté": "🟢", "désactivé": "🔴"}.get(e.status, "⚪")
        lines.append(f"{icon} {e.asset_class}/{e.strategy} : {e.status} · seuil {e.score_threshold:.0f} · "
                     f"R:R≥{e.min_rr_tp2} · OOS {e.oos_trades} trades"
                     + (f" {e.oos_expectancy:+.2f}R" if e.oos_expectancy is not None else ""))
    lines += ["", "Adopté = gagnant sur des périodes jamais vues pendant le réglage. Ce n'est pas une garantie."]
    return "\n".join(lines)


def cmd_edge(app: App) -> str:
    from .backtest.optimizer import load_edges
    edges = load_edges(app.db)
    if not edges:
        return "Aucune optimisation enregistrée. Lance OPTIMISER."
    last = app.db.kv_get("last_optimization")
    lines = [f"📈 EDGE PAR STRATÉGIE (dernière optimisation {str(last)[:16] if last else '—'})", LINE]
    for e in sorted(edges.values(), key=lambda x: (x.asset_class, x.strategy)):
        lines.append(f"{e.asset_class}/{e.strategy} : {e.note()}")
    return "\n".join(lines)


def cmd_live_prepare(app: App, raw: str) -> str:
    parts = raw.split()
    sig = _signal_from_report(app, int(parts[2])) if len(parts) > 2 else None
    if not sig:
        return "Signal introuvable dans le dernier scan."
    t = app.live.prepare(sig.setup, sig.plan, sig.inst)
    return t.summary()
