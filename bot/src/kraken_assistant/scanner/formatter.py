"""Sorties texte courtes, structurées, visuelles, actionnables (pensées pour un lecteur TDAH).

Toujours commencer par : 🟢 TRADE VALIDÉ / 🟡 SURVEILLER / 🛑 AUCUN TRADE — ATTENDRE.
Vocabulaire interdit : "trade sûr", "gain garanti", "machine à cash", "aucun risque".
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..news.engine import NewsItem
from ..portfolio.management import Advice
from ..strategies.base import Setup
from .scan import ScanReport, Signal

SEP = "=" * 30
LINE = "-" * 30
FORBIDDEN = ("trade sûr", "gain garanti", "machine à cash", "aucun risque")
TZ = ZoneInfo("Europe/Paris")


def px(x: float | None) -> str:
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"{x:,.1f}".replace(",", " ")
    return f"{x:.6g}"


def eur(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f} €".replace(".", ",")


def hhmm(d: datetime | None) -> str:
    return d.astimezone(TZ).strftime("%H:%M") if d else "—"


def _q(inst_quote: str) -> str:
    return {"USD": " $", "EUR": " €"}.get(inst_quote, f" {inst_quote}")


def format_signal(sig: Signal) -> str:
    st, p, q = sig.setup, sig.plan, _q(sig.inst.quote)
    rs, rn = st.r_multiples(), p.r_multiples_net
    lines = [f"🟢 TRADE VALIDÉ — {st.direction} {st.display}", SEP,
             "ENTRY", f"{px(st.entry_low)} – {px(st.entry_high)}{q}", "",
             "SL", f"{px(st.sl)}{q}", ""]
    for i, tp in enumerate(st.tps, 1):
        lines += [f"TP{i}", f"{px(tp)}{q}", ""]
    lines += ["LEVIER", f"x{p.leverage}" + (" (sans marge)" if p.leverage == 1 and sig.inst.venue == "spot" else ""), "",
              "RISQUE", f"{eur(p.estimated_loss_at_sl_eur)} / {p.effective_risk_pct:.2f} % (frais inclus)", "",
              "TAILLE", f"{p.position_size:g} {sig.inst.base}  ≈ {eur(p.notional_eur)} · marge {eur(p.margin_required_eur)}", "",
              "R:R (brut · net de frais)"]
    lines += [f"TP{i} = {rs[i-1]:.1f} · {rn[i-1]:.1f}" for i in range(1, len(st.tps) + 1) if i - 1 < len(rn)]
    lines += ["", "GESTION", "TP1 → 30 %", "TP2 → 40 %", "TP3 → 30 %",
              "Après TP1 : SL → break-even SI confirmation 15m (sinon inchangé)",
              "Après TP2 : SL suiveur sous le dernier creux 1h", "",
              "INVALIDATION", st.invalidation_text, "",
              "CATALYSEUR", sig.catalyst_label, "",
              "SOURCE"]
    lines += [f"{n.source} — {n.published_at.astimezone(TZ):%d/%m %H:%M} (vérifiée {n.fetched_at.astimezone(TZ):%H:%M})"
              for n in sig.news] or ["Données de marché Kraken (5m/15m/1h/4h clôturées + historique jour/semaine)"]
    if st.edge_note:
        lines += ["", "HISTORIQUE", st.edge_note]
    lines += ["", f"ACTION : {st.action}", "",
              f"Pourquoi : {' · '.join(st.reasons[:2])}",
              f"Score {st.score:.0f}/100 · {st.strategy} · gain net estimé TP1/TP2/TP3 : "
              + " / ".join(eur(x) for x in p.estimated_profit_tp_eur),
              f"Signal n°{sig.signal_id} → PAPER OPEN {sig.signal_id}"]
    if sig.warnings:
        lines += ["", "⚠ " + "\n⚠ ".join(sig.warnings[:4])]
    lines.append(SEP)
    return "\n".join(lines)


def format_watch(w: Setup) -> str:
    rs = w.r_multiples()
    trig = w.trigger or ("" if w.confirmed else "clôture 15m de confirmation")
    why = w.rejections[0] if w.rejections else ""
    return (f"🟡 {w.direction} {w.display}  (score {w.score:.0f})\n"
            f"   Zone {px(w.entry_low)}–{px(w.entry_high)} · SL {px(w.sl)} · TP1 {px(w.tps[0]) if w.tps else '—'}"
            f" ({rs[0] if rs else 0:.1f}R)"
            + (f"\n   Déclencheur : {trig}" if trig else "") + (f"\n   Bloquant : {why}" if why else ""))


def format_news_item(n: NewsItem) -> str:
    flag = "✅ vérifiée" if n.verified else ("❗ rumeur" if n.is_rumor else "❔ non vérifiée")
    return (f"• {n.title}\n  {n.source} · publiée {n.published_at.astimezone(TZ):%d/%m %H:%M} · "
            f"vérif. {n.fetched_at.astimezone(TZ):%H:%M} · {flag}\n"
            f"  Actif : {', '.join(n.assets) or ('macro' if n.macro else '—')} · impact {n.impact_label}\n"
            f"  FAIT : {n.fact}\n  INTERPRÉTATION : {n.interpretation}")


def format_advice(a: Advice) -> str:
    icon = "🔴" if a.urgent else "🔵"
    extra = f" → {px(a.new_sl)}" if a.new_sl is not None else ""
    return f"{icon} #{a.position_id} {a.display} : {a.action}{extra}\n   " + "\n   ".join(a.details)


def format_report(rep: ScanReport) -> str:
    out: list[str] = []
    if rep.verdict == "DATA":
        out += ["🛑 DATA INSUFFISANTE — PAS DE TRADE", ""]
        out += [f"• {r}" for r in rep.no_trade_reasons[:5]]
        out += _footer(rep)
        return _check("\n".join(out))
    urgent_adv = [a for a in rep.advice if a.urgent]
    if urgent_adv:
        out += ["🔴 POSITION : DÉCISION REQUISE"] + [format_advice(a) for a in urgent_adv] + [""]
    if rep.trades:
        out += [format_signal(s) for s in rep.trades]
        if rep.watch:
            out += ["", "🟡 SURVEILLER AUSSI"] + [format_watch(w) for w in rep.watch[:3]]
    elif rep.watch:
        out += ["🟡 SURVEILLER — pas d'entrée confirmée", ""] + [format_watch(w) for w in rep.watch[:4]]
        out += ["", "Pourquoi pas de trade :"] + [f"• {r}" for r in rep.no_trade_reasons[:3]]
    else:
        out += ["🛑 AUCUN TRADE — ATTENDRE", "", "Pourquoi :"] + [f"• {r}" for r in rep.no_trade_reasons[:4]]
    major = [n for n in rep.news if n.impact >= 3][:3]
    if major:
        out += ["", "📰 NEWS IMPORTANTES"] + [f"• {n.title} ({n.source}, {hhmm(n.published_at)}"
                                            f"{'' if n.verified else ', NON vérifiée'})" for n in major]
    other_adv = [a for a in rep.advice if not a.urgent]
    if other_adv:
        out += ["", "📂 POSITIONS"] + [format_advice(a) for a in other_adv]
    if rep.paper_events:
        out += ["", "🧪 PAPER : " + " · ".join(rep.paper_events)]
    out += _footer(rep)
    return _check("\n".join(out))


def _footer(rep: ScanReport) -> list[str]:
    c = rep.counts
    lines = ["", LINE, f"Scan {rep.mode} {hhmm(rep.ts)} · {c.get('tradables', 0)} instruments · "
             f"{c.get('analysés', 0)} analysés · {rep.duration_s:.0f}s"]
    if rep.risk:
        r = rep.risk
        lines.append(f"Risque ouvert {eur(r.open_risk_eur)} · disponible {eur(r.available_risk_eur)} · "
                     f"P&L jour {eur(r.realized_today_eur)}")
    if rep.data_issues:
        lines.append(f"⚠ {len(rep.data_issues)} problème(s) de données (commande STATUS)")
    return lines


def _check(text: str) -> str:
    """Filet de sécurité : aucune formulation de type 'gain garanti' ne sort du système."""
    import re
    for f in FORBIDDEN:
        text = re.sub(re.escape(f), "[formulation retirée]", text, flags=re.IGNORECASE)
    return text
