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
