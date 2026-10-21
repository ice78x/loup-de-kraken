"""Règles SWING (trades de plusieurs jours, bougies journalières), choisies le 19/10 AVANT tout test.

Méthode publique et documentée du suivi de tendance (« Turtle », Donchian) :
  ENTRÉE   clôture du jour au-delà du plus haut (LONG) / plus bas (SHORT) des `entry` jours précédents ;
           on entre le lendemain (ouverture de la bougie suivante).
  STOP     initial = entrée ∓ 2 × N  (N = ATR 20 jours, la « volatilité » des Turtles) ;
           puis stop SUIVEUR mis à jour chaque jour : plus bas (LONG) / plus haut (SHORT) des `exit` derniers jours,
           jamais reculé. Le trade dure tant que la tendance dure — pas d'objectif fixe qui coupe le gain.
  GESTION  « trail » : 100 % suit le stop ; « tp30 » : 30 % encaissés à +2R puis stop au point mort, le reste suit.
Variantes (fixées à l'avance, pas optimisées) : canal 20/10 et 55/20 jours × gestion trail/tp30 × LONG+SHORT ou LONG seul.
Le walk-forward choisit une variante uniquement avec le passé et la juge sur l'avenir.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

VARIANTS: dict[str, dict] = {
    "canal_20_10": {"entry": 20, "exit": 10},
    "canal_55_20": {"entry": 55, "exit": 20},
}
MGMT = ("trail", "tp30")
SIDES = ("both", "long")
ATR_N = 20
STOP_N = 2.0
TP_PARTIAL_R = 2.0
TP_PARTIAL_SHARE = 0.30


def combo_name(variant: str, mgmt: str, sides: str) -> str:
    return f"{variant}|{mgmt}|{sides}"


def parse_combo(name: str) -> tuple[str, str, str]:
    v, m, s = name.split("|")
    return v, m, s


def wilder_atr(df: pd.DataFrame, n: int = ATR_N) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def channels(df: pd.DataFrame, entry: int, exit_: int) -> pd.DataFrame:
    """Canaux calculés sur les jours PRÉCÉDENTS (aucun regard vers le futur : la valeur du jour t n'utilise pas t)."""
    out = pd.DataFrame(index=df.index)
    out["hi_entry"] = df["high"].shift(1).rolling(entry).max()
    out["lo_entry"] = df["low"].shift(1).rolling(entry).min()
    # Stop suiveur : plus bas / plus haut des `exit` derniers jours, jour t INCLUS (connu à la clôture de t,
    # utilisé à partir du jour t+1).
    out["lo_exit"] = df["low"].rolling(exit_).min()
    out["hi_exit"] = df["high"].rolling(exit_).max()
    out["atr"] = wilder_atr(df)
    return out


@dataclass
class SwingSignal:
    direction: str            # LONG | SHORT
    signal_ts: pd.Timestamp   # bougie journalière dont la CLÔTURE a déclenché le signal
    level: float              # plus haut / plus bas cassé
    close: float
    atr: float
    stop: float               # stop initial (par rapport à la clôture du signal ; recalculé sur l'entrée réelle)
    trail: float              # stop suiveur actuel (canal de sortie)


def last_signal(df: pd.DataFrame, variant: str, sides: str = "both") -> SwingSignal | None:
    """Signal sur la DERNIÈRE bougie journalière clôturée de `df` (None si rien)."""
    p = VARIANTS[variant]
    if len(df) < p["entry"] + ATR_N + 2:
        return None
    ch = channels(df, p["entry"], p["exit"])
    c, a = float(df["close"].iloc[-1]), float(ch["atr"].iloc[-1])
    if not np.isfinite(a) or a <= 0:
        return None
    hi, lo = ch["hi_entry"].iloc[-1], ch["lo_entry"].iloc[-1]
    prev_c = float(df["close"].iloc[-2])
    prev_hi, prev_lo = ch["hi_entry"].iloc[-2], ch["lo_entry"].iloc[-2]
    if np.isfinite(hi) and c > hi and not prev_c > prev_hi:
        return SwingSignal("LONG", df.index[-1], float(hi), c, a, c - STOP_N * a, float(ch["lo_exit"].iloc[-1]))
    if sides == "both" and np.isfinite(lo) and c < lo and not prev_c < prev_lo:
        return SwingSignal("SHORT", df.index[-1], float(lo), c, a, c + STOP_N * a, float(ch["hi_exit"].iloc[-1]))
    return None


def next_stop(direction: str, current_stop: float, df_upto: pd.DataFrame, exit_days: int) -> float:
    """Stop suiveur pour le lendemain : canal de sortie, jamais reculé."""
    if direction == "LONG":
        return max(current_stop, float(df_upto["low"].iloc[-exit_days:].min()))
    return min(current_stop, float(df_upto["high"].iloc[-exit_days:].max()))


# --------------------------------------------------------------------------------- mise par paliers (21/10)
# Critères FIXÉS avant le test (classiques du suivi de tendance), tous connus à la clôture du signal :
#   +1 si la clôture casse aussi le plus haut de 55 jours (cassure longue, pas seulement 20 jours)
#   +1 si l'actif est au-dessus de sa moyenne 200 jours (tendance de fond haussière)
#   +1 si le BTC est au-dessus de sa moyenne 200 jours (marché crypto porteur)
# Palier = 1 + nombre de critères → mise 1/4 … 4/4. Le backtest dit si ça aide vraiment (par_palier_*).
SMA_LONG = 200
TIER_RISK = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0}      # % du capital perdu au stop selon le palier (testé le 21/10 : moins bien)
TIER_RISK_V2 = {1: 0.0, 2: 0.5, 3: 1.0, 4: 1.0}   # 21/10 : 1/4 sauté (perdant hors échantillon), 2/4 demi-mise, 3/4 et 4/4 pleine


def above_sma(df: pd.DataFrame | None, n: int = SMA_LONG) -> pd.Series | None:
    if df is None or df.empty:
        return None
    sma = df["close"].rolling(n).mean()
    return (df["close"] > sma) & sma.notna()


def tier_series(df: pd.DataFrame, btc_ok: pd.Series | None = None) -> np.ndarray:
    hi55 = df["high"].shift(1).rolling(55).max()
    c1 = (df["close"] > hi55).fillna(False).to_numpy(bool)
    c2 = above_sma(df).to_numpy(bool)
    if btc_ok is not None:
        c3 = btc_ok.reindex(df.index.normalize(), method="ffill").fillna(False).to_numpy(bool) \
            if not btc_ok.index.equals(df.index) else btc_ok.fillna(False).to_numpy(bool)
    else:
        c3 = np.zeros(len(df), bool)
    return 1 + c1.astype(int) + c2.astype(int) + c3.astype(int)
