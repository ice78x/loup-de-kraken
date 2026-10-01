"""Traduction des titres de news en français (API gratuite MyMemory) + explication « ce que ça peut changer ».

- La traduction est une aide à la lecture : le titre ORIGINAL reste la référence (affiché et lié).
- Mémoire : chaque titre traduit est gardé dans la base locale (pas de nouvelle requête au scan suivant).
- Quota gratuit MyMemory : ~5 000 caractères/jour sans e-mail, ~50 000 avec un e-mail de contact
  (variable TRANSLATE_EMAIL, facultative). Requête limitée à 500 octets.
- En cas d'échec (quota, réseau) : on garde l'anglais et on le dit. Jamais de texte inventé.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os

import httpx

log = logging.getLogger(__name__)
API = "https://api.mymemory.translated.net/get"


class Translator:
    def __init__(self, db=None, transport: httpx.BaseTransport | None = None, email: str | None = None,
                 max_calls: int = 12):
        self.db = db
        self.transport = transport
        self.email = (email if email is not None else os.environ.get("TRANSLATE_EMAIL", "")).strip()
        self.max_calls = max_calls  # garde-fou par scan pour ménager le quota gratuit
        self.calls = 0
        self.disabled = False

    @staticmethod
    def _key(text: str) -> str:
        return "tr:fr:" + hashlib.sha1(text.encode("utf-8")).hexdigest()

    def fr(self, text: str) -> str | None:
        """Traduction française du texte, ou None si indisponible (on affichera alors l'original)."""
        text = (text or "").strip()
        if not text:
            return None
        k = self._key(text)
        if self.db is not None:
            cached = self.db.kv_get(k)
            if cached:
                return cached
        if self.disabled or self.calls >= self.max_calls:
            return None
        q = text.encode("utf-8")[:480].decode("utf-8", "ignore")
        params = {"q": q, "langpair": "en|fr"}
        if self.email:
            params["de"] = self.email
        self.calls += 1
        try:
            with httpx.Client(timeout=8, transport=self.transport) as c:
                r = c.get(API, params=params)
            b = r.json()
            out = html.unescape(str((b.get("responseData") or {}).get("translatedText") or "")).strip()
            status = int(b.get("responseStatus") or r.status_code)
            if status != 200 or not out or "MYMEMORY WARNING" in out.upper() or b.get("quotaFinished"):
                if status == 429 or b.get("quotaFinished") or "MYMEMORY WARNING" in out.upper():
                    self.disabled = True  # quota atteint : on arrête pour ce scan
                log.info("traduction indisponible (statut %s)", status)
                return None
        except (httpx.HTTPError, ValueError) as e:
            log.info("traduction indisponible (%s)", type(e).__name__)
            return None
        if self.db is not None:
            self.db.kv_set(k, out)
        return out


# ------------------------------------------------------------- explications en français simple
CE_QUE_CA_CHANGE = {
    "Fed": "Les décisions de la Fed (banque centrale américaine) font bouger le dollar et presque tous les marchés. "
           "Des taux en baisse sont souvent favorables aux cryptos et aux actions, des taux en hausse les freinent.",
    "BCE": "La BCE fixe les taux en zone euro : elle fait bouger l'euro face au dollar, et donc la conversion de tes gains.",
    "Taux": "Le prix de l'argent change : taux en baisse, souvent favorable aux actifs risqués (cryptos, actions) ; en hausse, l'inverse.",
    "Inflation": "Une inflation plus forte que prévu fait craindre des taux élevés plus longtemps (souvent négatif pour cryptos et actions) ; "
                 "plus faible que prévu, souvent l'inverse.",
    "Emploi": "Des chiffres de l'emploi solides peuvent retarder les baisses de taux, des chiffres faibles les rapprocher. "
              "Les prix bougent souvent fort à la publication.",
    "Géopolitique": "Quand les tensions montent, les investisseurs fuient le risque : l'or et le pétrole montent souvent, "
                    "cryptos et actions baissent souvent.",
    "Régulation": "Une décision d'un régulateur ou d'un tribunal peut faire bouger fortement l'actif concerné : "
                  "favorable si c'est une autorisation ou un abandon de poursuites, défavorable si c'est une plainte ou une interdiction.",
    "ETF": "Un ETF permet aux grands investisseurs d'acheter l'actif facilement : approbation ou entrées d'argent = plus de demande ; "
           "refus ou sorties = l'inverse.",
    "Hack/Exploit": "Un piratage fait souvent chuter vite l'actif concerné, parfois tout son écosystème. Prudence avant tout achat.",
    "Faillite": "Une faillite peut provoquer des ventes forcées et toucher d'autres actifs liés.",
    "Liquidations": "Des liquidations en masse accélèrent les mouvements (effet cascade), puis le prix rebondit parfois. "
                    "Mieux vaut attendre que ça se calme.",
    "Listing": "Arriver sur une grande plateforme rend l'actif plus facile à acheter : souvent une hausse rapide, parfois suivie d'une retombée.",
    "Delisting": "Un retrait de cotation réduit le nombre d'acheteurs possibles : souvent négatif pour l'actif.",
    "Upgrade/Fork": "Une mise à jour du réseau attire l'attention avant l'événement ; après, le mouvement retombe souvent.",
    "Partenariat/Institutionnel": "L'arrivée de grands acteurs peut soutenir la demande sur l'actif concerné.",
    "Token unlock": "Des jetons jusque-là bloqués arrivent sur le marché : risque de pression vendeuse.",
    "Gros transferts": "Un gros transfert vers une plateforme peut annoncer une vente. Signal faible, à ne pas trader seul.",
    "Résultats": "Les résultats trimestriels font souvent bouger fortement l'action (et son xStock), dans un sens ou dans l'autre.",
    "Incident exchange": "Un incident technique peut bloquer des ordres : vérifie que Kraken fonctionne normalement avant de trader.",
}


def explain(n) -> str:
    """Explication courte en français : ce que ce type de news peut changer, et quoi en faire. Interprétation, pas un fait."""
    parts: list[str] = []
    for c in n.categories or []:
        if c in CE_QUE_CA_CHANGE:
            parts.append(CE_QUE_CA_CHANGE[c])
            break
    who = ", ".join(n.assets) if n.assets else ("tout le marché" if n.macro else "")
    if n.is_rumor:
        parts.append("C'est formulé comme une rumeur : à ne pas trader tant que ce n'est pas confirmé.")
    elif not n.verified:
        parts.append("Une seule source non officielle pour l'instant : à confirmer avant d'en tenir compte.")
    if not n.is_rumor:
        if n.direction_hint == "haussier" and who:
            parts.append(f"Lecture automatique : plutôt favorable pour {who}.")
        elif n.direction_hint == "baissier" and who:
            parts.append(f"Lecture automatique : plutôt défavorable pour {who}.")
        elif who:
            parts.append(f"Concerne {who} ; le sens n'est pas clair : regarde d'abord comment le prix réagit.")
    if n.impact >= 3 and not n.is_rumor:
        parts.append("Impact potentiel fort : mouvements rapides possibles. N'entre qu'après une clôture 15 min qui confirme.")
    if not parts:
        parts.append("Pas d'effet clair attendu sur les marchés suivis par le bot.")
    return " ".join(parts)
