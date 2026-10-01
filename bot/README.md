# Kraken Assistant : le guide pour débutant

Ce guide t'explique **pas à pas** comment installer et utiliser ton assistant de trading.
Tu n'as pas besoin de savoir programmer : il suffit de **copier-coller** les commandes indiquées.

> ⚠️ **À lire avant tout**
> L'assistant t'aide à repérer des occasions de trade et à calculer ton risque.
> Il **ne garantit aucun gain**. Chaque trade peut perdre de l'argent.
> Par défaut, il fonctionne en **mode entraînement (PAPER)** : **aucun vrai ordre n'est jamais envoyé**.

---

## 🧭 C'est quoi, en une minute ?

L'assistant fait 4 choses pour toi :

1. **Il surveille les marchés** de Kraken (cryptos, xStocks, matières premières) toutes les heures.
2. **Il lit les news importantes** (Fed, BCE, hacks, ETF…) et **l'historique des graphiques**.
3. **Il te dit quoi faire**, avec un code couleur simple :
   - 🟢 **TRADE VALIDÉ** : une occasion propre. Il te donne l'entrée, le stop (SL), les objectifs (TP), la taille et le risque.
   - 🟡 **SURVEILLER** : ça se prépare, mais ce n'est pas encore le moment.
   - 🛑 **AUCUN TRADE** : rien d'intéressant, on attend.
4. **Il protège ton capital** : jamais plus de **1 %** de risque par trade (0,90 € sur 90 €), et arrêt pour la journée si tu perds **3 %**.

---

## 📖 Petit lexique (les mots utilisés)

| Mot | Ce que ça veut dire |
|---|---|
| **LONG** | Tu paries que le prix va **monter** |
| **SHORT** | Tu paries que le prix va **baisser** |
| **ENTRY** (entrée) | Le prix auquel tu entres dans le trade |
| **SL** (Stop Loss) | Le prix où tu **coupes ta perte**. C'est ta protection, **toujours obligatoire** |
| **TP** (Take Profit) | Les prix où tu **encaisses tes gains** (TP1, TP2, TP3) |
| **R** ou **R:R** | Combien tu peux gagner par rapport à ce que tu risques. « 2R » = tu peux gagner 2 fois ce que tu risques |
| **Levier** (x2, x3…) | Un « emprunt » pour ouvrir une position plus grosse. Ici, il ne sert **jamais** à risquer plus |
| **PAPER** | Mode entraînement : de faux trades sur les vrais prix, sans argent réel |
| **LIVE** | Mode réel : de vrais ordres sur ton compte Kraken. **Désactivé** au départ |
| **Clé API** | Un « badge d'accès » qui permet à l'assistant de **lire** ton compte Kraken |

---

## 🛠️ ÉTAPE 1 : Installer (une seule fois, environ 15 minutes)

### 1.1 Installer Python (le moteur qui fait tourner l'assistant)

1. Va sur **https://www.python.org/downloads/macos/**
2. Clique sur le gros bouton jaune **« Download Python 3.12 »** (ou plus récent).
3. Ouvre le fichier téléchargé (`.pkg`) et clique sur **Continuer** jusqu'à **Installer**.
4. À la fin, une fenêtre s'ouvre. Double-clique sur **« Install Certificates.command »** (important pour Internet).

### 1.2 Mettre le dossier du projet au bon endroit

1. Trouve le fichier **`kraken-assistant.zip`** (dans tes **Téléchargements**).
2. **Double-clique** dessus : un dossier **`kraken-assistant`** apparaît.
3. **Glisse ce dossier dans « Documents »**.

### 1.3 Ouvrir le Terminal

Le Terminal est une fenêtre où l'on tape des commandes.

1. Appuie sur **⌘ Cmd + Espace**.
2. Tape **Terminal**, puis appuie sur **Entrée**.
3. Une fenêtre blanche ou noire s'ouvre. C'est normal.

> 💡 Dans tout ce guide : **copie** la ligne grise, **colle-la** dans le Terminal (⌘ Cmd + V), puis appuie sur **Entrée**.

### 1.4 Installer l'assistant

Copie-colle ces lignes **une par une** (Entrée après chacune) :

```bash
cd ~/Documents/kraken-assistant
```
*(Tu entres dans le dossier du projet.)*

```bash
python3 -m venv .venv
```
*(Tu crées un espace réservé à l'assistant. Rien ne s'affiche : c'est normal.)*

```bash
source .venv/bin/activate
```
*(Tu actives cet espace. Tu dois voir `(.venv)` au début de la ligne.)*

```bash
pip install -e ".[dev]"
```
*(Tu installes les outils nécessaires. Ça prend 1 à 3 minutes, avec beaucoup de texte qui défile.)*

```bash
cp .env.example .env
```
*(Tu crées ton fichier de réglages personnel.)*

### 1.5 Vérifier que tout marche

```bash
pytest -q
```
Attends environ une minute. Tu dois voir à la fin quelque chose comme **`86 passed`** ✅.
Si tu vois `failed` en rouge, copie le message et envoie-le moi.

---

## ▶️ ÉTAPE 2 : Lancer l'assistant (à chaque utilisation)

À chaque fois que tu veux utiliser l'assistant :

1. Ouvre le **Terminal** (⌘ Cmd + Espace → Terminal).
2. Copie-colle ces 3 lignes :

```bash
cd ~/Documents/kraken-assistant
source .venv/bin/activate
python -m kraken_assistant serve
```

3. Ouvre ton navigateur (Safari, Chrome…) et va sur : **http://127.0.0.1:8000**

🎉 Tu vois ton **tableau de bord** !

> ⚠️ **Laisse le Terminal ouvert** tant que tu utilises l'assistant. Si tu le fermes, l'assistant s'arrête.
> Pour l'arrêter proprement : clique dans le Terminal et appuie sur **Ctrl + C**.

> 💡 Tant que le Terminal reste ouvert, l'assistant **scanne tout seul toutes les heures**. Tu n'as rien à faire.

---

## 🖥️ ÉTAPE 3 : Utiliser le tableau de bord

### Ce que tu vois

- **CAPITAL** : ton argent d'entraînement (90 € au départ).
- **RISQUE DISPONIBLE** : combien tu peux encore risquer aujourd'hui.
- **POSITIONS** : tes trades en cours.
- **SCAN** : l'heure du dernier et du prochain scan.
- **OPPORTUNITÉS** : chaque actif avec son état (LONG, SHORT, SURVEILLER ou WAIT = attendre).
- **NEWS IMPORTANTES** : ce qui peut faire bouger les marchés.

### Les boutons

| Bouton | À quoi il sert |
|---|---|
| **SCAN** | Analyser tous les marchés **maintenant** (1 à 3 minutes) |
| **SCAN URGENT** | Réanalyser tout de suite après une grosse news ou un gros mouvement |
| **POSITIONS** | Voir tes trades en cours |
| **GESTION** | Te dire quoi faire sur tes trades en cours (garder, encaisser, bouger le stop…) |
| **RISQUE** | Voir combien tu risques |
| **PORTFOLIO** | Voir ton capital |
| **PAPER STATS** | Voir tes résultats d'entraînement |
| **NEWS** | Voir les news importantes en détail |
| **STATUS** | Vérifier que tout fonctionne |
| **AIDE** | La liste de toutes les commandes |

Tu peux aussi **taper une commande** dans la barre, puis cliquer sur **OK**.

---

## 🟢 ÉTAPE 4 : Lire un signal

Quand l'assistant trouve une occasion, tu reçois un bloc comme celui-ci :

```
🟢 TRADE VALIDÉ — LONG BTC/EUR

ENTRY   84 900 – 85 100 €     ← achète dans cette zone
SL      84 300 €              ← ton stop : c'est là que tu coupes si ça va mal
TP1     85 700 €              ← tu encaisses 30 % de la position
TP2     86 500 €              ← tu encaisses 40 %
TP3     87 500 €              ← tu encaisses les 30 % restants
LEVIER  x3
RISQUE  0,90 € / 1 %          ← le maximum que tu peux perdre sur ce trade
TAILLE  0.00065 BTC           ← la quantité à acheter

INVALIDATION  Clôture 15m sous 84 300 €   ← si ça arrive, le scénario est raté
ACTION : ENTRÉE               ← ou « ATTENDRE LE RETEST »
```

**Les règles simples à suivre :**
1. **Mets TOUJOURS le SL**, dès l'ouverture du trade.
2. Au **TP1**, encaisse 30 %. Ensuite, clique sur **GESTION** : l'assistant te dira s'il faut remonter ton stop.
3. Si l'**INVALIDATION** se produit, **sors du trade**, même si le SL n'est pas touché.
4. **« ATTENDRE LE RETEST »** = n'achète pas tout de suite. Place un ordre à cours limité dans la zone d'entrée.

---

## 🧪 ÉTAPE 5 : S'entraîner en PAPER (commence par là !)

Le mode PAPER, c'est un **simulateur** : vrais prix, faux argent.

1. Clique sur **SCAN**.
2. Si un 🟢 apparaît, clique sur le bouton **« Ouvrir en PAPER »** sous le signal.
3. L'assistant suit le trade tout seul :
   - il encaisse les TP ;
   - il coupe au SL ;
   - il remonte le stop quand c'est justifié.
4. Clique sur **PAPER STATS** pour voir tes résultats :
   - combien de trades ;
   - combien de gagnants ;
   - le pourcentage de réussite ;
   - le gain ou la perte.

> 🎯 **Conseil important** : fais **au moins 30 à 50 trades en PAPER** avant de penser à l'argent réel.
> C'est le seul moyen de savoir si la méthode marche **pour toi**.

---

## 🔑 ÉTAPE 6 (facultative) : Relier ton compte Kraken

**Sans ça, tout fonctionne déjà** (les prix de Kraken sont publics).
Avec, l'assistant voit en plus **tes vraies positions, ton vrai solde et tes vrais frais**.

### Créer une clé « lecture seule »

1. Connecte-toi sur **pro.kraken.com**.
2. Clique sur ton profil → **Settings** (Paramètres) → **API**.
3. Clique sur **Create API key** (Créer une clé).
4. Coche **UNIQUEMENT** ces cases :
   - ✅ **Query Funds**
   - ✅ **Query Open Orders & Trades**
   - ✅ **Query Closed Orders & Trades**
5. **NE COCHE PAS** « Create & Modify Orders ».
6. **NE COCHE JAMAIS** « Withdraw Funds » (retrait d'argent).
7. Clique sur **Generate key**. Kraken t'affiche **une clé (API Key)** et **un secret (Private Key)**. Garde la page ouverte.

### Coller la clé dans l'assistant

1. Dans le Terminal, tape :
   ```bash
   open -e ~/Documents/kraken-assistant/.env
   ```
   Le fichier de réglages s'ouvre dans TextEdit.
2. Trouve ces deux lignes et colle ta clé et ton secret **après le signe =**, sans espace :
   ```
   KRAKEN_API_KEY=ta_clé_ici
   KRAKEN_API_SECRET=ton_secret_ici
   ```
3. Sur la ligne `USER_AGENT=`, remplace `ton-email@exemple.com` par **ton e-mail**. Certaines sources de news l'exigent.
4. Enregistre (⌘ Cmd + S) et ferme.
5. **Relance l'assistant** : Ctrl + C dans le Terminal, puis `python -m kraken_assistant serve`.

> 🔒 Ce fichier `.env` reste **uniquement sur ton ordinateur**. Ne l'envoie à personne. Ne le montre à personne.

---

## 📚 ÉTAPE 7 (facultative) : Donner tout l'historique des graphiques

L'assistant apprend du passé pour choisir de meilleurs trades.
Il récupère déjà tout seul **2 ans de journalier** et **tout l'hebdomadaire**, et son historique grandit à chaque scan.

**Pour lui donner tout l'historique d'un coup :**
1. Va sur **support.kraken.com** et cherche **« Downloadable historical OHLCVT data »**.
2. Télécharge l'archive et **décompresse-la** (double-clic).
3. Dans la barre de commande du tableau de bord, tape :
   ```
   HISTORIQUE IMPORT /Users/TON_NOM/Downloads/Kraken_OHLCVT
   ```
   *(Remplace le chemin par celui de ton dossier. Astuce : glisse le dossier dans le Terminal pour obtenir son chemin exact.)*
4. Puis tape **`OPTIMISER`**. L'assistant teste ses stratégies sur tout l'historique et garde les réglages qui ont fonctionné **sur des périodes qu'il n'avait pas vues pendant le réglage**. Il refait ce travail tout seul chaque nuit à 3 h, si l'assistant tourne.
5. Tape **`EDGE`** pour voir les résultats passés de chaque stratégie.

---

## 🔴 ÉTAPE 8 (plus tard, prudence) : Passer en argent réel

**Ne fais pas ça tant que tes statistiques PAPER ne sont pas bonnes sur au moins 30 à 50 trades.**

L'assistant a **3 verrous de sécurité** pour qu'aucun ordre réel ne parte par accident :
1. Dans le fichier `.env` : `LIVE_TRADING=true`
2. Dans le fichier `.env` : `LIVE_TRADING_ACK=J_ACCEPTE_LE_RISQUE_REEL`
3. Pour **chaque** ordre, tu tapes `LIVE PREPARE <numéro>`. L'assistant affiche tout (risque, taille, prix) et te donne un **code** valable 2 minutes. Tu confirmes avec `CONFIRMER <ticket> <code>`.

Il faut aussi ajouter la permission « Create & Modify Orders » à ta clé Kraken.
Fais ton **premier essai avec la plus petite taille possible**.

---

## 🆘 Problèmes fréquents

| Problème | Solution |
|---|---|
| `command not found: python3` | Python n'est pas installé : refais l'étape 1.1 |
| `(.venv)` n'apparaît pas | Refais `cd ~/Documents/kraken-assistant` puis `source .venv/bin/activate` |
| La page http://127.0.0.1:8000 ne s'ouvre pas | Vérifie que le Terminal est ouvert et que l'assistant tourne (étape 2) |
| « DATA INSUFFISANTE — PAS DE TRADE » | Internet ou Kraken ne répond pas. Vérifie ta connexion, puis clique sur **STATUS** |
| Toujours 🛑 AUCUN TRADE | C'est normal : l'assistant ne force jamais un trade. Les bonnes occasions sont rares |
| « accès compte non vérifié » dans un signal | Tu n'as pas mis de clé API (étape 6). Vérifie sur Kraken que l'actif est bien disponible pour toi |
| Autre erreur | Copie le message du Terminal et envoie-le moi |

---

## 📌 Les 5 règles d'or

1. **Toujours un SL.** Sans exception.
2. **Jamais plus de 1 % de risque par trade** (0,90 € sur 90 €). L'assistant le calcule pour toi.
3. **Stop pour la journée à −3 %.** L'assistant bloque les nouveaux trades.
4. **Pas de 🟢 = pas de trade.** Ne force rien.
5. **PAPER d'abord**, argent réel ensuite, et seulement si les statistiques le justifient.

---

*Pour les détails techniques (architecture, réglages avancés, limites) : voir `docs/GUIDE-TECHNIQUE.md`.*
