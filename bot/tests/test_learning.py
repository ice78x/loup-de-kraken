"""Apprentissage : résultat réel d'un signal rejoué sur des bougies 15 min, et effet sur les scans suivants."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pandas as pd

from kraken_assistant.cloud.learning import live_edges, outcome_row, resolve
from kraken_assistant.config import Settings
from kraken_assistant.scanner.scan import apply_live_edges
from kraken_assistant.strategies.base import TRADE, WATCH, Setup

T0 = pd.Timestamp("2026-10-03T12:00:00Z")
SIG = {"id": 1, "created_at": T0.isoformat(), "expires_at": (T0 + pd.Timedelta(hours=4)).isoformat(), "direction": "LONG",
       "status": "TRADE", "strategy": "cassure_retest", "asset_class": "crypto", "entry_low": 99.0, "entry_high": 100.0,
       "sl": 98.0, "tp1": 102.0, "tp2": 104.0, "tp3": 106.0}
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def bars(rows):
    """rows : liste de (high, low, close) à partir de 12:15."""
    idx = [T0 + pd.Timedelta(minutes=15 * (i + 1)) for i in range(len(rows))]
    return pd.DataFrame({"open": [c for _, _, c in rows], "high": [h for h, _, _ in rows], "low": [lo for _, lo, _ in rows],
                         "close": [c for _, _, c in rows]}, index=idx)


def test_stop_touche_avant_tout():
    r = resolve(SIG, bars([(101, 99.5, 100), (100, 97.5, 98)]), NOW)
    assert r["outcome"] == "sl" and abs(r["r"] - (-1 - 0.035)) < 1e-9     # −1R, moins les frais (0,07 % × 100 / 2 de risque)


def test_tp1_puis_break_even():
    r = resolve(SIG, bars([(100.5, 99.8, 100), (102.5, 100, 102), (101, 99.9, 100)]), NOW)
    assert r["outcome"] == "be" and r["tp_hits"] == 1
    assert abs(r["r"] - (0.3 * 1 - 0.035)) < 1e-9                         # 30 % encaissés à +1R, le reste sorti à 0


def test_tous_les_objectifs():
    r = resolve(SIG, bars([(100.2, 99.5, 100), (103, 100, 103), (107, 103, 106)]), NOW)
    assert r["outcome"] == "tp3" and abs(r["r"] - (0.3 * 1 + 0.4 * 2 + 0.3 * 3 - 0.035)) < 1e-9


def test_meme_bougie_stop_et_objectif_prudence():
    r = resolve(SIG, bars([(100.2, 99.5, 100), (103, 97, 100)]), NOW)
    assert r["outcome"] == "sl"


def test_jamais_entre_puis_expire():
    rows = [(105, 101, 103)] * 20                                          # 5 h au-dessus de la zone
    r = resolve(SIG, bars(rows), NOW)
    assert r["outcome"] == "non_entre" and r["r"] is None


def test_pas_encore_termine():
    assert resolve(SIG, bars([(100.5, 99.5, 100), (101, 99.6, 100.5)]), NOW) is None


def test_ligne_et_statistiques():
    row = outcome_row(SIG, resolve(SIG, bars([(101, 99.5, 100), (100, 97.5, 98)]), NOW))
    assert row["outcome"] == "sl" and row["hour_paris"] == 14 and row["weekday"] == 5 and abs(row["sl_pct"] - 2) < 1e-9
    e = live_edges([{"status": "TRADE", "strategy": "cassure_retest", "asset_class": "crypto", "n": 20, "win_rate": 35, "avg_r": -0.3},
                    {"status": "WATCH", "strategy": "x", "asset_class": "crypto", "n": 9, "win_rate": 50, "avg_r": 0.1}])
    assert list(e) == ["cassure_retest|crypto"]


def test_une_combinaison_perdante_ne_donne_plus_de_vert():
    s = Settings(_env_file=None).model_copy(update={"live_edges": {"cassure_retest|crypto": {"n": 20, "win_rate": 35.0, "avg_r": -0.3},
                                                                   "rejet_sweep|crypto": {"n": 5, "win_rate": 20.0, "avg_r": -0.8}}})
    mk = lambda strat: Setup(inst_key="k", display="X", asset_class="crypto", strategy=strat, direction="LONG", entry_low=1,  # noqa: E731
                             entry_high=1, sl=0.9, tps=[1.2], invalidation_price=0.9, invalidation_text="", action="", status=TRADE)
    a, b = mk("cassure_retest"), mk("rejet_sweep")
    apply_live_edges([a, b], s)
    assert a.status == WATCH and "perd en vrai" in a.rejections[0] and "20 trades" in a.edge_note
    assert b.status == TRADE                                               # 5 trades : pas assez pour juger


def test_signal_enregistre_des_sa_publication_avec_son_contexte():
    from kraken_assistant.cloud.learning import EN_COURS, pending_rows
    st = Setup(inst_key="k", display="PF_TAOUSD", asset_class="crypto", strategy="rejet_sweep", direction="LONG", entry_low=304.9,
               entry_high=305.5, sl=302.8, tps=[308.4, 310.6, 312.5], invalidation_price=302.8, invalidation_text="", action="",
               status=TRADE, score=72, confirmed=True, components={"structure": 16, "volume": 8})
    a = NS(price=305.6, atr15=1.2, rsi1h=55.0, rsi15=60.0, rvol15_last=1.4, vwap15=305.0,
           vol=NS(atr_1h_pct=0.9, regime="normale"), structures={"4h": NS(trend="up", ema_bias="up"), "1h": NS(trend="range", ema_bias="up")},
           htf=NS(daily_trend="up", weekly_trend="range", range_position=0.6),
           catalyst=NS(label=lambda: "aucun", has_major=False), liquidity=NS(volume_24h_eur=5e6, spread_pct=0.02))
    row = {"id": 42, "created_at": "2026-10-04T08:20:00+00:00", "instrument_key": "futures:PF_TAOUSD", "display": "PF_TAOUSD",
           "asset_class": "crypto", "strategy": "rejet_sweep", "direction": "LONG", "status": "TRADE", "score": 72,
           "entry_low": 304.9, "entry_high": 305.5, "sl": 302.8, "tp1": 308.4, "tp2": 310.6, "tp3": 312.5}
    [p] = pending_rows([row], [(st, a, "normal")])
    assert p["signal_id"] == 42 and p["outcome"] == EN_COURS and p["r"] is None
    assert p["hour_paris"] == 10 and p["weekday"] == 6
    f = p["features"]
    assert f["composantes"]["structure"] == 16 and f["tendance"] == {"4h": "up", "1h": "range"} and f["au_dessus_vwap"] is True
    assert f["rr"] == st.r_multiples() and abs(f["atr15_pct"] - 1.2 / 305.6 * 100) < 1e-3
