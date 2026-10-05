# 🐺 Le Loup de Kraken

Le site privé de ton club de trading :

- **le bot** analyse Kraken toutes les 15 minutes et publie ses trades 🟢 / 🟡 / 🛑 ;
- **chaque membre** a son compte et son solde, et enregistre ses trades : ceux du bot, ou les siens (choix de l'entrée, du SL, des TP et du multiplicateur) ;
- **tout le club** voit l'historique et le classement ;
- **chaque membre** peut envoyer ses idées d'amélioration à l'admin (seul l'admin règle le bot) ;
- **ça marche sur téléphone** : le site s'installe comme une application.

> ⚠️ Le bot cherche les meilleures occasions et calcule le risque, mais **aucun trade n'est garanti**.
> Le site n'envoie **jamais** d'ordre sur Kraken : tu passes tes ordres toi-même dans l'app Kraken, puis tu les enregistres ici.

**Coût : 0 €.** Tout tourne sur des offres gratuites :
- GitHub garde le code et fait tourner le bot ;
- Supabase gère les comptes et la base de données ;
- Netlify héberge le site.

Si une limite gratuite était dépassée, le service concerné se met en pause jusqu'au mois suivant. **Rien n'est jamais facturé sans carte bancaire.**

---

## 👀 Voir le site tout de suite (mode démo)

Sans rien configurer, tu peux voir à quoi il ressemble :

```bash
cd ~/Documents/loup-de-kraken/site
python3 -m http.server 8080
```
Ouvre **http://localhost:8080**.

Un bandeau jaune indique **« Mode démo : données fictives »**. C'est normal tant que Supabase n'est pas configuré.
Pour arrêter : **Ctrl + C** dans le Terminal.

---

## 🚀 Mettre le site en ligne (environ 45 minutes, une seule fois)

Tu vas créer 3 comptes gratuits. Le plus simple : crée d'abord le compte GitHub, puis utilise « Continuer avec GitHub » pour les deux autres.

### Étape 1 : mettre le code sur GitHub

1. Crée un compte sur **https://github.com**.
2. Installe **GitHub Desktop** : **https://desktop.github.com**. Ouvre-le et connecte-toi.
3. Décompresse `loup-de-kraken.zip` et place le dossier dans **Documents**.
4. Dans GitHub Desktop : **File → Add local repository…** → choisis le dossier `loup-de-kraken`.
   - S'il te propose **« create a repository »**, clique dessus, puis sur **Create repository**.
5. Clique sur **Publish repository**. **Laisse cochée la case « Keep this code private »**, puis clique sur **Publish**.

✅ Ton code est sur GitHub, en privé.

### Étape 2 : créer la base de données (Supabase)

1. Va sur **https://supabase.com** → **Start your project** → connecte-toi avec GitHub.
2. **New project** :
   - nom : `loup-de-kraken` ;
   - choisis un **mot de passe** (note-le quelque part) ;
   - région : **West EU (Paris)** ou **Central EU (Frankfurt)**.

   Clique sur **Create**, puis attends environ 2 minutes.
3. Menu de gauche → **SQL Editor** → **New query**.
4. Ouvre le fichier `supabase/schema.sql` avec TextEdit, **copie tout** et colle-le dans Supabase, puis clique sur **Run**.
   Tu dois voir **« Success »**.
5. Menu de gauche → **Authentication** → **Sign In / Providers** (ou **Providers**) → **Email** :
   - **décoche « Confirm email »**, puis **Save**.
   - *Pourquoi :* l'envoi d'e-mails gratuit de Supabase est très limité. Sans cette option, tes amis ne pourraient pas s'inscrire. La sécurité reste assurée : chaque nouveau compte doit être **approuvé par toi**.
6. Copie 3 valeurs (garde-les dans une note, supprime-la à la fin) :
   - **Project URL** (ex. `https://abcd.supabase.co`) : bouton **Connect** en haut du projet ;
   - clé **publique** : **Project Settings → API Keys → Publishable key** (`sb_publishable_…`, ancien nom « anon ») ;
   - clé **secrète** : même page, **Secret keys** (`sb_secret_…`, ancien nom « service_role »). 🔒 Elle ne va **que** dans GitHub, jamais dans le site.

   Si ton projet affiche encore les anciennes clés `eyJ…` (« anon » / « service_role »), elles marchent aussi.

### Étape 3 : relier le site à ta base

1. Ouvre `site/config.js` avec TextEdit.
2. Colle l'URL et la clé **publique** entre les guillemets déjà présents (ne retape pas les guillemets : TextEdit les rend « courbes » et le site ne démarre plus) :
   ```js
   SUPABASE_URL: "https://abcd.supabase.co",
   SUPABASE_ANON_KEY: "sb_publishable_xxxx",
   ```
3. Enregistre (⌘ + S).
4. Dans GitHub Desktop, en bas à gauche : écris `Configuration Supabase`, clique sur **Commit to main**, puis sur **Push origin**.

### Étape 4 : allumer le bot (GitHub Actions)

1. Sur **github.com**, ouvre ton dépôt `loup-de-kraken`.
2. **Settings → Secrets and variables → Actions → New repository secret**. Ajoute ces 2 secrets :

   | Nom | Valeur |
   |---|---|
   | `SUPABASE_URL` | ton Project URL |
   | `SUPABASE_SERVICE_KEY` | ta clé **secrète** (`sb_secret_…`) |

3. Onglet **Actions**. Si GitHub demande d'activer les workflows, clique sur **I understand… enable them**.
4. À gauche, clique sur **scan** → **Run workflow** → **Run workflow**.
5. Attends 2 à 4 minutes. La ligne doit devenir **verte ✅**.
   - En cas de croix rouge ❌ : clique dessus et envoie-moi le texte rouge.

Ensuite, le bot tourne **tout seul toutes les 15 minutes, 24 h / 24**. Il optimise ses réglages **chaque dimanche**.

### Étape 5 : mettre le site en ligne (Netlify)

1. Va sur **https://app.netlify.com** et connecte-toi avec GitHub.
2. **Add new site → Import an existing project → GitHub** → choisis `loup-de-kraken`.
3. Netlify lit tout seul les réglages (fichier `netlify.toml`). Clique sur **Deploy**.
4. Après environ 1 minute, tu as une adresse du type **`https://nom-au-hasard.netlify.app`**.
   - Pour la changer : **Site configuration → Change site name** (ex. `loup-de-kraken-ice`).

### Étape 6 : activer le bouton « Scanner maintenant » (facultatif mais pratique)

Sans cette étape, le site marche quand même : le bot scanne tout seul (toutes les 15 min avec Netlify, sinon toutes les 30 min environ).

1. **Crée un jeton GitHub :**
   1. Sur GitHub : ta photo → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
   2. Nom : `bouton scan` ; expiration : 1 an.
   3. **Repository access → Only select repositories →** `loup-de-kraken`.
   4. **Permissions → Repository permissions → Actions : Read and write.**
   5. **Generate token**, puis copie le jeton (il ne s'affiche qu'une fois).
2. **Ajoute les variables dans Netlify :**
   1. Va dans **Site configuration → Environment variables → Add a variable**, et ajoute ces 4 variables :

      | Nom | Valeur |
      |---|---|
      | `SUPABASE_URL` | ton Project URL |
      | `SUPABASE_ANON_KEY` | ta clé **publique** (`sb_publishable_…`) |
      | `GH_TOKEN` | le jeton GitHub |
      | `GH_REPO` | `ton-pseudo-github/loup-de-kraken` |

   2. Onglet **Deploys → Trigger deploy → Deploy site**, pour que les variables soient prises en compte.

### Étape 7 : créer ton compte et inviter tes amis

1. Ouvre l'adresse de ton site, onglet **Créer un compte**.
   **Le premier compte créé devient administrateur.** Fais-le donc avant d'envoyer le lien.
2. Envoie l'adresse du site à tes amis. Ils créent leur compte, puis attendent.
3. Dans **Mon compte → Membres**, clique sur **Approuver** pour chacun.
4. (Conseillé) Dans Supabase : **Authentication → URL Configuration → Site URL**, mets l'adresse de ton site.

### Étape 8 : l'installer sur ton téléphone

- **iPhone (Safari)** : bouton Partager → **Sur l'écran d'accueil**.
- **Android (Chrome)** : menu ⋮ → **Installer l'application**.

L'icône du loup apparaît sur ton écran, comme une vraie app.

---

## 📱 Comment on s'en sert

| Page | Ce qu'on y fait |
|---|---|
| **Accueil** | Le verdict du bot (🟢 trade validé / 🟡 à surveiller / 🛑 on attend), mis à jour en direct (**SL touché** / **TP1 touché**), chaque setup avec son **levier conseillé** et ses résultats en **% de ta mise**, ton solde, les news, le bouton **Scanner maintenant** |
| **Graphiques** | Toutes les paires Kraken Pro France en 3 onglets (cryptos / xStocks / matières premières). Chaque paire : graphique en direct (5 min → 1 jour), outils d'analyse expliqués (EMA, volume, supports/résistances, structure HH/HL, RSI, VWAP), lecture rapide, signaux du bot et trades du club sur cette paire |
| **Signal** | Le graphique, l'échelle de prix (SL, entrée, TP à leur vraie distance), le plan en clair, **Prendre ce trade**, et comment le passer dans l'app Kraken |
| **Mes trades** | Tes trades en cours (gain ou perte en direct, conseil du bot), ton historique, tes statistiques. Tu peux encaisser une partie, déplacer le SL ou clôturer |
| **Trade manuel** | Comme sur Kraken : l'actif (menu déroulant), le sens, la **quantité**, le type d'ordre (limite / marché), le **levier**, le SL et les TP. Le site affiche la marge isolée, la perte au stop ou à la liquidation, les gains et les **frais Kraken réels** |
| **Le club** | Classement (en R, pour être juste entre petits et gros soldes), trades de tout le monde, page de chaque membre |
| **Idées** | Formulaire pour proposer une amélioration : elle arrive directement chez l'admin, qui répond |
| **Le bot** (admin) | Comment il décide, ses résultats historiques, ses réglages. Lien dans Mon compte, réservé à l'admin |
| **Apprendre** | Les règles, le lexique, les **graphiques d'exemple** de chaque situation, une calculette de risque |
| **Mon compte** | Pseudo, **solde modifiable à tout moment**, risque par trade, garde-fous, historique du solde. Pour l'admin : idées reçues, réglages du bot, approbation des membres |

**Paires en dollars.** Le bot ne propose que des paires cotées en **USD** (BTC/USD, ETH/USD, xStocks…), comme sur ton compte.
Ton solde et ton risque restent en **euros** : le site convertit avec le taux EUR/USD de Kraken du moment.
Pour autoriser aussi les paires en euros : page **Le bot → Paires analysées**.

**Frais.** Le site utilise la grille officielle Kraken Pro (niveau d'entrée, vérifiée le 01/10/2026) : futures 0,02 % (limite) / 0,05 % (marché),
xStocks 0 % / 0,10 % (0,08 % dès le 05/10/2026), stablecoins 0,20 %, spot crypto 0,40 % / 0,80 %. Fichiers : `site/js/fees.js` et `bot/src/kraken_assistant/risk/fees.py`.

**Paper ou réel ?** À chaque trade enregistré, tu choisis :
- **Paper (entraînement)** : le bot le suit tout seul sur les vrais prix Kraken. Il encaisse les TP, coupe au SL, et remonte le SL quand c'est confirmé.
- **Réel** : tu as passé l'ordre sur Kraken. Le site le suit et te conseille, mais c'est **toi** qui agis sur Kraken. Tu peux corriger les prix à la main.

---

## 🛡️ Sécurité (ce qui est déjà en place)

- **Club fermé :** chaque compte doit être approuvé par un admin. Personne d'autre ne voit rien.
- **Chacun ne modifie que ses propres trades et son propre solde** (règles de sécurité dans la base, testées).
- **La clé secrète Supabase (`sb_secret_…` / `service_role`) n'est que dans GitHub (secret)**, jamais dans le site.
- **Aucune clé Kraken n'est stockée** : le site ne peut donc pas trader à ta place ni retirer de l'argent.
- **Les réglages du bot ont des limites qu'on ne peut pas dépasser**, et chaque changement est journalisé.
- **Moteurs de recherche :** le site leur demande de ne pas l'indexer (`noindex`).

---

## 🤖 Améliorer le bot et le site avec Claude

Le fichier **`CLAUDE.md`** explique le projet à Claude (structure, règles, tests).

Pour faire une modification :
1. Ouvre le dossier avec **Claude** : Claude Code, ou une conversation où tu relies ton dépôt GitHub.
2. Demande en français, par exemple : « Ajoute une alerte Telegram quand un 🟢 sort ».
3. Claude modifie le code et lance les tests.
4. Tu envoies sur GitHub (GitHub Desktop → **Commit**, puis **Push**).

Ensuite, tout est automatique :
- GitHub relance les tests ;
- Netlify met le site à jour en 1 minute ;
- le bot utilise la nouvelle version au scan suivant.

Pour que tes amis puissent aussi modifier le code : sur GitHub, **Settings → Collaborators → Add people**.

---

## 💶 Limites gratuites (largement suffisantes pour un club d'amis)

| Service | Offre gratuite | Utilisation prévue |
|---|---|---|
| GitHub Actions (dépôt privé) | 2 000 min/mois | environ 1 600 min (18 scans par jour + 1 optimisation par semaine) |
| Supabase | 500 Mo de base, 50 000 utilisateurs | quelques Mo (les scans de plus de 60 jours sont effacés) |
| Netlify | 125 000 appels de fonctions, 100 Go/mois | prix en direct toutes les 30 s seulement quand la page est ouverte |

Si les minutes GitHub devenaient justes, tu as deux options :
- espacer les scans : dans `.github/workflows/scan.yml`, remplacer `5 * * * *` par `5 4-21 * * *` (de 6 h à 23 h seulement) ;
- rendre le dépôt public : les minutes deviennent illimitées, mais le code est alors visible de tous (aucun secret n'y est).

---

## 🆘 Problèmes fréquents

| Problème | Solution |
|---|---|
| Le bandeau « Mode démo » reste affiché en ligne | `site/config.js` n'est pas rempli ou pas envoyé sur GitHub (étape 3, puis Commit + Push) |
| « Invalid API key » à la connexion | Tu as collé la mauvaise clé : il faut la clé **publique** (`sb_publishable_…`) dans `config.js` |
| Un ami ne peut pas s'inscrire | Vérifie que « Confirm email » est bien **décoché** (étape 2.5) |
| « Le bot n'a pas encore scanné » | Lance le workflow **scan** à la main (étape 4) et vérifie qu'il est vert |
| Le workflow scan est rouge | Vérifie les 2 secrets GitHub (étape 4), puis envoie-moi l'erreur |
| « Scanner maintenant » affiche une erreur | Vérifie les 4 variables Netlify et le jeton GitHub (étape 6), puis redéploie |
| Prix en direct indisponibles | Kraken ne répond pas ou le site n'est pas sur Netlify (en local, pas de prix réels) |

---

## 🗂️ Ce qu'il y a dans le dossier

```
site/        le site (HTML/CSS/JavaScript, aucun outil à installer)
netlify/     les 2 petites fonctions serveur (prix Kraken en direct, bouton scan)
supabase/    le schéma de la base (à coller une fois dans Supabase) + son test
bot/         le bot d'analyse (Python) : le même assistant que ta version locale
.github/     les tâches automatiques : scan chaque heure, optimisation le dimanche, tests
CLAUDE.md    le mode d'emploi du projet pour Claude
```

Tu peux toujours utiliser le bot en local, sur ton Mac : voir `bot/README.md`.
