"""Scheduler configurable (thread) : scan complet toutes les SCAN_INTERVAL_MINUTES (défaut 60) et veille
"scan urgent" toutes les WATCH_INTERVAL_MINUTES (défaut 10). Un seul scan à la fois (verrou)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .app import App
from .scanner.scan import scan
from .scanner.urgent import watch_tick

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, app: App):
        self.app = app
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()
        log.info("scheduler démarré (scan %d min, veille %d min)", self.app.settings.scan_interval_minutes,
                 self.app.settings.watch_interval_minutes)

    def stop(self) -> None:
        self._stop.set()

    def _maybe_optimize(self) -> None:
        """Ré-optimisation nocturne sur tout l'historique local (thread séparé, n'empêche pas les scans)."""
        s = self.app.settings
        if not s.optimizer_enabled:
            return
        from zoneinfo import ZoneInfo
        local = datetime.now(ZoneInfo(s.timezone))
        last = self.app.db.kv_get("last_optimization")
        if local.hour != s.optimizer_hour_local or (last and last[:10] == datetime.now(timezone.utc).date().isoformat()):
            return
        if getattr(self, "_opt_thread", None) and self._opt_thread.is_alive():
            return
        from .commands import execute

        def job() -> None:
            log.info("optimisation nocturne : démarrage")
            log.info(execute(self.app, "OPTIMISER"))
        self._opt_thread = threading.Thread(target=job, name="optimizer", daemon=True)
        self._opt_thread.start()

    def _run(self) -> None:
        s = self.app.settings
        next_scan = datetime.now(timezone.utc) + timedelta(seconds=5)
        next_watch = datetime.now(timezone.utc) + timedelta(minutes=s.watch_interval_minutes)
        self.app.state["next_scan_at"] = next_scan
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            try:
                if now >= next_scan:
                    scan(self.app)
                    next_scan = datetime.now(timezone.utc) + timedelta(minutes=s.scan_interval_minutes)
                    next_watch = datetime.now(timezone.utc) + timedelta(minutes=s.watch_interval_minutes)
                    self.app.state["next_scan_at"] = next_scan
                elif now >= next_watch:
                    watch_tick(self.app)
                    next_watch = datetime.now(timezone.utc) + timedelta(minutes=s.watch_interval_minutes)
                self._maybe_optimize()
            except RuntimeError as e:  # scan déjà en cours
                log.info("scheduler : %s", e)
            except Exception:  # le scheduler ne doit jamais mourir silencieusement
                log.exception("scheduler : erreur pendant le cycle")
                next_scan = datetime.now(timezone.utc) + timedelta(minutes=5)
            self._stop.wait(10)


def run_forever(app: App) -> None:
    sch = Scheduler(app)
    sch.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sch.stop()
