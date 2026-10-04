"""Scan de bout en bout contre un faux Kraken (données SYNTHÉTIQUES, voir fake_kraken.py)."""
import httpx
import pytest

from fake_kraken import FakeKraken, down
from kraken_assistant.app import App
from kraken_assistant.commands import execute
from kraken_assistant.database.db import Database
from kraken_assistant.scanner.formatter import FORBIDDEN, format_report
from kraken_assistant.scanner.scan import scan


def build(settings, tmp_path, seed=0, news_ok=False):
    fk = FakeKraken(seed)
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": False,
                                    "min_volume_24h_eur_crypto": 1000, "min_volume_24h_eur_other": 100})
    app = App.build(s, spot_transport=httpx.MockTransport(fk.handler), news_transport=httpx.MockTransport(down),
                    db=Database(tmp_path / f"e2e{seed}.db"))
    app.spot.http.retries = 0
    return app, fk


def test_scan_complet_mode_paper(settings, tmp_path):
    app, fk = build(settings, tmp_path)
    rep = scan(app)
    assert rep.verdict in ("TRADE", "WATCH", "NONE")
    assert rep.counts["analysés"] >= 5                        # crypto + xStock + matière première
    classes = {o["asset_class"] for o in rep.opportunities}
    assert {"crypto", "xstock", "commodity"} <= classes
    assert any("news absentes" in d for d in rep.data_issues)   # news indisponibles signalées, pas inventées
    text = format_report(rep)
    assert text.splitlines()[0].startswith(("🟢", "🟡", "🛑", "🔴"))
    assert not any(f in text.lower() for f in FORBIDDEN)
    assert app.db.one("SELECT COUNT(*) AS n FROM scans")["n"] == 1


@pytest.mark.parametrize("seed", range(8))
def test_proprietes_des_signaux(settings, tmp_path, seed):
    """Sur plusieurs marchés synthétiques : tout signal émis respecte les règles de risque."""
    app, _ = build(settings, tmp_path, seed)
    rep = scan(app)
    total = 0.0
    for sig in rep.trades:
        st, p = sig.setup, sig.plan
        assert st.confirmed and not st.rejections
        assert p.estimated_loss_at_sl_eur <= 90 * 0.02 + 1e-9
        assert p.leverage <= 10
        rs = st.r_multiples()
        assert rs[0] >= settings.min_rr_tp1 and rs[1] >= settings.min_rr_tp2
        if st.direction == "LONG":
            assert st.sl < st.entry_low <= st.entry_high < st.tps[0] < st.tps[1] < st.tps[2]
        else:
            assert st.sl > st.entry_high >= st.entry_low > st.tps[0] > st.tps[1] > st.tps[2]
        total += p.estimated_loss_at_sl_eur
        assert sig.signal_id is not None
    assert total <= 90 * 0.02 + 1e-6                          # risque cumulé des signaux proposés ≤ 2 %


def test_api_injoignable_donne_data_insuffisante(settings, tmp_path):
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": False})
    app = App.build(s, spot_transport=httpx.MockTransport(down), news_transport=httpx.MockTransport(down),
                    db=Database(tmp_path / "down.db"))
    app.spot.http.retries = 0
    rep = scan(app)
    assert rep.verdict == "DATA"
    assert format_report(rep).startswith("🛑 DATA INSUFFISANTE — PAS DE TRADE")
    assert not rep.trades


def test_commandes(settings, tmp_path):
    app, _ = build(settings, tmp_path, 3)
    assert execute(app, "SCAN").splitlines()[0][0] in "🟢🟡🛑🔴"
    for c in ("POSITIONS", "RISQUE", "PORTFOLIO", "STATUS", "JOURNAL", "PAPER STATS", "CALC 90 1 100 98", "AIDE"):
        out = execute(app, c)
        assert out and "Traceback" not in out
    assert "🔒" in execute(app, "CONFIRMER abc 123456")      # live verrouillé
    rep = app.state["last_report"]
    if rep.trades:
        out = execute(app, f"PAPER OPEN {rep.trades[0].signal_id}")
        assert "PAPER #" in out
        assert "POSITIONS" in execute(app, "POSITIONS")


def test_historique_s_accumule_et_commandes_optimiseur(settings, tmp_path):
    app, _ = build(settings, tmp_path, 5)
    scan(app)
    cov = app.history.store.coverage()
    tfs = {r["tf"] for r in cov}
    assert {"5m", "1h", "1d", "1w"} <= tfs                     # live + contexte long terme stockés
    n1 = sum(r["n"] for r in cov)
    scan(app)
    assert sum(r["n"] for r in app.history.store.coverage()) >= n1  # jamais de perte d'historique
    rep = app.state["last_report"]
    assert any(o.get("1d") for o in rep.opportunities)
    assert "HISTORIQUE LOCAL" in execute(app, "HISTORIQUE")
    out = execute(app, "OPTIMISER")
    assert "OPTIMIS" in out and "Traceback" not in out
    assert "OPTIMISER" in execute(app, "EDGE") or "EDGE" in execute(app, "EDGE")


def test_scan_avec_futures(settings, tmp_path):
    """Chemin futures complet (instruments, tickers, bougies 5m/1h/1j/1sem, carnet) — régression du bug 1w."""
    fk = FakeKraken(7)
    s = settings.model_copy(update={"public_min_interval_s": 0, "futures_enabled": True,
                                    "min_volume_24h_eur_crypto": 1000, "min_volume_24h_eur_other": 100})
    t = httpx.MockTransport(fk.handler)
    app = App.build(s, spot_transport=t, futures_transport=t, news_transport=httpx.MockTransport(down),
                    db=Database(tmp_path / "fut.db"))
    rep = scan(app)
    assert rep.verdict in ("TRADE", "WATCH", "NONE")
    assert any(o["key"] == "futures:PF_SOLUSD" for o in rep.opportunities)
    assert {"1d", "1w"} <= {r["tf"] for r in app.history.store.coverage("futures:PF_SOLUSD")}
    assert "Traceback" not in execute(app, "SCAN")


def test_paires_usd_uniquement_par_defaut(settings, tmp_path):
    """Réglage par défaut (classification.toml) : seules les paires contre USD sont analysées ; le taux EUR/USD
    vient de la paire forex Kraken même si elle n'est pas un instrument tradé."""
    fk = FakeKraken(2)
    s = settings.model_copy(update={"quote_currencies": [], "public_min_interval_s": 0, "futures_enabled": False,
                                    "min_volume_24h_eur_crypto": 1000, "min_volume_24h_eur_other": 100})
    app = App.build(s, spot_transport=httpx.MockTransport(fk.handler), news_transport=httpx.MockTransport(down),
                    db=Database(tmp_path / "usd.db"))
    assert app.taxonomy.quotes == ["USD"]
    rep = scan(app)
    assert rep.opportunities and all(o["display"].endswith("/USD") for o in rep.opportunities)
    assert {o["display"] for o in rep.opportunities} >= {"BTC/USD", "TSLAx/USD"}
    usd_eur = float(fk.series["ZEURZUSD"]["close"].iloc[-1])
    assert rep.fx["USD"] == pytest.approx(1 / usd_eur, rel=1e-3)
    assert not any("EUR/USD" in o["display"] for o in rep.opportunities)


def test_verification_express_une_seule_paire(settings, tmp_path):
    """Bouton « Vérifier ce setup » : le bot n'analyse que la paire demandée (plus rapide)."""
    app, _ = build(settings, tmp_path)
    full = scan(app)
    key = next(o for o in full.opportunities if o["asset_class"] == "crypto")
    k = next(i.key for i in app.discovery.discover() if i.display == key["display"])
    rep = scan(app, mode="cible", focus={k})
    assert rep.mode == "cible"
    assert rep.counts["analysés"] == 1
    assert {o["display"] for o in rep.opportunities} <= {key["display"]}


def test_les_setups_refuses_ne_sont_pas_publies_en_surveiller(settings, tmp_path):
    """Ex. XAUT du 04/10 : stop éloigné à 0,35 % → R:R 0,1 / 0,2 → refusé : il ne doit pas apparaître en 🟡."""
    from kraken_assistant.scanner.scan import REFUS_DEFINITIFS
    for seed in range(4):
        app, _ = build(settings, tmp_path, seed)
        rep = scan(app)
        for w in rep.watch:
            assert not any(any(k in r for k in REFUS_DEFINITIFS) for r in w.rejections), (w.display, w.rejections)
