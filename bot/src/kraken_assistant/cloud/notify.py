"""Notifications Telegram : un message dès qu'un scan publie un 🟢 (ou 🔥 A+), même si personne n'est sur le site.

Configuration (secrets GitHub, jamais dans le code) :
  TELEGRAM_BOT_TOKEN  jeton donné par @BotFather
  TELEGRAM_CHAT_ID    identifiant de la conversation (plusieurs possibles, séparés par des virgules : toi, un groupe du club…)
Sans ces deux secrets, rien n'est envoyé. Le jeton n'apparaît jamais dans les journaux.
Pas de doublon : un même actif dans le même sens déjà notifié dans les 4 dernières heures n'est pas renvoyé.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("cloud")
SITE = "https://loup-2-kraken.netlify.app"
REGIMES = {"TREND_UP": "tendance haussière", "TREND_DOWN": "tendance baissière", "RANGE": "range",
           "BREAKOUT_UP": "cassure haussière", "BREAKOUT_DOWN": "cassure baissière"}


def _px(x) -> str:
    if x is None:
        return "—"
    x = float(x)
    return f"{x:,.{2 if x >= 100 else 4 if x >= 1 else 6}f}".replace(",", " ").rstrip("0").rstrip(".")


def _base(display: str) -> str:
    d = (display or "").upper()
    if d.startswith("PF_"):
        d = d[3:]
        for q in ("USD", "EUR"):
            if d.endswith(q):
                d = d[: -len(q)]
        return "BTC" if d == "XBT" else d
    return d.split("/")[0]


def signal_message(row: dict, site: str = SITE) -> str:
    """Message court (TDAH) : verdict, niveaux, risque, invalidation, lien. Tout vient du signal publié."""
    e = html.escape
    L = row.get("direction") == "LONG"
    tete = "🔥 TRADE A+" if row.get("grade") == "A+" else "🟢 TRADE VALIDÉ"
    rr = row.get("rr_net") or row.get("rr") or []
    lignes = [
        f"<b>{tete}</b>",
        f"<b>{'LONG ↑' if L else 'SHORT ↓'} {e(_base(row.get('display', '')))}</b>  ({e(row.get('display', ''))})",
        f"Score {round(float(row.get('score') or 0))}/100" + (f" · {REGIMES.get(row.get('regime'), '')}" if row.get("regime") in REGIMES else ""),
        "",
        f"ENTRÉE  {_px(row.get('entry_low'))} – {_px(row.get('entry_high'))}",
        f"SL      {_px(row.get('sl'))}",
        f"TP1     {_px(row.get('tp1'))}",
        f"TP2     {_px(row.get('tp2'))}",
        f"TP3     {_px(row.get('tp3'))}",
    ]
    if len(rr) > 1:
        lignes.append(f"R:R net TP2 = {float(rr[1]):.1f}")
    lignes += ["RISQUE  1 % de ton solde", "GESTION TP1 30 % · TP2 40 % · TP3 30 %"]
    if row.get("invalidation"):
        lignes.append(f"INVALIDATION  {e(row['invalidation'])}")
    if row.get("action"):
        lignes.append(f"ACTION  {e(row['action'])}")
    lignes += ["", f'👉 <a href="{site}/#/signal/{row.get("id")}">Ouvrir le ticket sur le site</a>',
               "<i>Probabilité, pas garantie. Valable 4 h. Le stop te protège.</i>"]
    return "\n".join(lignes)


def send(text: str, token: str, chat_ids: list[str], client: httpx.Client | None = None) -> int:
    ok = 0
    c = client or httpx.Client(timeout=15)
    try:
        for chat in chat_ids:
            try:
                r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
                if r.status_code == 200 and r.json().get("ok"):
                    ok += 1
                else:
                    log.warning("Telegram a refusé le message (code %s) — vérifie TELEGRAM_CHAT_ID", r.status_code)
            except httpx.HTTPError as ex:
                log.warning("Telegram injoignable : %s", type(ex).__name__)
    finally:
        if client is None:
            c.close()
    return ok


def config() -> tuple[str, list[str]] | None:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chats = [x.strip() for x in (os.environ.get("TELEGRAM_CHAT_ID") or "").split(",") if x.strip()]
    return (token, chats) if token and chats else None


def heads_up_message(row: dict, site: str = SITE) -> str:
    """Pré-alerte : setup prouvé et bien noté, il ne manque que la confirmation 15 min. Ce n'est PAS encore un trade."""
    e = html.escape
    L = row.get("direction") == "LONG"
    lignes = [
        "<b>⏳ PRÉPARE-TOI</b> — pas encore un trade",
        f"<b>{'LONG ↑' if L else 'SHORT ↓'} {e(_base(row.get('display', '')))}</b>  ({e(row.get('display', ''))})",
        f"Score {round(float(row.get('score') or 0))}/100" + (f" · {REGIMES.get(row.get('regime'), '')}" if row.get("regime") in REGIMES else ""),
        "",
        f"IL MANQUE  {e(row.get('trigger_text') or 'la confirmation 15 min')}",
        f"ZONE  {_px(row.get('entry_low'))} – {_px(row.get('entry_high'))}",
        f"SL    {_px(row.get('sl'))}",
        f"TP1   {_px(row.get('tp1'))}",
        "",
        "👉 Prépare Kraken et ouvre le ticket. Quand le site affiche « ✅ Condition remplie », appuie sur « ⚡ Vérifier maintenant » :",
        f'<a href="{site}/#/signal/{row.get("id")}">Ouvrir le ticket</a>',
        "<i>N'entre pas avant le message 🟢. Si la condition n'arrive pas, on laisse passer.</i>",
    ]
    return "\n".join(lignes)


def _presque(r: dict) -> bool:
    return r.get("status") == "WATCH" and bool((r.get("quality") or {}).get("presque_pret"))


def notify_trades(sb, inserted: list[dict], client: httpx.Client | None = None, now: datetime | None = None) -> int:
    """Un message par nouveau 🟢, et une pré-alerte « ⏳ prépare-toi » pour un 🟡 à qui il ne manque que la confirmation.
    Pas de doublon sur 4 h (même actif, même sens) : un 🟢 n'est jamais bloqué par une pré-alerte."""
    cfg = config()
    trades = [r for r in inserted or [] if r.get("status") == "TRADE"]
    preps = [r for r in inserted or [] if _presque(r)]
    if not cfg or not (trades or preps):
        return 0
    token, chats = cfg
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=4)).isoformat()
    ids = {r.get("id") for r in trades + preps}
    try:
        recent = sb.select("signals", {"select": "id,instrument_key,direction,status,quality", "created_at": f"gte.{since}"}) or []
    except Exception as ex:  # la vérification des doublons ne doit jamais bloquer
        log.warning("doublons Telegram non vérifiés : %s", ex)
        recent = []
    recent = [r for r in recent if r.get("id") not in ids]
    deja_vert = {(r.get("instrument_key"), r.get("direction")) for r in recent if r.get("status") == "TRADE"}
    deja_prep = {(r.get("instrument_key"), r.get("direction")) for r in recent if _presque(r)}
    sent = 0
    for r in trades:
        k = (r.get("instrument_key"), r.get("direction"))
        if k in deja_vert:
            continue
        deja_vert.add(k)
        sent += send(signal_message(r), token, chats, client)
    for r in preps:
        k = (r.get("instrument_key"), r.get("direction"))
        if k in deja_vert or k in deja_prep:
            continue
        deja_prep.add(k)
        sent += send(heads_up_message(r), token, chats, client)
    if sent:
        log.info("Telegram : %d message(s) envoyé(s)", sent)
    return sent


WELCOME_KEY = "telegram_bienvenue"


def welcome_once(sb, client: httpx.Client | None = None) -> bool:
    """Premier scan après la configuration : un message « ✅ connecté » (une seule fois), pour vérifier les secrets
    sans attendre un 🟢. Mémorisé dans bot_settings (clé ignorée par les réglages)."""
    cfg = config()
    if not cfg:
        return False
    try:
        if sb.select("bot_settings", {"select": "key", "key": f"eq.{WELCOME_KEY}"}):
            return False
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram : vérification du message de bienvenue impossible (%s)", type(ex).__name__)
        return False
    token, chats = cfg
    text = ("✅ <b>Notifications activées</b>\nLe Loup de Kraken t'écrira ici à chaque nouveau 🟢 ou 🔥 "
            "(jamais pour un 🟡). Pas de message = pas de trade propre : c'est normal.")
    if send(text, token, chats, client) == 0:
        return False
    try:
        sb.upsert("bot_settings", [{"key": WELCOME_KEY, "value": True, "label": "Telegram connecté",
                                    "help": "Message de bienvenue Telegram déjà envoyé (technique)."}], "key")
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram : bienvenue envoyée mais non mémorisée (%s)", type(ex).__name__)
    log.info("Telegram : message de bienvenue envoyé")
    return True
