import pandas as pd
import pytest

from conftest import make_df
from kraken_assistant.api.errors import LiveTradingDisabled
from kraken_assistant.database.db import Database
from kraken_assistant.execution.live import LiveBroker
from kraken_assistant.execution.paper import PaperBroker
from kraken_assistant.portfolio.pnl import paper_stats
from kraken_assistant.risk.position_sizing import SizingInput, compute_position
from kraken_assistant.scanner.formatter import _check
from kraken_assistant.strategies.base import ACTION_ENTER, Setup


def setup_long():
    return Setup(inst_key="spot:TESTEUR", display="TEST/EUR", asset_class="crypto", strategy="cassure_retest",
                 direction="LONG", entry_low=99.5, entry_high=100.0, sl=98.0, tps=[102.0, 104.0, 106.0],
                 invalidation_price=98.5, invalidation_text="Clôture 15m sous 98.5", action=ACTION_ENTER)


def plan_for(st, fee=0.0):
    return compute_position(SizingInput(capital_eur=90, risk_percent=1, entry=st.sizing_entry, stop_loss=st.sl,
                                        direction=st.direction, take_profits=st.tps, fee_rate_pct=fee,
                                        allowed_leverages=[1, 2, 3], max_leverage=10))


@pytest.fixture
def broker(settings, tmp_path):
    db = Database(tmp_path / "p.db")
    return PaperBroker(db, settings.model_copy(update={"paper_auto_manage": False})), db


def bars(rows, start):
    return make_df(rows, start=start, freq="5min")


def test_paper_tp_partiels_puis_sl_break_even(broker):
    br, db = broker
    st = setup_long()
    plan = plan_for(st)
    pid = br.open_from_setup(st, plan, 1.0, 0.0, bid=99.7, ask=99.8, signal_id=None, base="TEST", catalyst=None)
    p = br.store.get(pid)
    assert p.status == "open" and p.entry == 99.8           # exécuté au prix réel du carnet (ask)
    created = pd.Timestamp(db.one("SELECT created_at FROM positions WHERE id=?", (pid,))["created_at"])
    b = bars([(99.8, 102.1, 99.7, 102.0)], created.floor("5min"))  # TP1 touché
    br.update(pid, b, None, None, now=created + pd.Timedelta(minutes=10))
    p = br.store.get(pid)
    assert p.tp1_hit and p.qty_remaining == pytest.approx(plan.position_size * 0.7)
    br.move_sl(pid, p.entry, "BE")
    b2 = bars([(102.0, 102.2, 99.0, 99.2)], created.floor("5min") + pd.Timedelta(minutes=10))  # retour sous BE
    br.update(pid, b2, None, None, now=created + pd.Timedelta(minutes=20))
    p = br.store.get(pid)
    assert p.status == "closed"
    expected = plan.position_size * 0.3 * (102.0 - 99.8)       # gain TP1, reste sorti à BE
    assert p.realized_pnl_eur == pytest.approx(expected, abs=1e-6)
    st_ = paper_stats(db, 90.0)
    assert st_["trades"] == 1 and st_["gagnants"] == 1


def test_paper_sl_avant_tp_dans_la_meme_bougie(broker):
    br, db = broker
    st = setup_long()
    plan = plan_for(st)
    pid = br.open_from_setup(st, plan, 1.0, 0.0, bid=99.9, ask=100.0, signal_id=None, base="TEST", catalyst=None)
    created = pd.Timestamp(db.one("SELECT created_at FROM positions WHERE id=?", (pid,))["created_at"])
    br.update(pid, bars([(100.0, 102.5, 97.5, 101.0)], created.floor("5min")), None, None,
              now=created + pd.Timedelta(minutes=10))
    p = br.store.get(pid)
    assert p.status == "closed"
    assert p.realized_pnl_eur == pytest.approx(-plan.estimated_loss_at_sl_eur, abs=1e-6)  # prudence : SL d'abord


def test_paper_ordre_limite_puis_execution(broker):
    br, db = broker
    st = setup_long()
    pid = br.open_from_setup(st, plan_for(st), 1.0, 0.0, bid=100.9, ask=101.0, signal_id=None, base="TEST", catalyst=None)
    assert br.store.get(pid).status == "pending"            # prix au-dessus de la zone → limite
    created = pd.Timestamp(db.one("SELECT created_at FROM positions WHERE id=?", (pid,))["created_at"])
    br.update(pid, bars([(100.8, 100.9, 99.9, 100.2)], created.floor("5min")), None, None,
              now=created + pd.Timedelta(minutes=10))
    p = br.store.get(pid)
    assert p.status == "open" and p.entry == 100.0


def test_paper_frais(broker):
    br, db = broker
    st = setup_long()
    plan = plan_for(st, fee=0.4)
    pid = br.open_from_setup(st, plan, 1.0, 0.4, bid=99.9, ask=100.0, signal_id=None, base="TEST", catalyst=None)
    created = pd.Timestamp(db.one("SELECT created_at FROM positions WHERE id=?", (pid,))["created_at"])
    br.update(pid, bars([(100.0, 100.1, 97.9, 98.0)], created.floor("5min")), None, None,
              now=created + pd.Timedelta(minutes=10))
    p = br.store.get(pid)
    assert p.realized_pnl_eur == pytest.approx(-plan.estimated_loss_at_sl_eur, abs=1e-6)
    assert p.realized_pnl_eur >= -0.90 - 1e-9


def test_live_desactive_par_defaut(settings, tmp_path):
    assert settings.live_trading is False and not settings.live_armed
    lb = LiveBroker(settings, Database(tmp_path / "l.db"), None, None)
    with pytest.raises(LiveTradingDisabled):
        lb.prepare(setup_long(), plan_for(setup_long()), None)
    with pytest.raises(LiveTradingDisabled):
        lb.execute("abc", "123456")


def test_live_exige_la_phrase_d_accuse(settings):
    s = settings.model_copy(update={"live_trading": True})
    assert not s.live_armed                                  # LIVE_TRADING=true seul ne suffit pas
    s2 = s.model_copy(update={"live_trading_ack": "J_ACCEPTE_LE_RISQUE_REEL"})
    assert s2.live_armed


def test_vocabulaire_interdit_filtre():
    out = _check("Ceci est un trade sûr, gain garanti, aucun risque")
    for w in ("trade sûr", "gain garanti", "aucun risque"):
        assert w not in out.lower()
