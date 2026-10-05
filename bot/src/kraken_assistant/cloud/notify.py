"""Notifications Telegram : un message dès qu'un scan publie un 🟢 (ou 🔥 A+), même si personne n'est sur le site.

Configuration (secrets GitHub, jamais dans le code) :
  TELEGRAM_BOT_TOKEN  jeton donné par @BotFather (obligatoire)
  TELEGRAM_CHAT_ID    facultatif : conversations toujours servies (séparées par des virgules)
Abonnement automatique : toute personne (ou groupe) qui écrit au bot (« Démarrer ») est inscrite au scan suivant
(table telegram_subscribers) et reçoit les signaux ; « /stop » désabonne ; un bot bloqué ou retiré désabonne aussi.
Le jeton n'apparaît jamais dans les journaux.
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


def send(text: str, token: str, chat_ids: list[str], client: httpx.Client | None = None,
         gone: set[str] | None = None) -> int:
    """Envoie à chaque conversation. `gone` reçoit les conversations définitivement perdues (bot bloqué, retiré, inexistante)."""
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
                    log.warning("Telegram a refusé le message (code %s)", r.status_code)
                    if r.status_code in (400, 403) and gone is not None:
                        gone.add(str(chat))
            except httpx.HTTPError as ex:
                log.warning("Telegram injoignable : %s", type(ex).__name__)
    finally:
        if client is None:
            c.close()
    return ok


def token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def fixed_chats() -> list[str]:
    return [x.strip() for x in (os.environ.get("TELEGRAM_CHAT_ID") or "").split(",") if x.strip()]


def config() -> tuple[str, list[str]] | None:
    """(jeton, conversations fixes) — la liste peut être vide : les abonnés automatiques suffisent."""
    t = token()
    return (t, fixed_chats()) if t else None


# --------------------------------------------------------------------------------------- abonnements automatiques
SUBS = "telegram_subscribers"
OFFSET_KEY = "telegram_offset"
HELLO = ("✅ <b>Bienvenue sur Le Loup de Kraken</b>\nTu recevras ici chaque 🟢 trade validé et chaque ⏳ pré-alerte du bot.\n"
         "Pas de message = pas de trade propre : c'est normal.\nPour arrêter : envoie /stop.\n"
         "<i>Probabilité, pas garantie. Entraîne-toi en paper avant d'engager de l'argent.</i>")
BYE = "👋 C'est noté, tu ne recevras plus les signaux. Pour revenir : envoie /start."


def _name(chat: dict) -> str:
    return (chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or "")[:80]


def poll_subscribers(sb, client: httpx.Client | None = None) -> dict:
    """Lit les nouveaux messages reçus par le bot (getUpdates) : inscrit / désinscrit, et souhaite la bienvenue.
    Jamais bloquant. Retourne {"nouveaux": n, "partis": n}."""
    out = {"nouveaux": 0, "partis": 0}
    t = token()
    if not t:
        return out
    c = client or httpx.Client(timeout=20)
    try:
        try:
            rows = sb.select("bot_settings", {"select": "value", "key": f"eq.{OFFSET_KEY}"}) or []
            offset = int(rows[0]["value"]) if rows else 0
        except Exception as ex:  # noqa: BLE001
            log.warning("Telegram : position de lecture illisible (%s)", type(ex).__name__)
            return out
        try:
            r = c.get(f"https://api.telegram.org/bot{t}/getUpdates",
                      params={"offset": offset, "timeout": 0, "allowed_updates": '["message","my_chat_member"]'})
            updates = r.json().get("result", []) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError) as ex:
            log.warning("Telegram : lecture des messages impossible (%s)", type(ex).__name__)
            return out
        if not updates:
            return out
        try:
            known = {str(x["chat_id"]): bool(x.get("active")) for x in sb.select(SUBS, {"select": "chat_id,active"}) or []}
        except Exception as ex:  # noqa: BLE001
            log.warning("Telegram : table des abonnés absente (relance supabase/schema.sql) : %s", type(ex).__name__)
            return out
        now = datetime.now(timezone.utc).isoformat()
        changes: dict[str, dict] = {}
        for u in updates:
            m = u.get("message")
            mc = u.get("my_chat_member")
            if m and m.get("chat"):
                chat = m["chat"]
                cid = str(chat.get("id"))
                text = (m.get("text") or "").strip().lower()
                active = not text.startswith("/stop")
                changes[cid] = {"chat_id": cid, "name": _name(chat), "kind": chat.get("type", ""), "active": active, "updated_at": now}
            elif mc and mc.get("chat"):
                chat = mc["chat"]
                cid = str(chat.get("id"))
                status = (mc.get("new_chat_member") or {}).get("status")
                active = status in ("member", "administrator")
                changes[cid] = {"chat_id": cid, "name": _name(chat), "kind": chat.get("type", ""), "active": active, "updated_at": now}
        for cid, row in changes.items():
            before = known.get(cid)
            if row["active"] and before is not True:
                if send(HELLO, t, [cid], c):
                    out["nouveaux"] += 1
            elif not row["active"] and before is True:
                send(BYE, t, [cid], c)
                out["partis"] += 1
        try:
            if changes:
                sb.upsert(SUBS, list(changes.values()), "chat_id")
            sb.upsert("bot_settings", [{"key": OFFSET_KEY, "value": max(u["update_id"] for u in updates) + 1,
                                        "label": "Telegram (technique)", "help": "Position de lecture des messages du bot."}], "key")
        except Exception as ex:  # noqa: BLE001
            log.warning("Telegram : abonnés non enregistrés (%s)", type(ex).__name__)
        if out["nouveaux"] or out["partis"]:
            log.info("Telegram : %d nouvel(s) abonné(s), %d désabonnement(s)", out["nouveaux"], out["partis"])
        return out
    finally:
        if client is None:
            c.close()


def recipients(sb) -> list[str]:
    """Conversations fixes (secret) + abonnés actifs, sans doublon."""
    chats = list(dict.fromkeys(fixed_chats()))
    try:
        for x in sb.select(SUBS, {"select": "chat_id", "active": "eq.true"}) or []:
            if str(x["chat_id"]) not in chats:
                chats.append(str(x["chat_id"]))
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram : abonnés illisibles (%s) — envoi aux conversations fixes seulement", type(ex).__name__)
    return chats


def _forget(sb, gone: set[str]) -> None:
    fixed = set(fixed_chats())
    for cid in gone - fixed:
        try:
            sb.update(SUBS, {"chat_id": f"eq.{cid}"}, {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
        except Exception:  # noqa: BLE001
            pass


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
    tok = token()
    trades = [r for r in inserted or [] if r.get("status") == "TRADE"]
    preps = [r for r in inserted or [] if _presque(r)]
    if not tok or not (trades or preps):
        return 0
    chats = recipients(sb)
    if not chats:
        return 0
    gone: set[str] = set()
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
        sent += send(signal_message(r), tok, [c for c in chats if c not in gone], client, gone)
    for r in preps:
        k = (r.get("instrument_key"), r.get("direction"))
        if k in deja_vert or k in deja_prep:
            continue
        deja_prep.add(k)
        sent += send(heads_up_message(r), tok, [c for c in chats if c not in gone], client, gone)
    if gone:
        _forget(sb, gone)
    if sent:
        log.info("Telegram : %d message(s) envoyé(s)", sent)
    return sent


WELCOME_KEY = "telegram_bienvenue"


def welcome_once(sb, client: httpx.Client | None = None) -> bool:
    """Premier scan après la configuration : un message « ✅ connecté » (une seule fois), pour vérifier les secrets
    sans attendre un 🟢. Mémorisé dans bot_settings (clé ignorée par les réglages)."""
    cfg = config()
    if not cfg or not cfg[1]:
        return False
    try:
        if sb.select("bot_settings", {"select": "key", "key": f"eq.{WELCOME_KEY}"}):
            return False
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram : vérification du message de bienvenue impossible (%s)", type(ex).__name__)
        return False
    tok, chats = cfg
    text = ("✅ <b>Notifications activées</b>\nLe Loup de Kraken t'écrira ici à chaque nouveau 🟢 ou 🔥 "
            "(jamais pour un 🟡). Pas de message = pas de trade propre : c'est normal.")
    if send(text, tok, chats, client) == 0:
        return False
    try:
        sb.upsert("bot_settings", [{"key": WELCOME_KEY, "value": True, "label": "Telegram connecté",
                                    "help": "Message de bienvenue Telegram déjà envoyé (technique)."}], "key")
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram : bienvenue envoyée mais non mémorisée (%s)", type(ex).__name__)
    log.info("Telegram : message de bienvenue envoyé")
    return True
