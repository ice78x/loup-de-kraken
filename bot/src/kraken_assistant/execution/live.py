"""Exécution RÉELLE Kraken — OFF par défaut, triple verrou.

Verrou 1 : LIVE_TRADING=true dans .env
Verrou 2 : LIVE_TRADING_ACK=J_ACCEPTE_LE_RISQUE_REEL dans .env
Verrou 3 : chaque ordre passe par prepare() (affiche risque, taille, entrée, SL, TP + code unique à usage
           unique, valable LIVE_CONFIRMATION_TTL_S secondes) puis execute(ticket, code).
Côté spot, l'ordre est d'abord soumis avec validate=true (vérifié par Kraken sans être envoyé au carnet).
Les TP ne sont pas posés automatiquement (Kraken n'accepte qu'un ordre de clôture conditionnel par ordre
spot) : le SL est attaché, les TP restent à poser/suivre via GESTION POSITION.
Cette partie n'a PAS été testée contre le compte réel : fais un premier essai avec la plus petite taille.
"""
from __future__ import annotations

import logging
import math
import secrets
import time
from dataclasses import asdict, dataclass

from ..api.errors import LiveTradingDisabled
from ..api.kraken_futures import KrakenFuturesClient
from ..api.kraken_spot import KrakenSpotClient
from ..config import Settings
from ..database.db import Database
from ..market.models import Instrument
from ..risk.position_sizing import PositionPlan
from ..strategies.base import Setup

log = logging.getLogger(__name__)


def round_price(px: float, inst: Instrument) -> float:
    if inst.tick_size and inst.tick_size > 0:
        return round(round(px / inst.tick_size) * inst.tick_size, 12)
    return round(px, inst.pair_decimals)


def floor_qty(q: float, decimals: int) -> float:
    step = 10 ** (-decimals)
    return math.floor(q / step + 1e-9) * step


@dataclass
class OrderTicket:
    ticket_id: str
    code: str
    expires_at: float
    venue: str
    symbol: str
    display: str
    direction: str
    entry: float
    sl: float
    tps: list[float]
    size: float
    leverage: int
    risk_eur: float
    risk_pct: float
    params: dict
    validated: str
    used: bool = False

    def summary(self) -> str:
        tps = " / ".join(f"{t:.6g}" for t in self.tps)
        return (f"⚠️ ORDRE RÉEL — CONFIRMATION REQUISE\n\n{self.direction} {self.display}\nENTRY  {self.entry:.6g}\n"
                f"SL     {self.sl:.6g}\nTP     {tps} (à gérer manuellement)\nTAILLE {self.size:g}\n"
                f"LEVIER x{self.leverage}\nRISQUE {self.risk_eur:.2f} € / {self.risk_pct:.2f} %\n"
                f"Validation Kraken : {self.validated}\n\n"
                f"Pour envoyer : CONFIRMER {self.ticket_id} {self.code}  (expire dans ~{int(self.expires_at - time.time())} s)")


class LiveBroker:
    def __init__(self, settings: Settings, db: Database, spot: KrakenSpotClient, futures: KrakenFuturesClient | None):
        self.s, self.db, self.spot, self.futures = settings, db, spot, futures

    def _guard(self) -> None:
        if not self.s.live_armed:
            raise LiveTradingDisabled("LIVE désactivé (LIVE_TRADING=false ou LIVE_TRADING_ACK absent). "
                                      "Aucun ordre réel ne peut être envoyé.")

    def prepare(self, st: Setup, plan: PositionPlan, inst: Instrument) -> OrderTicket:
        self._guard()
        if not plan.ok:
            raise ValueError("plan invalide")
        if plan.effective_risk_pct > self.s.risk_exceptional_pct + 1e-6 or plan.leverage > self.s.max_leverage:
            raise ValueError("risque ou levier au-delà des plafonds")
        entry = round_price(st.sizing_entry, inst)
        sl = round_price(st.sl, inst)
        size = floor_qty(plan.position_size, inst.lot_decimals)
        side = "buy" if st.direction == "LONG" else "sell"
        if inst.venue == "spot":
            params = {"pair": inst.symbol, "type": side, "ordertype": "limit", "price": f"{entry}",
                      "volume": f"{size}", "close[ordertype]": "stop-loss", "close[price]": f"{sl}"}
            if plan.leverage > 1 or st.direction == "SHORT":
                params["leverage"] = str(max(plan.leverage, 2) if st.direction == "SHORT" else plan.leverage)
            if inst.api_asset_class:
                params["asset_class"] = inst.api_asset_class
            res = self.spot.add_order(params, validate=True)
            validated = f"OK ({res.get('descr', {}).get('order', '')})"
        else:
            params = {"orderType": "lmt", "symbol": inst.symbol, "side": side, "size": size, "limitPrice": entry}
            validated = "non disponible pour les futures (pas de mode validate) — vérifie les valeurs"
        t = OrderTicket(secrets.token_hex(3), f"{secrets.randbelow(10**6):06d}",
                        time.time() + self.s.live_confirmation_ttl_s, inst.venue, inst.symbol, inst.display,
                        st.direction, entry, sl, st.tps, size, plan.leverage, plan.estimated_loss_at_sl_eur,
                        plan.effective_risk_pct, params, validated)
        self.db.kv_set(f"live_ticket:{t.ticket_id}", asdict(t))
        log.warning("LIVE ticket préparé %s %s %s (en attente de confirmation)", t.ticket_id, t.direction, t.display)
        return t

    def execute(self, ticket_id: str, code: str) -> dict:
        self._guard()
        raw = self.db.kv_get(f"live_ticket:{ticket_id}")
        if not raw:
            raise ValueError("ticket inconnu")
        t = OrderTicket(**raw)
        if t.used:
            raise ValueError("ticket déjà utilisé")
        if time.time() > t.expires_at:
            raise ValueError("ticket expiré — relance la préparation")
        if not secrets.compare_digest(code, t.code):
            raise ValueError("code de confirmation incorrect")
        t.used = True
        self.db.kv_set(f"live_ticket:{ticket_id}", asdict(t))
        log.warning("LIVE envoi ordre réel %s %s %s", t.ticket_id, t.direction, t.display)
        if t.venue == "spot":
            res = self.spot.add_order(t.params, validate=False)
            return {"entry_order": res}
        if not self.futures:
            raise ValueError("client futures indisponible")
        res = self.futures.send_order(t.params)
        stop = self.futures.send_order({"orderType": "stp", "symbol": t.symbol,
                                        "side": "sell" if t.direction == "LONG" else "buy", "size": t.size,
                                        "stopPrice": t.sl, "reduceOnly": "true"})
        return {"entry_order": res, "stop_order": stop}
