"""P&L, capital et statistiques (paper)."""
from __future__ import annotations

from collections import defaultdict

from ..database.db import Database


def paper_capital(db: Database, initial: float) -> dict:
    realized = db.one("SELECT COALESCE(SUM(f.pnl_eur),0) AS v FROM fills f JOIN positions p ON p.id=f.position_id "
                      "WHERE p.source='paper'")["v"]
    deposits = db.one("SELECT COALESCE(SUM(amount_eur),0) AS v FROM cash_movements")["v"]
    return {"initial": initial, "deposits": deposits, "realized": realized,
            "equity": round(initial + deposits + realized, 4)}


def _group(rows: list[dict], key: str) -> dict[str, dict]:
    g: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl_eur": 0.0, "wins": 0})
    for r in rows:
        k = r.get(key) or "—"
        g[k]["trades"] += 1
        g[k]["pnl_eur"] = round(g[k]["pnl_eur"] + r["realized_pnl_eur"], 4)
        g[k]["wins"] += 1 if r["realized_pnl_eur"] > 0 else 0
    return dict(g)


def paper_stats(db: Database, initial: float) -> dict:
    rows = db.query("SELECT * FROM positions WHERE source='paper' AND status='closed' AND opened_at IS NOT NULL "
                    "ORDER BY closed_at")
    n = len(rows)
    if n == 0:
        return {"trades": 0, "message": "Aucun trade paper clôturé : pas encore de statistiques (rien n'est inventé)."}
    pnl = [r["realized_pnl_eur"] for r in rows]
    rs = [r["realized_pnl_eur"] / r["risk_eur_initial"] for r in rows if r["risk_eur_initial"]]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    equity, peak, max_dd = initial, initial, 0.0
    for x in pnl:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
    return {
        "trades": n, "gagnants": len(wins), "perdants": len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "profit_moyen_eur": round(gross_win / len(wins), 4) if wins else 0.0,
        "perte_moyenne_eur": round(-gross_loss / len(losses), 4) if losses else 0.0,
        "r_moyen": round(sum(rs) / len(rs), 2) if rs else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "max_drawdown_pct": round(max_dd, 2),
        "pnl_total_eur": round(sum(pnl), 4),
        "par_actif": _group(rows, "display"),
        "par_strategie": _group(rows, "strategy"),
        "par_catalyseur": _group(rows, "catalyst"),
    }
