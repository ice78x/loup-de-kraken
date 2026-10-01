# Architecture

```
src/kraken_assistant/
  config.py            Réglages (.env) + fichiers TOML ; secrets en SecretStr
  logging_setup.py     Logs INFO/WARNING/ERROR console + fichier, masquage des secrets
  app.py               Conteneur : instancie clients, services, base
  commands.py          Commandes texte (CLI + dashboard)
  cli.py / __main__.py serve | shell | run | <commande>
  scheduler.py         Scan toutes les N min + veille urgente
  api/
    http.py            Timeout, retries, limitation de débit
    kraken_spot.py     REST spot public/privé (signature API-Sign)
    kraken_futures.py  REST futures public/privé (signature Authent), bougies charts
  market/
    instruments.py     instrument_discovery (AssetPairs country_code, tokenized_asset, futures)
    prices.py          Tickers + conversion EUR (sans valeur par défaut)
    candles.py         OHLCV 5m/1h → 15m/4h, retrait bougie en cours, contrôles qualité
    orderbook.py       Spread + profondeur ±0,5 %
    history.py         Historique local (SQLite) : accumulation, jour/semaine, backfill futures, import CSV Kraken
  news/engine.py       RSS/Atom, classification, rumeurs, vérification croisée
  analysis/
    indicators.py      EMA, SMA, RSI, ATR (Wilder), VWAP, volume relatif
    structure.py       Swings HH/HL/LH/LL, tendance, niveaux S/R
    breakout.py        Cassure confirmée / retest / fausse cassure / sweep / rejet / sans volume / étendu
    volatility.py      Régime ATR
    liquidity.py       Volume 24h €, spread, carnet, proxy liquidations
    correlation.py     Corrélation rendements 1h
    catalysts.py       News vérifiées → points de confluence (jamais un déclencheur seul)
    htf.py             Contexte long terme : tendance J/S, ATH/ATL, 52 sem., niveaux majeurs
    market_analysis.py Assemblage multi-timeframes
  strategies/
    base.py            Setup, TP (niveaux puis projections), score, filtres durs
    breakout_retest.py cassure_retest
    rejection.py       rejet_sweep
    trend.py           tendance_pullback
    news.py            news_momentum (news majeure + réaction de prix + pullback confirmé)
  risk/
    position_sizing.py risk_manager : taille depuis ENTRY→SL + frais, levier en dernier
    portfolio_risk.py  portfolio_risk_manager : risque cumulé, corrélation, exposition
    daily_loss.py      P&L réalisé du jour (Europe/Paris)
  portfolio/
    positions.py       Positions paper + import Kraken (marge, futures, avoirs spot)
    management.py      GESTION POSITION
    pnl.py             Capital paper + statistiques
  execution/
    paper.py           Exécution virtuelle sur bougies réelles
    live.py            Triple verrou, validate=true, code à usage unique
  scanner/
    scan.py            scan() : pipeline complet + journal
    urgent.py          Détection des déclencheurs + scan urgent
    formatter.py       Sorties 🟢/🟡/🛑
  backtest/engine.py   Détection sans look-ahead + simulation numpy (maker/taker, BE confirmé, 2 positions max)
  backtest/optimizer.py Walk-forward par classe d'actif × stratégie, validation hors échantillon
  database/db.py       SQLite : signals, positions, fills, scans, news, kv
  ui/server.py + static/index.html   Dashboard FastAPI
config/
  classification.toml  Taxonomie (matières premières, exclusions, alias news)
  news_sources.toml    Sources et niveau de confiance
```

## Pipeline d'un scan

1. **Instruments** : découverts via l'API ; tradables seulement ; statut, taille min, précision, levier, pays.
2. **Prix** : tous les tickers en 2-3 appels ; taux EUR/USD réel.
3. **Positions** : paper + Kraken (si clés) ; capital (paper, ou Kraken si live armé).
4. **News** : collecte, classification, vérification (tier 1-3 = primaire ; tier 4-5 = 2 sources ; rumeur = jamais).
5. **Univers** : filtre liquidité/spread → une ligne par actif (meilleure venue) → top N par classe + actifs avec news + positions.
6. **OHLCV** : 5m & 1h (API) → 15m & 4h (agrégés) ; bougie en cours retirée ; contrôles (trous, incohérences, données périmées).
7. **Analyse** : structure multi-TF, niveaux, volatilité, liquidité, catalyseur.
8. **Stratégies** → setups avec score de confluence (catalyseur, structure, niveau, volume, volatilité, confirmation, R:R, liquidité, secondaires).
9. **Filtres durs** : direction possible, liquidité, R:R, SL pas trop serré vs ATR15, volatilité extrême, extension, delisting.
10. **Risque** : budget restant (2 % ouvert, 3 % jour), corrélation vs positions et vs autres signaux, sizing, R net de frais, carnet.
11. **Sortie** : 🟢 (max 3), 🟡 niveaux à surveiller, 🛑 avec raisons ; tout est journalisé.

## Score de confluence (0-100)

| Composante | Max | Commentaire |
|---|---|---|
| Catalyseur | +20 / −15 | news vérifiées, pondérées par impact et fraîcheur |
| Structure | 20 | tendance 4h/1h alignée (ou range pour les rejets) |
| Fond | +10 / −5 | tendance journalière et hebdo (tout l'historique) |
| Niveau | 15 | contacts × poids timeframe |
| Volume | 10 | volume relatif à la cassure/confirmation |
| Volatilité | 10 | normale > élevée > compressée > extrême |
| Confirmation | 15 | retest confirmé 15, sweep/fausse cassure confirmés 12… |
| R:R | 10 | R au TP2 |
| Liquidité | 5 | volume 24h, spread |
| Secondaires | ±2/−4 | RSI extrême contre la direction, VWAP |

🟢 si confirmé, aucun filtre bloquant, score ≥ seuil (60 par défaut, ou seuil optimisé si la stratégie est « adoptée ») et risque disponible. Une stratégie « désactivée » par l'optimiseur ne peut plus produire de 🟢 sur cette classe d'actif. 🟡 sinon si score ≥ 40.
Risque 2 % seulement si score ≥ 85 **et** catalyseur majeur vérifié aligné.
