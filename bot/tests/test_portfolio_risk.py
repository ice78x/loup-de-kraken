from datetime import datetime, timezone

import pytest

from kraken_assistant.database.db import Database
from kraken_assistant.portfolio.positions import Position
from kraken_assistant.risk.daily_loss import realized_pnl_today
from kraken_assistant.risk.portfolio_risk import PortfolioRiskManager


def pos(pid=1, base="LINK", direction="SHORT", entry=14.25, sl=14.70, qty=2.0, epq=1.0, fee=0.0, asset="crypto"):
    return Position(id=pid, source="paper", instrument_key=f"spot:{base}EUR", display=f"{base}/EUR", base=base,
                    venue="spot", asset_class=asset, direction=direction, entry=entry, qty_initial=qty,
                    qty_remaining=qty, sl=sl, tp1=None, tp2=None, tp3=None, tp1_hit=False, tp2_hit=False,
                    tp3_hit=False, status="open", eur_per_quote=epq, fee_rate_pct=fee, realized_pnl_eur=0.0)


def test_risque_ouvert_et_disponible(settings):
    rm = PortfolioRiskManager(settings)
    snap = rm.snapshot(90.0, [pos()], 0.0)          # risque = 2 × 0,45 = 0,90 €
    assert snap.open_risk_eur == pytest.approx(0.90)
    assert snap.available_risk_eur == pytest.approx(0.90)   # max 1,80 € (2 %)
    d = rm.allowed_risk_pct(snap, exceptional=False)
    assert d.ok and d.risk_pct == pytest.approx(1.0)
    d2 = rm.allowed_risk_pct(snap, exceptional=True)          # 2 % demandé mais seulement 1 % dispo
    assert d2.ok and d2.risk_pct == pytest.approx(1.0) and d2.warnings


def test_risque_cumule_plein(settings):
    rm = PortfolioRiskManager(settings)
    snap = rm.snapshot(90.0, [pos(1), pos(2, base="BRENT", direction="LONG", entry=80, sl=79.1, qty=1.0, asset="commodity")], 0.0)
    assert snap.open_risk_eur == pytest.approx(1.80)
    d = rm.allowed_risk_pct(snap, False)
    assert not d.ok and "risque cumulé" in d.reasons[0]


def test_sl_break_even_libere_le_risque(settings):
    rm = PortfolioRiskManager(settings)
    p = pos(sl=14.25)  # SL au prix d'entrée
    assert rm.snapshot(90.0, [p], 0.0).open_risk_eur == pytest.approx(0.0)


def test_sl_inconnu_compte_par_hypothese(settings):
    rm = PortfolioRiskManager(settings)
    snap = rm.snapshot(90.0, [pos(sl=None)], 0.0)
    assert snap.open_risk_eur == pytest.approx(0.90)
    assert snap.notes


def test_perte_journaliere_stop(settings):
    rm = PortfolioRiskManager(settings)
    snap = rm.snapshot(90.0, [], -2.70)             # -3 % atteint
    assert snap.daily_limit_hit
    assert not rm.allowed_risk_pct(snap, False).ok
    snap2 = rm.snapshot(90.0, [], -2.0)              # reste 0,70 € avant la limite
    assert snap2.available_risk_eur == pytest.approx(0.70)
    d = rm.allowed_risk_pct(snap2, False)
    assert d.ok and d.risk_pct == pytest.approx(0.70 / 90 * 100, abs=1e-3)


def test_correlation_bloque(settings):
    rm = PortfolioRiskManager(settings)
    snap = rm.snapshot(90.0, [pos(1, base="ETH", direction="LONG", entry=100, sl=98, qty=0.45)], 0.0)
    assert not rm.check_candidate(snap, "BTC", "LONG", {1: 0.9}).ok              # double exposition
    assert not rm.check_candidate(snap, "BTC", "SHORT", {1: 0.9}).ok             # contradictoire
    assert rm.check_candidate(snap, "BTC", "LONG", {1: 0.3}).ok
    assert not rm.check_candidate(snap, "ETH", "LONG", {}).ok                    # même actif


def test_daily_loss_depuis_la_base(tmp_path):
    db = Database(tmp_path / "t.db")
    pid = db.insert("positions", {"source": "paper", "instrument_key": "spot:X", "direction": "LONG", "status": "closed"})
    now = datetime.now(timezone.utc)
    db.insert("fills", {"position_id": pid, "ts": now.isoformat(), "kind": "sl", "pnl_eur": -0.9})
    db.insert("fills", {"position_id": pid, "ts": "2020-01-01T00:00:00+00:00", "kind": "sl", "pnl_eur": -5})
    assert realized_pnl_today(db, "Europe/Paris", now) == pytest.approx(-0.9)


def test_avoirs_spot_hors_budget_puis_geres(tmp_path):
    from kraken_assistant.portfolio.positions import PositionStore
    db = Database(tmp_path / "h.db")
    pid = db.insert("positions", {"source": "kraken_spot", "external_id": "BTC", "instrument_key": "spot:XXBTZEUR",
                                  "display": "BTC/EUR", "direction": "LONG", "qty_initial": 0.001,
                                  "qty_remaining": 0.001, "status": "holding"})
    store = PositionStore(db)
    assert store.open_positions() == [] and len(store.holdings()) == 1
    store.set_levels(pid, entry=50000.0, sl=48000.0)
    assert [p.id for p in store.open_positions()] == [pid]
