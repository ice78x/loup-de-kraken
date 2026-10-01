"""Dashboard web (FastAPI) + API de commandes. Écoute sur 127.0.0.1 par défaut (usage local uniquement)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..api.errors import DataUnavailable
from ..app import App
from ..commands import execute
from ..risk.daily_loss import realized_pnl_today
from ..scanner.formatter import format_report, format_signal, format_watch
from ..scheduler import Scheduler

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class Command(BaseModel):
    command: str


def dashboard_payload(app: App) -> dict:
    s = app.settings
    try:
        cap = app.capital()
    except DataUnavailable as e:
        cap = {"mode": "?", "risk_capital_eur": None, "error": str(e)}
    positions = app.positions.open_positions(include_pending=True)
    snap = None
    if cap.get("risk_capital_eur"):
        snap = app.risk.snapshot(cap["risk_capital_eur"], [p for p in positions if p.status == "open"],
                                 realized_pnl_today(app.db, s.timezone))
    rep = app.state.get("last_report")
    last, nxt = app.state.get("last_scan_at"), app.state.get("next_scan_at")
    return {
        "mode": "LIVE ARMÉ" if s.live_armed else "PAPER / ANALYSE",
        "capital": cap,
        "risk": None if not snap else {
            "open_eur": snap.open_risk_eur, "open_pct": snap.open_risk_pct, "available_eur": snap.available_risk_eur,
            "available_pct": round(snap.available_risk_pct, 2), "today_eur": snap.realized_today_eur,
            "daily_limit_eur": snap.daily_limit_eur, "daily_limit_hit": snap.daily_limit_hit, "notes": snap.notes},
        "positions": [{"id": p.id, "display": p.display, "direction": p.direction, "status": p.status,
                       "source": p.source, "entry": p.entry, "sl": p.sl} for p in positions],
        "verdict": rep.verdict if rep else None,
        "report_text": format_report(rep) if rep else None,
        "signals": [{"id": t.signal_id, "text": format_signal(t)} for t in rep.trades] if rep else [],
        "watch": [format_watch(w) for w in rep.watch] if rep else [],
        "opportunities": rep.opportunities[:40] if rep else [],
        "news": [{"title": n.title, "source": n.source, "published": n.published_at.isoformat(),
                  "verified": n.verified, "impact": n.impact_label, "assets": n.assets,
                  "fact": n.fact, "interpretation": n.interpretation, "url": n.url}
                 for n in (rep.news if rep else [])][:10],
        "last_scan": last.isoformat() if last else None,
        "next_scan": nxt.isoformat() if nxt else None,
        "data_issues": rep.data_issues[:10] if rep else [],
    }


def create_app(app: App | None = None, start_scheduler: bool | None = None) -> FastAPI:
    core = app or App.build()
    sched = Scheduler(core)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if core.settings.scheduler_enabled if start_scheduler is None else start_scheduler:
            sched.start()
        yield
        sched.stop()

    api = FastAPI(title="Kraken Assistant", lifespan=lifespan)

    @api.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @api.get("/api/dashboard")
    async def dashboard() -> JSONResponse:
        try:
            return JSONResponse(await run_in_threadpool(dashboard_payload, core))
        except Exception as e:
            log.exception("dashboard : erreur")
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    @api.post("/api/command")
    async def command(c: Command) -> JSONResponse:
        text = await run_in_threadpool(execute, core, c.command)
        return JSONResponse({"text": text})

    @api.get("/api/health")
    def health() -> dict:
        return {"ok": True, "live_armed": core.settings.live_armed}

    api.state.core = core
    return api
