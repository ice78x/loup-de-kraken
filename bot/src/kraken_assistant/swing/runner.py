"""Lance le backtest SWING sur de vraies données Kraken (GitHub Actions) : bougies 1j + funding historique."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from ..api.errors import DataUnavailable, KrakenAPIError
from ..backtest.runner import pick_universe
from .backtest import SwingParams, daily_funding, report

log = logging.getLogger(__name__)
MIN_DAYS = 200


def load_data(app, insts, days: int) -> tuple[dict, list[str], dict]:
    data, skipped, coverage = {}, [], {}
    for inst in insts:
        try:
            app.history.backfill_futures(inst, "1d", max_days=days)
        except DataUnavailable as e:
            skipped.append(f"{inst.display} : historique indisponible ({e})")
            continue
        df = app.history.store.load(inst.key, "1d")
        if len(df) < MIN_DAYS:
            skipped.append(f"{inst.display} : {len(df)} jours d'historique ({MIN_DAYS} requis)")
            continue
        try:
            rates = app.futures.historical_funding(inst.symbol)
        except (DataUnavailable, KrakenAPIError) as e:
            log.warning("funding %s indisponible : %s", inst.display, e)
            rates = []
        fund = daily_funding(rates, df.index)
        coverage[inst.display] = round(float(fund.notna().mean()) * 100, 1)
        data[inst.key] = (inst.asset_class, df, fund)
    return data, skipped, coverage


def run_swing(app, days: int = 1500, crypto: int = 40, classes: dict | None = None) -> dict:
    started = datetime.now(timezone.utc)
    insts = pick_universe(app, crypto, classes)
    data, skipped, coverage = load_data(app, insts, days)
    if not data:
        return {"type": "swing", "message": "DATA INSUFFISANTE — aucun historique journalier exploitable", "ignores": skipped}
    rep = report(data, SwingParams())
    allf = [x for _, _, f in data.values() for x in f.dropna().tolist()]
    rep.update({
        "instruments": {k.split(":")[-1]: len(df) for k, (_, df, _) in data.items()},
        "classes": {c: sum(1 for cl, _, _ in data.values() if cl == c) for c in {cl for cl, _, _ in data.values()}},
        "periode": f"{min(df.index[0] for _, df, _ in data.values()):%Y-%m-%d} → "
                   f"{max(df.index[-1] for _, df, _ in data.values()):%Y-%m-%d}",
        "funding_couverture_pct": coverage,
        "funding_jour_median_pct": round(float(pd.Series(allf).abs().median()) * 100, 4) if allf else None,
        "ignores": skipped, "lance_le": started.isoformat(timespec="seconds"),
        "duree_s": round((datetime.now(timezone.utc) - started).total_seconds()),
    })
    return rep


def summary_text(rep: dict) -> str:
    if "par_classe" not in rep:
        return "🛑 " + rep.get("message", "backtest swing impossible")
    out = [f"BACKTEST SWING (bougies 1j, stop suiveur, funding compté) · {rep.get('periode')} · "
           f"{len(rep.get('instruments', {}))} perpétuels · funding médian {rep.get('funding_jour_median_pct')} %/jour"]
    for cls, c in rep["par_classe"].items():
        wf = c["walk_forward"]
        o = wf.get("oos", {})
        s = c.get("stats_variante", {})
        out.append(f"[{cls}] variante {c.get('variante_retenue')} : {s.get('n', 0)} trades, {s.get('expectancy_r', 0):+.3f}R, "
                   f"PF {s.get('profit_factor')} · hors échantillon {o.get('n', 0)} trades {o.get('expectancy_r', 0) or 0:+.3f}R "
                   f"→ {'PROUVÉ' if c.get('prouve') else 'non prouvé'}")
        for y, st in c.get("par_annee", {}).items():
            out.append(f"    {y} : {st.get('n')} trades {st.get('expectancy_r', 0):+.3f}R")
        for name, d in c.get("variantes_detail", {}).items():
            o = d.get("hors_echantillon", {})
            out.append(f"    variante {name} : hors échantillon {o.get('n', 0)} trades {o.get('expectancy_r', 0) or 0:+.3f}R "
                       f"→ {'prouvée' if d.get('prouve') else 'non prouvée'}")
        for k in ("par_palier_tout", "par_palier_hors_echantillon"):
            pp = c.get(k) or {}
            if pp:
                out.append(f"    {k} : " + " · ".join(f"{t}/4 : {st.get('n', 0)} trades {st.get('expectancy_r', 0) or 0:+.2f}R"
                                                    for t, st in pp.items()))
        for k, sc in c.get("scenarios_club", {}).items():
            if sc.get("trades"):
                mm = sc.get("mensuel") or {}
                if mm:
                    out.append(f"    mois positifs {k} : {mm['mois_positifs']}/{mm['mois']} ({mm['pct_mois_positifs']} %) · "
                               f"pire mois {mm['pire_mois_pct']:+.1f} % · meilleur {mm['meilleur_mois_pct']:+.1f} %")
                out.append(f"    scénario club {k:<22} {sc['trades']:>4} trades ({sc['trades_par_mois']}/mois) "
                           f"{sc['expectancy_r']:+.3f}R · capital 100 → {sc['capital_final']:.0f} · pire baisse {sc['max_drawdown_pct']:.1f} % "
                           f"· pire série {sc['pire_serie_pertes']}")
    out.append("Toutes les variantes (tout l'historique) :")
    for name, v in rep.get("variantes", {}).items():
        t = v.get("tout", {})
        out.append(f"  {name:<28} {t.get('n', 0):>4} trades {t.get('expectancy_r', 0) or 0:+.3f}R PF {t.get('profit_factor')} "
                   f"durée {t.get('jours_moyens')} j funding {t.get('funding_r_moyen')}R")
    return "\n".join(out)
