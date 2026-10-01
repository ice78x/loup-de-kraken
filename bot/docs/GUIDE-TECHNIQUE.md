# Kraken Assistant

Assistant de trading personnel pour **Kraken Pro** : il scanne crypto, xStocks et matières premières, filtre fortement, et ne propose que des setups confirmés, avec entrée, SL, 3 TP, levier, taille et risque déjà calculés.

**Mode par défaut : PAPER / ANALYSE. Le trading réel est OFF** et ne peut pas s'activer par accident.

> Ce système cherche des probabilités et des scénarios avec une invalidation claire. Il ne garantit rien. Chaque trade peut perdre.

---

## 1. Installation (une seule fois)

Il faut **Python 3.11 ou plus récent** (3.12 recommandé).

```bash
cd kraken-assistant
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
cp .env.example .env        # Windows : copy .env.example .env
```

Vérifie que tout fonctionne :

```bash
pytest -q                    # ~86 tests, ~1 min
```

## 2. Lancer le projet

```bash
python -m kraken_assistant serve
```

Ouvre ensuite **http://127.0.0.1:8000**.

- Le dashboard affiche : capital, risque disponible, positions, opportunités, news, dernier et prochain scan.
- Le scheduler démarre tout seul. Il fait un scan complet toutes les heures, et une veille « scan urgent » toutes les 10 minutes.

Autres modes :

| Commande | Effet |
|---|---|
| `python -m kraken_assistant shell` | Invite interactive : tape `SCAN`, `POSITIONS`… |
| `python -m kraken_assistant SCAN` | Une commande, puis sortie |
| `python -m kraken_assistant run` | Scheduler seul, sans interface |

## 3. Configurer Kraken

**Sans clé API**, tout fonctionne en analyse et en paper, car les données de marché sont publiques. Dans ce cas, les signaux portent la mention « accès compte non vérifié ».

**Avec une clé API**, l'assistant lit tes positions réelles, ton solde et tes vrais frais.

1. Va sur Kraken Pro → *Settings → API → Create API key*.
2. Coche **uniquement** les permissions de **lecture** :
   - *Funds : Query*
   - *Orders & trades : Query open orders & trades* et *Query closed orders & trades*
3. **Ne coche pas** *Create & modify orders* tant que tu n'actives pas le live. **Ne coche jamais** *Withdraw*.
4. Colle la clé et le secret dans `.env` : `KRAKEN_API_KEY=` et `KRAKEN_API_SECRET=`.
5. **Futures** (perpétuels, frais ~0,05 % au lieu de ~0,40 % en spot) : crée une clé *read-only* sur Kraken Futures, puis remplis `KRAKEN_FUTURES_API_KEY` et `KRAKEN_FUTURES_API_SECRET`. Sans cette clé, les perpétuels restent en 🟡 SURVEILLER, jamais en 🟢.
6. Dans `.env`, remplace l'e-mail de `USER_AGENT` par le tien : la SEC refuse les requêtes sans contact.

Sécurité :
- `.env` est dans `.gitignore`.
- Les clés ne sont jamais écrites dans les logs : un filtre les masque.
- Le serveur écoute seulement sur `127.0.0.1`.

## 4. Lancer un scan

Dans le dashboard, clique sur **SCAN**, ou tape `SCAN` dans le shell. Un scan complet prend 1 à 3 minutes, car l'API publique Kraken est limitée à environ 1 requête par seconde.

La réponse commence **toujours** par l'une de ces lignes :

- `🟢 TRADE VALIDÉ — LONG/SHORT <actif>` : le bloc complet suit (ENTRY, SL, TP1-3, LEVIER, RISQUE, TAILLE, R:R brut et net de frais, GESTION, INVALIDATION, CATALYSEUR, SOURCE, ACTION).
- `🟡 SURVEILLER` : setups en formation, avec leurs niveaux, le déclencheur attendu et ce qui bloque.
- `🛑 AUCUN TRADE — ATTENDRE` : les raisons, puis ce qu'il faut surveiller.
- `🛑 DATA INSUFFISANTE — PAS DE TRADE` : une donnée critique manque. Rien n'est inventé.

`SCAN URGENT` relance immédiatement une analyse sur les actifs qui bougent et sur tes positions. La veille automatique le déclenche d'elle-même en cas de :
- mouvement brutal ;
- news majeure vérifiée ;
- chute d'open interest (proxy de liquidations).

### Toutes les commandes

| Commande | Rôle |
|---|---|
| `SCAN` / `SCAN URGENT` | Analyse complète / immédiate |
| `POSITIONS` | Positions : entrée, prix, P&L, SL, TP, quantité, risque restant, statut |
| `GESTION` ou `GESTION <id>` | HOLD / PRENDRE TP / DÉPLACER SL / LAISSER COURIR / SORTIE (conseil uniquement) |
| `RISQUE` | Risque ouvert, disponible, perte du jour, limites |
| `PORTFOLIO` | Capital paper et réel, positions, avoirs |
| `STATUS` | État de Kraken, des sources news, du scheduler, problèmes de données |
| `NEWS` | News importantes avec FAIT / INTERPRÉTATION |
| `JOURNAL` | 15 derniers signaux et leur résultat |
| `POSITION SET <id> sl=.. tp1=.. tp2=.. tp3=.. inv=.. entry=..` | Renseigner les niveaux d'une position Kraken |
| `CALC <capital> <risque%> <entrée> <sl> [levier]` | Calculette de taille |
| `BACKTEST <paire> [stratégie] [fichier.csv]` | Backtest des stratégies techniques (sur l'historique local) |
| `HISTORIQUE` | Profondeur d'historique stockée par actif et unité de temps |
| `HISTORIQUE BACKFILL` | Récupère jour/semaine pour tout l'univers + 15m profond (2 ans) des perpétuels |
| `HISTORIQUE IMPORT <fichier ou dossier>` | Importe les archives CSV officielles Kraken (tout l'historique spot) |
| `OPTIMISER [crypto\|xstock\|commodity\|paire]` | Règle les stratégies sur l'historique, validé hors échantillon |
| `EDGE` | Performance historique hors échantillon de chaque stratégie |

## 5. Utiliser le mode PAPER

1. Lance `SCAN`. Chaque 🟢 signal porte un numéro (« Signal n°12 »).
2. Tape `PAPER OPEN 12`, ou clique sur *Ouvrir en PAPER* dans le dashboard :
   - si le prix réel est dans la zone, l'ordre est exécuté au prix réel du carnet ;
   - sinon, un ordre limite virtuel est posé. Il expire au bout de 4 h.
3. Le suivi utilise les **vraies bougies 5m Kraken** :
   - SL et TP partiels 30/40/30, frais inclus ;
   - si une bougie touche à la fois le SL et un TP, le SL compte en premier (hypothèse prudente).
4. Avec `PAPER_AUTO_MANAGE=true`, le paper applique les conseils de GESTION :
   - SL au break-even après TP1, **seulement si** la structure 15m confirme ;
   - SL suiveur sous les creux 1h après TP2 ;
   - sortie si l'invalidation est clôturée.
5. Commandes manuelles : `PAPER CLOSE <id>`, `PAPER TP <id> <1-3>`, `PAPER SL <id> <prix>`, `PAPER DEPOSIT <€>`.
6. `PAPER STATS` donne :
   - nombre de trades, gagnants, perdants, win rate ;
   - profit moyen, perte moyenne, R moyen, profit factor, drawdown ;
   - résultats par actif, par stratégie et par catalyseur.

**Conseil** : fais au moins 30 à 50 trades en paper avant d'envisager le live. Ce sont ces statistiques, et non une impression, qui diront si la méthode tient.

## 5 bis. Historique et optimisation : utiliser tout le passé pour les prochains trades

L'assistant tient un **historique local** qui ne fait que grandir :

| Source | Profondeur |
|---|---|
| API Kraken, à chaque scan | 5m ≈ 2,5 jours · 1h ≈ 30 jours · **jour ≈ 2 ans · semaine = tout l'historique** |
| Accumulation | chaque scan ajoute les nouvelles bougies 5m/1h : l'historique fin s'allonge chaque jour |
| `HISTORIQUE BACKFILL` | perpétuels : 15m sur 2 ans (pagination de l'API futures) |
| `HISTORIQUE IMPORT` | archives CSV officielles Kraken : **tout** l'historique spot depuis le listing |

Pour avoir tout l'historique spot dès maintenant :
1. Télécharge « Kraken OHLCVT » sur support.kraken.com (article *Downloadable historical OHLCVT data*).
2. Décompresse l'archive.
3. Lance `HISTORIQUE IMPORT <dossier>`. Seuls les actifs tradables et les unités utiles (5m, 15m, 1h, 4h, jour) sont importés.

**Comment l'historique sert aux trades :**
- **Contexte long terme dans chaque analyse** :
  - tendance de fond journalière et hebdomadaire (points de score en plus si alignée, en moins si à contre-sens) ;
  - niveaux majeurs : swings journaliers et hebdo, plus haut/bas historique, plus haut/bas 52 semaines ;
  - ces niveaux servent aussi aux cassures, aux TP et à repérer les obstacles.
- **Optimiseur walk-forward** (`OPTIMISER`, lancé automatiquement chaque nuit à 3 h) :
  1. rejoue l'analyse complète du scanner sur tout l'historique 15m, bougie par bougie, sans jamais voir le futur (vérifié par un test) ;
  2. simule chaque setup avec frais maker/taker, SL avant TP, TP 30/40/30, BE seulement après confirmation, et 2 positions simultanées au maximum ;
  3. choisit, pour chaque stratégie et chaque classe d'actif, le seuil de score et le R:R minimal **sur le passé**, puis les **teste sur la période suivante, jamais vue** (4 plis successifs).
- **Ce qui en sort** :
  - 🟢 **adopté** : gagnant hors échantillon sur au moins 15 trades. Le scanner utilise ces réglages.
  - 🔴 **désactivé** : perdant hors échantillon (< −0,1R par trade). La stratégie est bloquée sur cette classe d'actif.
  - ⚪ **non démontré** : pas assez de données, les réglages par défaut s'appliquent.
- Chaque signal affiche une ligne **HISTORIQUE**. Exemple : « 34 trades hors échantillon · +0,21R/trade · win 48 % ».

La grille est volontairement petite (18 combinaisons) pour limiter la sur-optimisation. Un bon résultat passé reste une mesure, pas une promesse.

## 6. Activer le LIVE plus tard

Trois verrous doivent tous être ouverts :

1. Dans `.env` : `LIVE_TRADING=true`.
2. Dans `.env` : `LIVE_TRADING_ACK=J_ACCEPTE_LE_RISQUE_REEL`. `LIVE_TRADING=true` seul ne suffit pas.
3. Pour **chaque** ordre, tape `LIVE PREPARE <signal>`. L'assistant :
   - affiche le risque, la taille, l'entrée, le SL et les TP ;
   - fait valider l'ordre par Kraken (`validate=true`, rien n'est envoyé au carnet) ;
   - donne un code à usage unique, valable 2 minutes.

   Tu envoies ensuite l'ordre avec `CONFIRMER <ticket> <code>`.

Il faut aussi ajouter la permission *Create & modify orders* à la clé API.

Notes sur le live :
- Le SL est attaché à l'ordre d'entrée. Les TP restent à poser ou à suivre toi-même via `GESTION`.
- Le module live n'a **pas** été testé sur un compte réel. Fais un premier essai avec la taille minimale.

## 7. Limites actuelles (à connaître)

- **Pas encore lancé sur les vraies données Kraken.** Le projet a été construit dans un environnement sans accès réseau vers Kraken. Tout le pipeline est testé sur des données synthétiques, et l'échec réseau est géré. Le **premier scan réel se fera chez toi** : regarde `STATUS` et `logs/assistant.log` pour repérer d'éventuels écarts de format.
- **Éligibilité du compte** : l'API ne dit pas si ton compte a accès aux xStocks ou aux futures. Les paires sont filtrées `country_code=FR`, mais l'accès xStocks reste « non vérifié ». Sans clé futures, les perpétuels ne sont jamais proposés en 🟢.
- **Matières premières** : dépend de ce que Kraken liste pour la France (ex. PAXG / XAUT, xStocks d'ETF matières, perpétuels « tradfi »). Le classement se fait via `config/classification.toml`.
- **Short en spot** : il faut de la marge (`leverage_sell`). Sans marge ni perpétuel, les setups SHORT sont refusés.
- **Frais spot** : environ 0,40 % par côté. Sur les SL serrés, ils représentent une grosse part du risque. Le système affiche le R **net** et rejette les setups où les frais dépassent 35 % de la perte au SL ou où le R net au TP2 est inférieur à 1,2. Les perpétuels (~0,05 %) sont nettement plus adaptés à l'intraday.
- **News** : flux RSS publics (Fed, BCE, BLS, BEA, SEC, CFTC, Kraken, CNBC, MarketWatch, CoinDesk, Cointelegraph, The Block, Decrypt).
  - Pas de calendrier macro programmé : la décision FOMC est vue quand elle est publiée, pas avant.
  - Le calendrier des résultats d'entreprises n'est dispo qu'avec une clé Finnhub gratuite.
  - La lecture « haussier / baissier » est faite par des règles et affichée comme INTERPRÉTATION.
  - Les URL RSS peuvent changer : `STATUS` montre quelles sources répondent.
- **Liquidations** : Kraken ne publie pas de flux agrégé. On utilise un **proxy** (chute d'open interest + mouvement brutal), présenté comme une interprétation.
- **Historique fin** : l'API renvoie 720 bougies par unité de temps. Sans import CSV, l'historique 15m spot ne se construit qu'au fil des scans ; il faut environ 10 jours avant que l'optimiseur puisse travailler (et des mois pour des statistiques solides). Avec l'import CSV, c'est immédiat.
- **Backtest / optimiseur** : ils ne rejouent ni les news ni la liquidité historiques (le catalyseur vaut 0), et le cadre 5m y est approximé par le 15m. Sur un ordinateur classique, l'optimisation prend quelques minutes par instrument (elle est parallélisée).
- **Paper après redémarrage** : `PAPER OPEN` n'accepte que les signaux du dernier scan en mémoire. Relance `SCAN` après un redémarrage.
- **Conversion EUR/USD** : on utilise la paire EUR/USD de Kraken, sinon le ratio BTC/EUR ÷ BTC/USD. Le taux est figé à l'ouverture d'une position paper.

## 8. Prochaines améliorations possibles

1. Premier scan réel, puis ajustement des formats si Kraken diffère de la doc.
2. WebSocket Kraken : prix temps réel et suivi paper à la seconde, au lieu des bougies 5m.
3. Calendrier macro (FOMC, CPI, NFP) pour éviter d'entrer juste avant une publication.
4. Notifications (Telegram, e-mail ou push) sur 🟢 et 🔴.
5. Pour un SHORT spot impossible, proposer le perpétuel équivalent (niveaux recalculés sur son propre prix).
6. Ajouter les résultats paper réels à l'optimiseur (en plus du backtest).
7. Pose automatique des TP en live (ordres take-profit réduits) une fois le live validé.
8. Élargir la grille de l'optimiseur (distance du SL, répartition des TP) une fois l'historique assez long pour le supporter.

---

## Réglages utiles (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `CAPITAL_EUR` | 90 | Capital de départ du paper |
| `RISK_NORMAL_PCT` / `RISK_EXCEPTIONAL_PCT` | 1 / 2 | Risque par trade (le 2 % n'est autorisé que si score ≥ 85 et catalyseur majeur aligné) |
| `MAX_OPEN_RISK_PCT` | 2 | Risque cumulé max des positions ouvertes |
| `MAX_DAILY_LOSS_PCT` | 3 | Stop des nouveaux trades une fois atteint |
| `MAX_LEVERAGE` | 10 | Plafond (le levier est déduit de la taille, jamais l'inverse) |
| `SCORE_TRADE` / `SCORE_WATCH` | 60 / 40 | Seuils 🟢 / 🟡 |
| `SCAN_INTERVAL_MINUTES` / `WATCH_INTERVAL_MINUTES` | 60 / 10 | Scheduler |
| `UNIVERSE_MAX_CRYPTO` / `_XSTOCKS` / `_COMMODITIES` | 30 / 10 / 8 | Taille de l'univers analysé en profondeur |
| `OPTIMIZER_ENABLED` / `OPTIMIZER_HOUR_LOCAL` | true / 3 | Ré-optimisation nocturne automatique |
| `OPTIMIZER_MAX_BARS` | 12000 | Bougies 15m max par instrument (≈ 4 mois) ; augmente-le si ta machine est rapide |
| `OPTIMIZER_MIN_TRADES` | 15 | Trades hors échantillon minimum pour adopter/désactiver |
| `USE_OPTIMIZED_PARAMS` | true | Le scanner applique les réglages optimisés |

Architecture détaillée : [`docs/ARCHITECTURE.md`](ARCHITECTURE.md).
