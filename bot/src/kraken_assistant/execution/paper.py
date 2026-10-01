"""Paper trading : exécution virtuelle sur PRIX RÉELS Kraken (ticker + bougies 5m).

- Ouverture : immédiate au prix ask/bid réel si le prix est dans la zone, sinon ordre limite en attente.
- Suivi : bougies 5m clôturées depuis la dernière vérification ; SL testé AVANT les TP dans une même
  bougie (hypothèse prudente) ; TP partiels 30/40/30 ; frais appliqués à chaque exécution.
- Aucun prix n'est inventé : sans ticker/bougie réelle, rien n'est exécuté.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..config import Settings
from ..database.db import Database, utcnow
from ..portfolio.management import EXIT, advise
from ..portfolio.positions import Position, PositionStore
from ..risk.position_sizing import PositionPlan
from ..strategies.base import Setup

log = logging.getLogger(__name__)


class PaperBroker:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.s = db, settings
        self.store = PositionStore(db)

    # ------------------------------------------------------------ helpers
    def _fill(self, pos_id: int, kind: str, price: float, qty: float, pnl: float, fee: float, note: str = "",
              ts: str | None = None) -> None:
        self.db.insert("fills", {"position_id": pos_id, "ts": ts or utcnow(), "kind": kind, "price": price,
                                 "qty": qty, "pnl_eur": round(pnl, 6), "fee_eur": round(fee, 6), "note": note})

    def _fee_eur(self, p: Position, price: float, qty: float, maker: bool = False) -> float:
        rate = p.fee_rate_pct
        if maker:
            r = self.db.one("SELECT maker_fee_pct FROM positions WHERE id=?", (p.id,))
            rate = r["maker_fee_pct"] if r and r["maker_fee_pct"] is not None else rate
        return rate / 100 * price * qty * (p.eur_per_quote or 0)

    # ------------------------------------------------------------ open
    def open_from_setup(self, st: Setup, plan: PositionPlan, eur_per_quote: float, fee_rate_pct: float,
                        bid: float | None, ask: float | None, signal_id: int | None, base: str,
                        catalyst: str | None, maker_fee_pct: float | None = None) -> int:
        if not plan.ok:
            raise ValueError("plan de position invalide : " + "; ".join(plan.errors))
        pid = self.db.insert("positions", {
            "source": "paper", "signal_id": signal_id, "instrument_key": st.inst_key, "display": st.display,
            "base": base, "venue": st.inst_key.split(":")[0], "asset_class": st.asset_class,
            "direction": st.direction, "entry": None, "entry_low": st.entry_low, "entry_high": st.entry_high,
            "qty_initial": plan.position_size, "qty_remaining": plan.position_size, "sl": st.sl, "sl_initial": st.sl,
            "tp1": st.tps[0] if len(st.tps) > 0 else None, "tp2": st.tps[1] if len(st.tps) > 1 else None,
            "tp3": st.tps[2] if len(st.tps) > 2 else None, "invalidation": st.invalidation_price,
            "status": "pending", "created_at": utcnow(), "strategy": st.strategy, "catalyst": catalyst,
            "leverage": plan.leverage, "risk_eur_initial": plan.estimated_loss_at_sl_eur,
            "eur_per_quote": eur_per_quote, "fee_rate_pct": fee_rate_pct, "maker_fee_pct": maker_fee_pct,
            "last_checked": utcnow()})
        px = ask if st.direction == "LONG" else bid
        if px and st.entry_low <= px <= st.entry_high:
            self._activate(pid, px, "exécution immédiate au prix réel du carnet")
        log.info("PAPER ouverture #%d %s %s (%s)", pid, st.direction, st.display,
                 "exécutée" if self.store.get(pid).status == "open" else "ordre limite en attente")
        return pid

    def _activate(self, pid: int, price: float, note: str, ts: str | None = None, maker: bool = False) -> None:
        r = self.db.one("SELECT * FROM positions WHERE id=?", (pid,))
        rate = r["maker_fee_pct"] if maker and r["maker_fee_pct"] is not None else (r["fee_rate_pct"] or 0)
        fee = rate / 100 * price * r["qty_initial"] * (r["eur_per_quote"] or 0)
        self.db.update("positions", pid, {"entry": price, "status": "open", "opened_at": ts or utcnow(),
                                          "fees_eur": fee, "realized_pnl_eur": -fee})
        self._fill(pid, "entry", price, r["qty_initial"], -fee, fee, note, ts)

    def open_manual(self, inst_key: str, display: str, base: str, asset_class: str, direction: str, price: float,
                    qty: float, sl: float, tps: list[float], eur_per_quote: float, fee_rate_pct: float,
                    risk_eur: float) -> int:
        pid = self.db.insert("positions", {
            "source": "paper", "instrument_key": inst_key, "display": display, "base": base,
            "venue": inst_key.split(":")[0], "asset_class": asset_class, "direction": direction,
            "entry_low": price, "entry_high": price, "qty_initial": qty, "qty_remaining": qty, "sl": sl,
            "sl_initial": sl, "tp1": tps[0] if tps else None, "tp2": tps[1] if len(tps) > 1 else None,
            "tp3": tps[2] if len(tps) > 2 else None, "status": "pending", "created_at": utcnow(),
            "strategy": "manuel", "risk_eur_initial": risk_eur, "eur_per_quote": eur_per_quote,
            "fee_rate_pct": fee_rate_pct, "last_checked": utcnow()})
        self._activate(pid, price, "ouverture manuelle au prix réel")
        return pid

    # ------------------------------------------------------------ close
    def _close_part(self, p: Position, price: float, qty: float, kind: str, note: str, ts: str | None = None) -> Position:
        qty = min(qty, p.qty_remaining)
        fee = self._fee_eur(p, price, qty, maker=kind in ("tp1", "tp2", "tp3"))
        pnl = p.sign * (price - p.entry) * qty * (p.eur_per_quote or 0) - fee
        self._fill(p.id, kind, price, qty, pnl, fee, note, ts)
        remaining = round(p.qty_remaining - qty, 12)
        data = {"qty_remaining": remaining, "realized_pnl_eur": p.realized_pnl_eur + pnl}
        if kind in ("tp1", "tp2", "tp3"):
            data[f"{kind}_hit"] = 1
        if remaining <= 1e-12:
            data.update({"status": "closed", "closed_at": ts or utcnow(), "qty_remaining": 0})
        self.db.update("positions", p.id, data)
        self.db.execute("UPDATE positions SET fees_eur = COALESCE(fees_eur,0) + ? WHERE id=?", (fee, p.id))
        p2 = self.store.get(p.id)
        if p2.status == "closed":
            self._record_outcome(p2)
        return p2

    def close(self, pid: int, price: float, note: str = "clôture manuelle") -> Position:
        p = self.store.get(pid)
        if not p or p.source != "paper":
            raise ValueError("position paper introuvable")
        if p.status == "pending":
            self.db.update("positions", pid, {"status": "cancelled", "closed_at": utcnow(), "notes": note})
            return self.store.get(pid)
        return self._close_part(p, price, p.qty_remaining, "manual", note)

    def take_partial(self, pid: int, price: float, fraction_of_initial: float, tp_index: int | None = None) -> Position:
        p = self.store.get(pid)
        kind = f"tp{tp_index}" if tp_index else "manual"
        return self._close_part(p, price, p.qty_initial * fraction_of_initial, kind, "prise partielle")

    def move_sl(self, pid: int, new_sl: float, reason: str) -> None:
        self.db.update("positions", pid, {"sl": new_sl, "notes": reason})
        log.info("PAPER #%d SL -> %.8g (%s)", pid, new_sl, reason)

    def _record_outcome(self, p: Position) -> None:
        if not p.signal_id:
            return
        r = p.realized_pnl_eur / p.risk_eur_initial if p.risk_eur_initial else None
        res = "BE" if r is not None and abs(r) < 0.1 else ("WIN" if p.realized_pnl_eur > 0 else "LOSS")
        self.db.execute("UPDATE signals SET result=?, r_achieved=?, outcome_status='closed' WHERE id=?",
                        (res, round(r, 3) if r is not None else None, p.signal_id))

    # ------------------------------------------------------------ update
    def update(self, pid: int, bars5: pd.DataFrame, frames: dict | None, price: float | None,
               now: datetime | None = None) -> list[str]:
        """Rejoue les bougies 5m clôturées depuis last_checked. Retourne les évènements."""
        now = now or datetime.now(timezone.utc)
        p = self.store.get(pid)
        events: list[str] = []
        if not p or p.status not in ("pending", "open"):
            return events
        row = self.db.one("SELECT last_checked, created_at FROM positions WHERE id=?", (pid,))
        since = pd.Timestamp(row["last_checked"] or row["created_at"])
        # une bougie 5m ne compte que si elle a commencé après la dernière vérification
        new = bars5[bars5.index >= since.floor("5min")]
        split = self.s.tp_split
        for ts, b in new.iterrows():
            tss = ts.isoformat()
            if p.status == "pending":
                created = pd.Timestamp(row["created_at"])
                if ts - created > timedelta(hours=self.s.paper_pending_expiry_hours):
                    self.db.update("positions", pid, {"status": "cancelled", "closed_at": tss,
                                                      "notes": "ordre limite expiré (non déclenché)"})
                    self.db.execute("UPDATE signals SET result='EXPIRED', outcome_status='closed' WHERE id=?",
                                    (p.signal_id,))
                    events.append(f"#{pid} ordre expiré")
                    break
                hi_lim = self.db.one("SELECT entry_low, entry_high FROM positions WHERE id=?", (pid,))
                lo_z, hi_z = hi_lim["entry_low"], hi_lim["entry_high"]
                if p.direction == "LONG" and b["low"] <= hi_z:
                    self._activate(pid, min(float(b["open"]), hi_z), "limite déclenchée (bougie 5m réelle)", tss, maker=True)
                elif p.direction == "SHORT" and b["high"] >= lo_z:
                    self._activate(pid, max(float(b["open"]), lo_z), "limite déclenchée (bougie 5m réelle)", tss,
                                   maker=True)
                else:
                    continue
                p = self.store.get(pid)
                events.append(f"#{pid} entrée exécutée à {p.entry:.6g}")
            # SL d'abord (prudence)
            sg = p.sign
            adverse = b["low"] if sg > 0 else b["high"]
            if p.sl is not None and sg * (adverse - p.sl) <= 0:
                fill = min(float(b["open"]), p.sl) if sg > 0 else max(float(b["open"]), p.sl)
                kind = "sl"
                p = self._close_part(p, fill, p.qty_remaining, kind, "stop touché", tss)
                events.append(f"#{pid} SL exécuté à {fill:.6g}")
                break
            favorable = b["high"] if sg > 0 else b["low"]
            for i, tp in ((1, p.tp1), (2, p.tp2), (3, p.tp3)):
                if tp is None or getattr(p, f"tp{i}_hit"):
                    continue
                if sg * (favorable - tp) >= 0:
                    last_tp = i == 3 or (p.tp3 is None and (i == 2 or p.tp2 is None))
                    qty = p.qty_remaining if last_tp else p.qty_initial * split[i - 1]
                    p = self._close_part(p, tp, qty, f"tp{i}", f"TP{i} atteint", tss)
                    events.append(f"#{pid} TP{i} exécuté à {tp:.6g}")
                    if p.status == "closed":
                        break
            if p.status == "closed":
                break
        self.db.update("positions", pid, {"last_checked": now.isoformat(timespec="seconds")})
        p = self.store.get(pid)
        if p.status == "open" and self.s.paper_auto_manage and frames is not None and price is not None:
            adv = advise(p, frames, price, split)
            if adv.action == EXIT:
                self._close_part(p, price, p.qty_remaining, "manual", "sortie sur invalidation (auto paper)")
                events.append(f"#{pid} sortie sur invalidation à {price:.6g}")
            elif adv.new_sl is not None:
                self.move_sl(pid, adv.new_sl, "; ".join(adv.details))
                events.append(f"#{pid} SL déplacé à {adv.new_sl:.6g}")
        return events
