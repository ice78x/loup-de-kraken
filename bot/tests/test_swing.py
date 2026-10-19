"""Moteur SWING (19/10) : simulation journalière, stop suiveur, funding, walk-forward. Données SYNTHÉTIQUES."""
import numpy as np
import pandas as pd
import pytest

from kraken_assistant.swing import rules as R
from kraken_assistant.swing.backtest import SwingParams, daily_funding, portfolio, report, simulate, walk_forward


def _df(closes, spread=0.01):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1D", tz="UTC")
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * (1 + spread), "low": np.minimum(o, c) * (1 - spread),
                         "close": c, "volume": 1.0}, index=idx)


def _range_then_trend(n_range=80, n_trend=60, step=0.01, seed=3):
    rng = np.random.default_rng(seed)
    r = 100 + rng.uniform(-1, 1, n_range)
    t = r[-1] * np.cumprod(np.full(n_trend, 1 + step))
    return np.r_[r, t]


def test_tendance_haussiere_un_long_gagnant_qui_dure():
    df = _df(_range_then_trend())
    tr = simulate(df, None, "k", "crypto", "canal_20_10", "trail", "both", SwingParams(slippage_pct=0, fee_taker_pct=0))
    longs = [t for t in tr if t.direction == "LONG"]
    assert longs and longs[0].r > 2 and longs[0].days > 20


def test_entree_le_lendemain_du_signal_jamais_le_jour_meme():
    df = _df(_range_then_trend())
    t = simulate(df, None, "k", "crypto", "canal_20_10", "trail", "long", SwingParams())[0]
    ch = R.channels(df, 20, 10)
    sig_day = df.index.get_loc(t.entry_ts) - 1
    assert df["close"].iloc[sig_day] > ch["hi_entry"].iloc[sig_day]            # le signal est la clôture de la VEILLE


def test_funding_positif_coute_aux_longs():
    df = _df(_range_then_trend())
    p = SwingParams(slippage_pct=0, fee_taker_pct=0)
    sans = simulate(df, None, "k", "crypto", "canal_20_10", "trail", "long", p)[0]
    fund = pd.Series(0.0003, index=df.index)                                     # 0,03 % par jour
    avec = simulate(df, fund, "k", "crypto", "canal_20_10", "trail", "long", p)[0]
    assert avec.r < sans.r and avec.funding_r < 0


def test_funding_horaire_converti_par_jour():
    idx = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    rates = [{"timestamp": f"2024-01-01T{h:02d}:00:00Z", "relativeFundingRate": 0.00001} for h in range(24)]
    f = daily_funding(rates, idx)
    assert f.iloc[0] == pytest.approx(0.00024) and np.isnan(f.iloc[1])         # 24 h × 0,001 %, rien inventé le jour 2
    four_h = [{"timestamp": f"2024-01-01T{h:02d}:00:00Z", "relativeFundingRate": 0.00001} for h in range(0, 24, 4)]
    assert daily_funding(four_h, idx).iloc[0] == pytest.approx(0.00024)         # taux horaire publié toutes les 4 h


def test_stop_suiveur_ne_recule_jamais_et_coupe_la_perte():
    up = _range_then_trend(n_trend=30)
    down = up[-1] * np.cumprod(np.full(30, 0.97))
    df = _df(np.r_[up, down])
    t = [x for x in simulate(df, None, "k", "crypto", "canal_20_10", "trail", "long", SwingParams()) if x.direction == "LONG"][0]
    assert t.exit_reason == "stop" and t.r > 0                                 # le stop suiveur a gardé une partie du gain


def test_tp30_encaisse_puis_point_mort():
    df = _df(_range_then_trend())
    t = simulate(df, None, "k", "crypto", "canal_20_10", "tp30", "long", SwingParams(slippage_pct=0, fee_taker_pct=0, fee_maker_pct=0))[0]
    full = simulate(df, None, "k", "crypto", "canal_20_10", "trail", "long", SwingParams(slippage_pct=0, fee_taker_pct=0, fee_maker_pct=0))[0]
    assert 0 < t.r < full.r                                                     # en tendance forte, encaisser tôt rapporte moins


def test_portefeuille_respecte_2_pourcent_de_risque_ouvert():
    from kraken_assistant.swing.backtest import SwingTrade
    d = lambda s: pd.Timestamp(s, tz="UTC")
    mk = lambda k, a, b: SwingTrade(k, "x", "LONG", d(a), d(b), 1.0, "stop", "", "crypto", risk_path={})
    tr = [mk("a", "2024-01-01", "2024-02-01"), mk("b", "2024-01-02", "2024-02-01"), mk("c", "2024-01-03", "2024-02-01")]
    assert [t.key for t in portfolio(tr, 2.0)] == ["a", "b"]                   # 3e refusé : déjà 2 % de risque ouvert
    tr[0].risk_path = {d("2024-01-02"): 0.0}                                    # stop de « a » au point mort
    assert [t.key for t in portfolio(tr, 2.0)] == ["a", "b", "c"]


def test_rapport_complet_et_walk_forward_sans_futur():
    data = {f"k{i}": ("crypto", _df(np.r_[_range_then_trend(seed=i), _range_then_trend(seed=i + 50)[::-1]]), None)
            for i in range(6)}
    rep = report(data, SwingParams(min_trades_select=3, min_oos_trades=1, folds=3))
    assert rep["type"] == "swing" and "crypto" in rep["par_classe"]
    c = rep["par_classe"]["crypto"]
    assert set(c) >= {"walk_forward", "variante_retenue", "prouve", "par_annee", "portefeuille_club"}
    assert len(rep["variantes"]) == len(R.VARIANTS) * len(R.MGMT) * len(R.SIDES)


def test_signal_en_direct_sur_la_derniere_bougie():
    closes = _range_then_trend(n_trend=1, step=0.05)
    sig = R.last_signal(_df(closes), "canal_20_10")
    assert sig and sig.direction == "LONG" and sig.stop < sig.close and sig.trail < sig.close
    assert R.last_signal(_df(_range_then_trend(n_trend=5, step=0.05)), "canal_20_10") is None   # cassure déjà ancienne
