# CLAUDE.md — Le Loup de Kraken

Site privé d'un club de trading entre amis (francophone, débutants) + bot d'analyse Kraken.
Réponds et écris l'interface **en français simple**. Les utilisateurs sont novices (dont une personne avec un TDAH) :
sorties courtes, verdict d'abord (🟢 / 🟡 / 🛑), pas de jargon non expliqué.

## Architecture (coût 0 €)
- `site/` : site statique servi par Netlify, **sans étape de build**. HTML + CSS + modules JavaScript natifs.
  - `js/app.js` routeur (hash `#/...`), `js/views/*.js` une page par fichier (`export async function render(main, ctx, ...params)`).
  - `js/data.js` : TOUT accès aux données passe par ici (Supabase, ou `demo.js` si `config.js` est vide).
  - `js/sizing.js` : calcul de position (miroir de `bot/src/kraken_assistant/risk/position_sizing.py`). Toute modification = mettre à jour les deux + tests.
  - `vendor/` : bibliothèques intégrées (supabase-js, lightweight-charts v5). Ne pas ajouter de CDN pour le JS.
  - `css/app.css` : jetons de design dans `:root` (bleu abyssal + ambre ; vert/rouge réservés gains/pertes et LONG/SHORT).
  - Pages clés : `views/home.js` (accueil + cartes setup de `setup.js`, mises à jour par `live.js`), `views/markets.js` (Graphiques : liste en onglets),
    `views/chart.js` (graphique d'une paire, indicateurs de `indicators.js`), `views/tradeform.js` (formulaire de trade, quantité + levier).
- `netlify/functions/` : `market.mjs` (proxy des prix publics Kraken), `scan.mjs` (déclenche le workflow GitHub `scan`).
- `supabase/schema.sql` : schéma + RLS. **Idempotent** (relançable) : utiliser `create ... if not exists`, `alter table ... add column if not exists`,
  `create or replace`. Les politiques RLS sont recréées à chaque exécution.
- `bot/` : bot Python (scanner, stratégies, risque, backtest/optimiseur). `bot/src/kraken_assistant/cloud/run.py` = point d'entrée GitHub Actions
  (scan → table `scans`/`signals`, suivi des `trades` membres, réglages lus dans `bot_settings`).
- **Apprentissage** : `bot/.../cloud/learning.py` rejoue après chaque scan les signaux des 4 derniers jours sur les vraies bougies 15m
  (entrée = pire prix de la zone, stop avant TP dans une même bougie, 30/40/30, BE après TP1, frais, 48 h max) → table `signal_outcomes`
  (permanente ; chaque signal y est écrit dès sa publication, `outcome='en_cours'` + `features` = contexte complet) → vue `signal_stats`. Relue à chaque scan (`live_edges`, 🟢 et 🟡 additionnés) : stratégie×classe ≥ 15 trades et R moyen < −0,15 → plus de 🟢.
  `resolve_signals` lit les signaux par pages de 1000 (PostgREST) et ne rejoue que les non terminés.
  Affiché dans « Mes trades » (🧠 Ce que le bot apprend).
- **Moteur v2 (04/10)** : `analysis/regime.py` (régime TREND/RANGE/BREAKOUT/HIGH_VOL/CHAOTIC/UNCERTAIN + contexte BTC/ETH `MarketContext`),
  `strategies/quality.py` (score qualité /100 à règles fixes, coupe-circuits `kill_switch`, preuve statistique), appelés par `finalize`.
  Seuils : ≥ 90 🔥 A+, ≥ 80 🟢, ≥ 70 🟡, sinon non publié. Stratégie autorisée seulement dans son régime (`ALLOWED`).
  **Pas de 🟢 sans preuve** (`require_proven_edge`) : combinaison stratégie × famille de régime prouvée dans le dernier backtest
  (`backtest_runs.report.edges`, lu par `v2_inputs` dans `cloud/run.py`). Série de pertes réelle (v2) → stratégie suspendue (`degraded_strategies`).
  Au plus 2 🟢 par scan, 1 par sens sur les cryptos. L'ancien score reste calculé (`legacy_score`) pour la comparaison AVANT/APRÈS.
- **Backtest walk-forward** : `backtest/walkforward.py` (AVANT ancien moteur / APRÈS v2, edges appris seulement sur le passé, frais + glissement),
  `backtest/runner.py` (univers liquide, backfill Kraken Futures, contexte BTC/ETH heure par heure). Lancé par `.github/workflows/backtest.yml`
  (manuel ou bouton admin du site via `netlify/functions/scan.mjs` mode `backtest`, + dimanche). Résultats affichés par `site/js/backtest.js`.
- **Telegram** : `cloud/notify.py` envoie un message à chaque nouveau 🟢 (pas de 🟡, pas de doublon sur 4 h) si les secrets GitHub
  `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` (plusieurs ids séparés par des virgules) existent. Jamais bloquant, jeton jamais journalisé.
- `.github/workflows/` : `scan.yml` (horaire), `backtest.yml` (dimanche + manuel), `optimize.yml` (ancien, dimanche), `tests.yml` (à chaque push).

## Règles NON négociables
1. **Ne jamais inventer** un prix, une news, un volume, une disponibilité Kraken, une position ou un résultat. Donnée absente → le dire
   (« DATA INSUFFISANTE — PAS DE TRADE »). Les données fictives n'existent que dans `site/js/demo.js`, `site/js/examples.js` (étiquetées) et les tests.
2. **Aucun ordre réel** envoyé depuis le site ou le cloud. Pas de clé API Kraken stockée côté serveur. (`live_trading` forcé à false dans `cloud/run.py`.)
3. **Risque** : taille = risque € / (|entrée − SL| + frais). Le multiplicateur (levier) est choisi APRÈS et ne change jamais la perte au SL.
   1 % par trade (max 2 %), 2 % de risque ouvert cumulé, stop des nouveaux trades à −3 % sur la journée.
   Côté site, le membre choisit la **quantité** (comme sur Kraken, marge isolée) : le site montre la perte au SL / à la liquidation avant d'enregistrer.
   Levier conseillé (`levierConseille` dans `site/js/setup.js`) : liquidation ≥ 2× plus loin que le stop, et mise de 25 % du solde ≈ risque habituel.
   Frais : grille Kraken dans `site/js/fees.js` ⇄ `bot/src/kraken_assistant/risk/fees.py` (à garder identiques, avec la date de vérification).
   Stop des setups (`apply_filters`) : ≥ `min_sl_atr15` × ATR 15m, ≥ `min_sl_pct` % du prix, et au-delà du plus haut/bas des 4 dernières heures
   s'il est proche (sinon stop chassé) ; R:R revérifié ensuite. Ces réglages sont aussi dans `bot_settings` (la base écrase config.py).
   Niveaux des setups arrondis au pas de prix Kraken (`snap_to_tick` dans `strategies/base.py` : stop éloigné, TP rapprochés) ;
   le site arrondit aussi les prix pré-remplis aux décimales de la paire (`pair_decimals`).
   Les perpétuels sur actions (PF_NVDAXUSD…) sont rangés en `xstock` (`classify_xstock_perps`, base = action) et analysés
   seulement bourse US ouverte (`xstocks_us_hours_only`).
   **Le club trade uniquement les futures perpétuels Kraken (PF_…)** : `perps_only=True` dans `bot/.../config.py` (le bot n'analyse que les PF_),
   `trade_mode='futures'` par défaut côté site (`fees.js` : `perpsSeulement`, `venueEffective`, liste réelle des perpétuels via `setPerps`).
4. Jamais « trade sûr », « gain garanti », « aucun risque », « machine à cash ».
5. La clé Supabase secrète (`sb_secret_…`, ou l'ancienne `service_role`) ne va **que** dans les secrets GitHub. Le site n'utilise que la clé publique
   (`sb_publishable_…` / `anon`) + RLS. Les clés `sb_` ne sont pas des JWT : jamais dans `Authorization: Bearer` (voir `cloud/supabase_rest.py`).
6. Réglages du bot : **admin seulement** (RLS `is_admin()` sur `bot_settings`, page `#/bot` réservée). Les membres passent par la boîte à idées
   privée (`#/idees`, table `ideas` : un membre ne lit que ses idées, l'admin les lit toutes et répond dans Mon compte).
7. Tout nouveau réglage modifiable depuis le site : ajouter la ligne dans `bot_settings` (schema.sql, avec min/max)
   ET dans `EDITABLE` de `bot/src/kraken_assistant/cloud/run.py` (bornes revérifiées).

## Ajouter…
- **une page** : `site/js/views/xxx.js` + route dans `ROUTES` (et `NAV` si besoin) dans `site/js/app.js` + fonctions dans `data.js` (et `demo.js`).
- **une stratégie** : `bot/src/kraken_assistant/strategies/xxx.py` (`NAME`, `find(a, s) -> list[Setup]`, utiliser `score_setup` et `finalize`),
  l'enregistrer dans `strategies/__init__.py`, ajouter son libellé dans `STRAT` (`site/js/ui.js`) et des tests dans `bot/tests/`.
- **une colonne/table** : `supabase/schema.sql` (idempotent + RLS) → l'utilisateur doit recoller le fichier dans le SQL Editor de Supabase.

## Tester (obligatoire avant de proposer un changement)
```bash
cd bot && pip install -e ".[dev]" && pytest -q                      # bot (≈ 1 min)
node --test site/js/tests/*.test.mjs netlify/tests/*.test.mjs        # calculs du site + fonctions Netlify
npm install --no-save @electric-sql/pglite && node supabase/test_schema.mjs   # schéma + sécurité RLS
cd site && python3 -m http.server 8080                               # aperçu en mode démo : http://localhost:8080
```
Vérifier aussi l'affichage mobile (390 px de large) : pas de défilement horizontal, barre d'onglets en bas.
