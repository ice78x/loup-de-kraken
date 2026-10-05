"""Configuration centrale (variables d'environnement + fichiers TOML).

Les secrets sont des SecretStr : ils ne s'affichent jamais dans un repr/log.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_ACK_PHRASE = "J_ACCEPTE_LE_RISQUE_REEL"
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # dossier du projet (install éditable)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(PROJECT_ROOT / ".env", ".env"), env_file_encoding="utf-8",
                                      extra="ignore")

    # --- API ---
    kraken_api_key: SecretStr = SecretStr("")
    kraken_api_secret: SecretStr = SecretStr("")
    kraken_futures_api_key: SecretStr = SecretStr("")
    kraken_futures_api_secret: SecretStr = SecretStr("")
    finnhub_api_key: SecretStr = SecretStr("")
    spot_base_url: str = "https://api.kraken.com"
    futures_base_url: str = "https://futures.kraken.com"
    country_code: str = "FR"
    http_timeout_s: float = 15.0
    public_min_interval_s: float = 1.05  # ~1 req/s sur l'API publique spot
    user_agent: str = "kraken-assistant/0.1 (personal research tool)"

    # --- Capital & risque ---
    capital_eur: float = 90.0
    risk_normal_pct: float = 1.0
    risk_exceptional_pct: float = 2.0
    risk_min_pct: float = 0.5  # en dessous, le budget restant est jugé trop faible
    max_open_risk_pct: float = 2.0
    max_daily_loss_pct: float = 3.0
    max_leverage: int = 10
    default_spot_taker_fee_pct: float = 0.80  # spot crypto, niveau d'entrée (grille du 09/07/2026)
    default_futures_taker_fee_pct: float = 0.05
    default_spot_maker_fee_pct: float = 0.40
    default_futures_maker_fee_pct: float = 0.02
    # Les membres tradent les signaux crypto sur les futures perpétuels Kraken (PF_…) : frais futures pour ces paires.
    # "spot" pour revenir aux frais spot (0,40 / 0,80 %).
    execution_venue: str = "futures"
    # Le club ne trade QUE les futures perpétuels Kraken : le bot n'analyse et ne propose que des contrats PF_….
    perps_only: bool = True
    tp_split: tuple[float, float, float] = (0.30, 0.40, 0.30)
    correlation_block: float = 0.75
    timezone: str = "Europe/Paris"

    # --- Filtres de setup ---
    min_rr_tp2: float = 1.5
    min_rr_tp1: float = 0.7
    min_net_rr_tp2: float = 1.2  # R net de frais minimal au TP2
    max_spread_pct: float = 0.35
    min_volume_24h_eur_crypto: float = 300_000
    min_volume_24h_eur_other: float = 25_000
    # Stop minimum = 1,2 × la volatilité moyenne d'une bougie 15 min (ATR). Plus serré, une simple mèche le touche
    # (ex. WIF du 02/10 : stop à 0,5 ATR → sorti par le bruit). Le trader regarde toutes les 10-30 min : il faut de l'air.
    min_sl_atr15: float = 1.2
    xstocks_us_hours_only: bool = True   # actions analysées seulement bourse US ouverte (lun–ven 15h30–22h Paris)
    min_sl_pct: float = 0.5           # stop jamais plus près que 0,5 % du prix (04/10 : stops < 0,5 % → −0,47R en moyenne sur 51 signaux)
    liq_lookback_15m: int = 16        # stop placé au-delà du plus haut/bas des 4 dernières heures s'il est proche
    # Apprentissage sur les vrais résultats des signaux (table signal_outcomes, vue signal_stats)
    live_edges: dict = {}             # "stratégie|classe" -> {"n", "win_rate", "avg_r"} (rempli par le cloud)
    live_min_trades: int = 15         # en dessous : pas assez de données réelles pour juger
    live_block_avg_r: float = -0.15   # R moyen réel en dessous duquel la combinaison ne donne plus de 🟢
    max_extension_atr15: float = 2.5
    max_fee_share_of_risk: float = 0.35
    # --- Moteur v2 (04/10) : score qualité /100 calculé par règles fixes (strategies/quality.py) ---
    # ≥ 90 : 🔥 TRADE A+ · 80–89 : 🟢 · 70–79 : 🟡 surveiller · < 70 : rien n'est publié.
    score_trade: int = 70   # 05/10 : 70 (rejet/piège prouvé hors échantillon sur les setups ≥ 70 : 34 trades, +0,45R)
    score_watch: int = 60
    score_exceptional: int = 90
    max_signals_per_scan: int = 2
    max_trades_per_direction_crypto: int = 1   # cryptos très corrélées : 1 seul 🟢 LONG et 1 seul 🟢 SHORT par scan
    # Pas de 🟢 sans preuve : la combinaison stratégie × régime doit avoir une espérance positive HORS ÉCHANTILLON
    # dans le dernier backtest walk-forward (table backtest_runs), sur assez de trades.
    require_proven_edge: bool = True
    edge_min_trades: int = 20
    edge_min_pf: float = 1.1
    v2_edges: dict = {}                       # "stratégie|famille de régime" -> stats (rempli par le cloud)
    degraded_strategies: list[str] = Field(default_factory=list)  # série de pertes récente (rempli par le cloud)
    min_net_rr_tp2_v2: float = 1.5            # R:R net de frais minimal au TP2 pour un 🟢 v2
    disabled_strategies: list[str] = Field(default_factory=list)
    quote_currencies: list[str] = Field(default_factory=list)  # vide = config/classification.toml

    # --- Scanner ---
    scan_interval_minutes: int = 60
    watch_interval_minutes: int = 10
    scheduler_enabled: bool = True
    universe_max_crypto: int = 30
    universe_max_xstocks: int = 10
    universe_max_commodities: int = 8
    futures_enabled: bool = True
    news_enabled: bool = True
    news_max_age_hours: float = 24.0
    urgent_move_pct_crypto: float = 3.0
    urgent_move_pct_other: float = 1.5
    instrument_cache_hours: float = 6.0

    # --- Paper ---
    paper_auto_manage: bool = True
    paper_pending_expiry_hours: float = 4.0

    # --- Optimiseur (historique) ---
    optimizer_enabled: bool = True          # ré-optimisation automatique nocturne
    optimizer_hour_local: int = 3
    optimizer_max_bars: int = 12000         # bougies 15m max par instrument (~4 mois)
    optimizer_min_trades: int = 15          # trades hors échantillon minimum pour adopter des paramètres
    use_optimized_params: bool = True

    # --- Live ---
    live_trading: bool = False
    live_trading_ack: str = ""
    live_confirmation_ttl_s: int = 120

    # --- Chemins / serveur ---
    data_dir: Path = PROJECT_ROOT / "data"
    config_dir: Path = PROJECT_ROOT / "config"
    log_dir: Path = PROJECT_ROOT / "logs"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    @field_validator("tp_split", mode="before")
    @classmethod
    def _parse_split(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = tuple(float(x) / (100 if float(x) > 1 else 1) for x in v.split(","))
        return v

    @field_validator("tp_split")
    @classmethod
    def _check_split(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if len(v) != 3 or abs(sum(v) - 1.0) > 1e-6:
            raise ValueError("tp_split doit contenir 3 parts dont la somme vaut 100 %")
        return v

    @field_validator("max_leverage")
    @classmethod
    def _cap_leverage(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("MAX_LEVERAGE doit être entre 1 et 10")
        return v

    @field_validator("risk_normal_pct", "risk_exceptional_pct", "max_open_risk_pct", "max_daily_loss_pct")
    @classmethod
    def _sane_risk(cls, v: float) -> float:
        if v <= 0 or v > 5:
            raise ValueError("Les pourcentages de risque doivent être entre 0 et 5 %")
        return v

    # ---- helpers ----
    @property
    def has_spot_keys(self) -> bool:
        return bool(self.kraken_api_key.get_secret_value() and self.kraken_api_secret.get_secret_value())

    @property
    def has_futures_keys(self) -> bool:
        return bool(self.kraken_futures_api_key.get_secret_value()
                    and self.kraken_futures_api_secret.get_secret_value())

    @property
    def live_armed(self) -> bool:
        """Live n'est armé que si LIVE_TRADING=true ET la phrase d'accusé exacte est présente."""
        return bool(self.live_trading and self.live_trading_ack == LIVE_ACK_PHRASE)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    def secret_values(self) -> list[str]:
        vals = [self.kraken_api_key, self.kraken_api_secret, self.kraken_futures_api_key,
                self.kraken_futures_api_secret, self.finnhub_api_key]
        return [s.get_secret_value() for s in vals if s.get_secret_value()]

    def load_toml(self, name: str) -> dict[str, Any]:
        path = self.config_dir / name
        if not path.exists():
            return {}
        with path.open("rb") as f:
            return tomllib.load(f)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
