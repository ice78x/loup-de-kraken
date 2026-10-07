"""Score QUALITÉ /100 (moteur v2) et coupe-circuits.

Règles fixes et vérifiables (aucun réglage sur le passé) :

  Régime de marché      /20  la stratégie est-elle celle du régime ? 10 + 10 × confiance du régime, sinon 0
  Alignement            /20  4h, 1h, jour + BTC (altcoins) ou semaine : 5 aligné · 3 neutre · 0 opposé
  Structure             /20  force du niveau (8) + qualité de la confirmation (8) + pas d'obstacle avant TP1 (4)
  Volume / liquidité    /10  volume relatif de la bougie signal (6) + liquidité du marché (4)
  Momentum              /10  EMA9 > EMA21 en 15m (4) · prix du bon côté du VWAP (3) · RSI 1h dans la zone saine (3)
  News                  /10  catalyseur vérifié aligné 10 · aucun 5 · contraire 2 · bloquant 0
  R:R                   /10  R net de frais au TP2 : ≥ 3 → 10 · ≥ 2,5 → 8 · ≥ 2 → 6 · ≥ 1,5 → 3

Coupe-circuits (le setup ne peut pas être 🟢, quel que soit le score) : régime incertain/chaotique/volatilité extrême,
stratégie non adaptée au régime, BTC contre le trade, conflit 4h/1h, R:R net < minimum, avantage statistique non démontré,
stratégie en série de pertes.
"""
from __future__ import annotations

from ..analysis.indicators import ema
from ..analysis.regime import NO_TRADE_REGIMES, MarketContext, Regime, regime_from_analysis
from ..config import Settings

A_PLUS, A, B, C = "A+", "A", "B", "C"


def regime_family(name: str) -> str:
    return "TREND" if name.startswith("TREND") else "BREAKOUT" if name.startswith("BREAKOUT") else name


def edge_key(strategy: str, regime: str, asset_class: str = "crypto") -> str:
    """Combinaison prouvée : stratégie × famille de régime, et classe d'actif hors crypto (07/10) —
    l'or ou une action ne se comportent pas comme une crypto : leur preuve est mesurée à part."""
    base = f"{strategy}|{regime_family(regime)}"
    return base if asset_class in ("crypto", "", None) else f"{base}|{asset_class}"


def grade(score: float, s: Settings) -> str:
    return A_PLUS if score >= s.score_exceptional else A if score >= s.score_trade else B if score >= s.score_watch else C


def net_rr(st, fee_taker_pct: float, fee_maker_pct: float) -> list[float]:
    """R nets de frais pour chaque TP (entrée la moins bonne, frais d'entrée + de sortie)."""
    e, sl = st.sizing_entry, st.sl
    fm, ft = fee_maker_pct / 100, fee_taker_pct / 100
    loss = abs(e - sl) + fm * e + ft * sl
    if loss <= 0:
        return [0.0 for _ in st.tps]
    return [round((abs(tp - e) - fm * e - fm * tp) / loss, 2) for tp in st.tps]


def _fees(inst, s: Settings) -> tuple[float, float]:
    fut = getattr(inst, "venue", "futures") == "futures"
    taker = getattr(inst, "taker_fee_pct", None) or (s.default_futures_taker_fee_pct if fut else s.default_spot_taker_fee_pct)
    maker = s.default_futures_maker_fee_pct if fut else s.default_spot_maker_fee_pct
    return float(taker), float(maker)


def _trend_pts(trend: str, d: str) -> float:
    if trend == d:
        return 5.0
    if trend in ("up", "down"):
        return 0.0
    return 3.0


def context_of(a) -> tuple[Regime, MarketContext]:
    rg = getattr(a, "regime", None)
    if rg is None:
        try:
            rg = regime_from_analysis(a)
        except (KeyError, IndexError, ValueError, AttributeError):
            rg = Regime(reasons=["régime non calculable"])
        try:
            a.regime = rg
        except AttributeError:
            pass
    ctx = getattr(a, "context", None) or MarketContext()
    return rg, ctx


def score_quality(st, a, s: Settings, legacy: dict) -> dict:
    """Calcule les composantes v2. `legacy` = composantes de l'ancien score (niveau, confirmation, volume…)."""
    rg, ctx = context_of(a)
    d = "up" if st.direction == "LONG" else "down"
    c: dict[str, float] = {}
    c["régime"] = round(10 + 10 * rg.confidence, 1) if rg.allows(st.strategy, st.direction) else 0.0
    s4, s1 = a.structures["4h"], a.structures["1h"]
    verdict, btc_pts, _ = ctx.check(a.inst.base, a.inst.asset_class, st.direction)
    four = btc_pts if (a.inst.asset_class == "crypto" and a.inst.base not in ("BTC", "XBT") and ctx.btc is not None) \
        else _trend_pts(a.htf.weekly_trend, d)
    c["alignement"] = round(_trend_pts(s4.trend, d) + _trend_pts(s1.trend, d) + _trend_pts(a.htf.daily_trend, d) + four, 1)
    obstacle = any(w.startswith("niveau gênant proche") for w in st.warnings)
    c["structure"] = round(min(8.0, legacy.get("niveau", 0) / 15 * 8) + min(8.0, max(0.0, legacy.get("confirmation", 0)) / 15 * 8)
                           + (0 if obstacle else 4), 1)
    liq = a.liquidity.score if a.liquidity else 0.5
    c["volume"] = round(min(6.0, legacy.get("volume", 2) * 0.6) + 4 * liq, 1)
    f15 = a.frames["15m"]["close"]
    mom = 0.0
    if len(f15) >= 30:
        e9, e21 = ema(f15, 9).iloc[-1], ema(f15, 21).iloc[-1]
        mom += 4 if (e9 > e21) == (d == "up") else 0
    if a.vwap15:
        mom += 3 if (a.price > a.vwap15) == (d == "up") else 0
    if d == "up":
        mom += 3 if 45 <= a.rsi1h <= 70 else 0
    else:
        mom += 3 if 30 <= a.rsi1h <= 55 else 0
    c["momentum"] = mom
    pts = a.catalyst.points.get(st.direction, 0.0)
    opp = a.catalyst.points.get("SHORT" if st.direction == "LONG" else "LONG", 0.0)
    if a.catalyst.blocks.get(st.direction):
        c["news"] = 0.0
    elif pts >= 8:
        c["news"] = 10.0
    elif pts > 0:
        c["news"] = 7.0
    elif opp >= 5:
        c["news"] = 2.0
    else:
        c["news"] = 5.0
    taker, maker = _fees(a.inst, s)
    nr = net_rr(st, taker, maker)
    r2 = nr[1] if len(nr) > 1 else (nr[0] if nr else 0.0)
    c["R:R"] = 10.0 if r2 >= 3 else 8.0 if r2 >= 2.5 else 6.0 if r2 >= 2 else 3.0 if r2 >= 1.5 else 0.0
    return {"components": c, "score": round(min(100.0, sum(c.values())), 1), "regime": rg, "btc": verdict, "net_rr": nr}


def kill_switch(st, a, s: Settings, q: dict, check_edge: bool = True) -> list[str]:
    """Raisons qui interdisent un 🟢 (vide = aucune)."""
    rg: Regime = q["regime"]
    out: list[str] = []
    if rg.name in NO_TRADE_REGIMES:
        out.append(f"régime : {rg.label.lower()} — pas de trade")
    elif not rg.allows(st.strategy, st.direction):
        out.append(f"stratégie non adaptée au régime ({rg.label.lower()})")
    _, ctx = context_of(a)
    verdict, _, why = ctx.check(a.inst.base, a.inst.asset_class, st.direction)
    if verdict == "bloque":
        out += why
    s4, s1 = a.structures["4h"].trend, a.structures["1h"].trend
    if {s4, s1} == {"up", "down"}:
        out.append(f"conflit entre unités de temps (4h {s4} / 1h {s1})")
    nr = q["net_rr"]
    r2 = nr[1] if len(nr) > 1 else (nr[0] if nr else 0.0)
    if r2 < s.min_net_rr_tp2_v2:
        out.append(f"R:R net de frais insuffisant au TP2 ({r2:.1f}R < {s.min_net_rr_tp2_v2:g}R)")
    if s.cooldown_after_stop_h > 0 and f"{a.inst.key}|{st.direction}" in (s.recent_stops or []):
        out.append(f"même setup stoppé il y a moins de {s.cooldown_after_stop_h:g} h : le marché a déjà dit non")
    if st.strategy in (s.degraded_strategies or []):
        out.append(f"{st.strategy} en série de pertes : désactivée jusqu'à analyse")
    if check_edge and s.require_proven_edge and st.strategy != "news":
        e = (s.v2_edges or {}).get(edge_key(st.strategy, rg.name, getattr(a.inst, "asset_class", "crypto")))
        if not e:
            out.append(f"avantage statistique non démontré ({st.strategy} en {rg.label.lower()} : pas encore de backtest)")
        elif e.get("n", 0) < s.edge_min_trades:
            out.append(f"avantage statistique non démontré ({e.get('n', 0)} trades testés, {s.edge_min_trades} requis)")
        elif (e.get("expectancy_r") or 0) <= 0 or (e.get("profit_factor") or 0) < s.edge_min_pf:
            out.append(f"perd en backtest ({e.get('expectancy_r', 0):+.2f}R/trade sur {e.get('n')} trades)")
        else:
            from ..backtest.walkforward import proven
            if not proven(e, s, require_oos=True):
                n_oos = e.get("oos_n") or 0
                if n_oos < s.edge_min_oos_trades:
                    out.append(f"pas encore confirmé sur des données jamais vues ({n_oos} trade(s) hors échantillon, "
                               f"{s.edge_min_oos_trades} requis)")
                else:
                    out.append(f"perd en backtest hors échantillon ({(e.get('oos_expectancy_r') or 0):+.2f}R/trade sur "
                               f"{n_oos} trades jamais vus)")
    return out
