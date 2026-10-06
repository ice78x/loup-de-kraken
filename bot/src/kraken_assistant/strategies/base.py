"""Modèle de setup, construction des objectifs (TP) et score de confluence."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..analysis.breakout import LevelEvent
from ..analysis.market_analysis import MarketAnalysis
from ..config import Settings

TRADE, WATCH = "TRADE", "WATCH"
ACTION_ENTER = "ENTRÉE (ordre limite dans la zone)"
ACTION_WAIT_RETEST = "ATTENDRE LE RETEST (ordre limite dans la zone)"
ACTION_WAIT_CLOSE = "ATTENDRE LA CLÔTURE 15M DE CONFIRMATION"


@dataclass
class Setup:
    inst_key: str
    display: str
    asset_class: str
    strategy: str
    direction: str                  # LONG | SHORT
    entry_low: float
    entry_high: float
    sl: float
    tps: list[float]
    invalidation_price: float
    invalidation_text: str
    action: str
    reasons: list[str] = field(default_factory=list)
    event: LevelEvent | None = None
    tp_notes: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    status: str = WATCH
    rejections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trigger: str = ""               # ce qui ferait passer un WATCH en TRADE
    confirmed: bool = False
    exceptional: bool = False
    extension_atr: float = 0.0      # distance (en ATR 15m) entre le niveau clé et le prix, dans le sens du trade
    edge_note: str = ""             # performance historique hors échantillon de la stratégie (optimiseur)
    # --- moteur v2 ---
    legacy_score: float = 0.0       # ancien score additif (conservé pour la comparaison AVANT/APRÈS)
    legacy_status: str = WATCH      # statut que l'ancien moteur aurait donné (score ≥ 60, filtres durs, confirmé)
    hard_ok: bool = True            # aucun filtre dur (stop, R:R, liquidité, extension…) ne refuse le setup
    grade: str = ""                 # A+ (≥ 90) · A (≥ 80) · B (≥ 70) · C
    regime: str = ""
    regime_label: str = ""
    btc_context: str = ""           # bloque | contre | neutre | favorable
    kill: list[str] = field(default_factory=list)   # coupe-circuits v2 (interdisent le 🟢)
    net_rr: list[float] = field(default_factory=list)
    presque_pret: bool = False      # tout est bon (score, preuve, filtres) sauf la confirmation 15m → pré-alerte Telegram
    stale: bool = False             # signal trop ancien : ne pourra plus jamais être confirmé (pas de pré-alerte)

    @property
    def sizing_entry(self) -> float:
        """Entrée la plus défavorable de la zone (distance au SL maximale) → risque jamais sous-estimé."""
        return self.entry_high if self.direction == "LONG" else self.entry_low

    @property
    def sign(self) -> int:
        return 1 if self.direction == "LONG" else -1

    def r_multiples(self) -> list[float]:
        e = self.sizing_entry
        risk = abs(e - self.sl)
        return [round(abs(tp - e) / risk, 2) if risk else 0.0 for tp in self.tps]


def build_targets(direction: str, entry: float, sl: float, level_prices: list[float], atr15: float,
                  max_tps: int = 3) -> tuple[list[float], list[str], float | None]:
    """TP sur niveaux techniques (légèrement avant le niveau), complétés par des projections en R.
    Retourne (tps, notes, obstacle_R) où obstacle_R = distance en R d'un niveau gênant trop proche."""
    sign = 1 if direction == "LONG" else -1
    R = abs(entry - sl)
    beyond = sorted((p for p in level_prices if sign * (p - entry) > 0), key=lambda p: sign * (p - entry))
    obstacle = None
    tps, notes = [], []
    for p in beyond:
        adj = p - sign * 0.1 * atr15
        dist = sign * (adj - entry)
        if dist < 0.6 * R:
            obstacle = dist / R if obstacle is None else obstacle
            continue
        if tps and sign * (adj - tps[-1]) < 0.5 * R:
            continue
        tps.append(adj)
        notes.append(f"TP{len(tps)} sur niveau {p:g}")
        if len(tps) == max_tps:
            break
    for m in (1.3, 2.2, 3.2, 4.2):
        if len(tps) >= max_tps:
            break
        cand = entry + sign * m * R
        if tps and sign * (cand - tps[-1]) < 0.5 * R:
            continue
        tps.append(cand)
        notes.append(f"TP{len(tps)} projeté à {m}R (pas de niveau technique au-delà)")
    return tps, notes, obstacle


def _vol_points(rvol: float | None) -> float:
    if rvol is None:
        return 2.0
    return 10 if rvol >= 2 else 8 if rvol >= 1.5 else 6 if rvol >= 1.2 else 4 if rvol >= 1.0 else 1


def score_setup(st: Setup, a: MarketAnalysis, s: Settings, level_strength: float, rvol: float | None,
                confirmation_pts: float, reversal: bool = False) -> None:
    d = "up" if st.direction == "LONG" else "down"
    s4, s1 = a.structures["4h"], a.structures["1h"]
    c: dict[str, float] = {}
    c["catalyseur"] = a.catalyst.points.get(st.direction, 0.0)
    if reversal:
        struct = 8 if s1.trend == "range" else (4 if s1.trend == d else 2)
        struct += 6 if s4.trend in (d, "range") else 0
        struct += 4 if s1.ema_bias in (d, "flat") else 0
    else:
        struct = (8 if s4.trend == d else 4 if s4.trend == "range" else 0)
        struct += (8 if s1.trend == d else 4 if s1.trend == "range" else 0)
        struct += 4 if s1.ema_bias == d else 0
    c["structure"] = min(20, struct)
    # Contexte long terme (tout l'historique journalier/hebdo) : +5 par tendance de fond alignée,
    # −5 si contre les deux (sauf stratégie de retournement en range)
    al = a.htf.aligned(st.direction)
    c["fond"] = 5.0 * al if al >= 0 else (-2.5 if reversal else -5.0)
    c["niveau"] = min(15.0, level_strength * 2.5)
    c["volume"] = _vol_points(rvol)
    c["volatilité"] = round(a.vol.score * 10, 1)
    c["confirmation"] = confirmation_pts
    rs = st.r_multiples()
    r2 = rs[1] if len(rs) > 1 else (rs[0] if rs else 0)
    c["R:R"] = 10 if r2 >= 3 else 8 if r2 >= 2 else 5 if r2 >= 1.5 else 0
    c["liquidité"] = round((a.liquidity.score if a.liquidity else 0.5) * 5, 1)
    sec = 0.0  # indicateurs secondaires (jamais décisifs)
    if st.direction == "LONG":
        sec += -4 if a.rsi1h > 78 else 1 if 45 <= a.rsi1h <= 68 else 0
        sec += 1 if a.vwap15 and a.price > a.vwap15 else 0
    else:
        sec += -4 if a.rsi1h < 22 else 1 if 32 <= a.rsi1h <= 55 else 0
        sec += 1 if a.vwap15 and a.price < a.vwap15 else 0
    c["secondaires"] = sec
    st.components = {k: round(v, 1) for k, v in c.items()}
    st.score = round(max(0.0, min(100.0, sum(c.values()))), 1)


def snap_to_tick(st: Setup, tick: float) -> None:
    """Arrondit les niveaux au pas de prix Kraken (sinon Kraken refuse l'ordre ou le TP/SL, ex. 7 décimales sur PUMP).
    Prudent : le stop s'éloigne, les TP se rapprochent de l'entrée, la zone d'entrée s'élargit d'un pas au plus."""
    if not tick or tick <= 0:
        return
    def down(x: float) -> float:
        return round(math.floor(x / tick + 1e-9) * tick, 12)

    def up(x: float) -> float:
        return round(math.ceil(x / tick - 1e-9) * tick, 12)

    st.entry_low, st.entry_high = down(st.entry_low), up(st.entry_high)
    if st.direction == "LONG":
        st.sl, st.tps, st.invalidation_price = down(st.sl), [down(t) for t in st.tps], down(st.invalidation_price)
    else:
        st.sl, st.tps, st.invalidation_price = up(st.sl), [up(t) for t in st.tps], up(st.invalidation_price)


def apply_filters(st: Setup, a: MarketAnalysis, s: Settings) -> None:
    """Filtres durs : ils ne dépendent pas du score."""
    inst = a.inst
    # Stop « respirable » : au moins min_sl_atr15 × ATR 15 min entre l'entrée la moins bonne et le stop.
    # S'il est plus serré, on l'éloigne (jamais l'inverse) ; le R:R est recalculé juste après et peut alors refuser le setup.
    if a.atr15 > 0 and abs(st.sizing_entry - st.sl) < s.min_sl_atr15 * a.atr15:
        ancien = st.sl
        st.sl = st.sizing_entry - st.sign * s.min_sl_atr15 * a.atr15
        st.warnings.append(f"stop éloigné à {st.sl:.6g} (au lieu de {ancien:.6g}) : au moins {s.min_sl_atr15:g} × la volatilité "
                           "d'une bougie 15 min, pour ne pas être sorti par une simple mèche")
    # Stop au-delà de la liquidité proche : un stop posé juste avant le plus haut (SHORT) / plus bas (LONG) récent
    # est exactement là où le marché va chercher les stops (ex. ETH SHORT du 03/10 : stop sous le haut du range).
    df15 = (getattr(a, "frames", None) or {}).get("15m")
    if df15 is not None and len(df15) and a.atr15 > 0:
        recent = df15.iloc[-s.liq_lookback_15m:]
        extreme = float(recent["high"].max()) if st.direction == "SHORT" else float(recent["low"].min())
        derriere = st.sign * (st.sl - extreme) > 0          # stop entre l'entrée et l'extrême récent
        proche = abs(extreme - st.sizing_entry) <= 3 * a.atr15
        if derriere and proche and st.sign * (st.sizing_entry - extreme) > 0:
            ancien = st.sl
            st.sl = extreme - st.sign * 0.4 * a.atr15   # marge sous le creux / au-dessus du sommet (ex. MON du 04/10 : stop chassé de 0,1 %)
            st.warnings.append(f"stop placé au-delà du {'plus haut' if st.direction == 'SHORT' else 'plus bas'} des 4 dernières heures "
                               f"({extreme:.6g}) : {st.sl:.6g} au lieu de {ancien:.6g}, pour ne pas être chassé")
    # Stop minimal en % du prix (marchés très calmes : 1,2 × ATR peut faire 0,1 %, moins que les frais + le bruit)
    min_dist = st.sizing_entry * s.min_sl_pct / 100
    if abs(st.sizing_entry - st.sl) < min_dist:
        ancien = st.sl
        st.sl = st.sizing_entry - st.sign * min_dist
        st.warnings.append(f"stop éloigné à {st.sl:.6g} (au lieu de {ancien:.6g}) : au moins {s.min_sl_pct:g} % du prix")
    snap_to_tick(st, getattr(inst, "tick_size", 0) or 0)
    # Niveau gênant entre l'entrée et le TP1 (ex. MON et WLD du 04/10, résistance à 0,4–0,5R) : le prix bute dessus et revient.
    # Pas de 🟢 tant que ce niveau n'est pas cassé (le prochain scan le revoit).
    obst = next((w for w in st.warnings if w.startswith("niveau gênant proche")), None)
    if obst:
        st.rejections.append(f"{obst} avant le TP1 : attendre sa cassure (clôture 15m au-delà)")
        st.trigger = st.trigger or "cassure du niveau gênant avant le TP1 (clôture 15m au-delà)"
    # Marché trop peu actif : des bougies 15 min sans aucun échange = carnet vide, stops et sorties mal exécutés.
    df15v = (getattr(a, "frames", None) or {}).get("15m")
    if df15v is not None and len(df15v) and "volume" in df15v:
        vides = int((df15v["volume"].iloc[-24:] <= 0).sum())
        if vides >= 3:
            st.rejections.append(f"marché trop peu actif ({vides} bougies 15 min sans échange sur 6 h)")
    if st.direction == "SHORT" and not inst.can_short:
        st.rejections.append("SHORT impossible sur cet instrument (pas de marge/perp)")
    if st.direction == "LONG" and not inst.can_long:
        st.rejections.append("LONG impossible sur cet instrument")
    if a.liquidity and not a.liquidity.ok:
        st.rejections += a.liquidity.issues
    if block := a.catalyst.blocks.get(st.direction):
        st.rejections.append(block)
    rs = st.r_multiples()
    if not rs or rs[0] < s.min_rr_tp1 or (len(rs) > 1 and rs[1] < s.min_rr_tp2):
        st.rejections.append(f"mauvais ratio R:R ({' / '.join(f'{r:.1f}' for r in rs)})")
    sl_dist = abs(st.sizing_entry - st.sl)
    if a.atr15 > 0 and sl_dist < s.min_sl_atr15 * a.atr15:
        st.rejections.append("SL trop serré vs volatilité 15m — nécessiterait une surveillance continue")
    if a.vol.regime == "extrême" and not a.catalyst.has_major:
        st.rejections.append("volatilité extrême sans catalyseur identifié — marché trop incertain")
    if st.extension_atr > s.max_extension_atr15:
        st.rejections.append("mouvement déjà trop étendu")
    st.warnings += a.catalyst.warnings


LEGACY_SCORE_TRADE = 60   # seuil 🟢 de l'ancien moteur (jusqu'au 04/10), pour la comparaison AVANT/APRÈS


def finalize(st: Setup, a: MarketAnalysis, s: Settings, check_edge: bool = True) -> Setup:
    from .quality import grade, kill_switch, score_quality
    apply_filters(st, a, s)
    if a.htf.history_days:
        st.reasons.append(a.htf.summary())
    st.hard_ok = not st.rejections
    st.legacy_score = st.score
    st.legacy_status = TRADE if (st.hard_ok and st.confirmed and st.score >= LEGACY_SCORE_TRADE) else WATCH
    q = score_quality(st, a, s, dict(st.components))
    rg = q["regime"]
    st.components, st.score = q["components"], q["score"]
    st.regime, st.regime_label, st.btc_context, st.net_rr = rg.name, rg.label, q["btc"], q["net_rr"]
    st.grade = grade(st.score, s)
    st.kill = kill_switch(st, a, s, q, check_edge=check_edge)
    st.rejections += st.kill
    st.reasons.insert(0, f"régime : {rg.label.lower()}" + (f" ({rg.reasons[0]})" if rg.reasons else ""))
    aligned_major = a.catalyst.has_major and a.catalyst.points.get(st.direction, 0) >= 8
    st.exceptional = st.score >= s.score_exceptional and aligned_major
    # Il ne manque QUE la confirmation (clôture 15m / retest) : le membre peut se préparer.
    st.presque_pret = not st.rejections and not st.confirmed and not st.stale and st.score >= s.score_trade
    if st.rejections or not st.confirmed:
        st.status = WATCH
    elif st.score >= s.score_trade:
        st.status = TRADE
    else:
        st.status = WATCH
        st.rejections.append(f"score qualité {st.score:.0f}/100 < {s.score_trade} : pas assez de confluence")
    return st
