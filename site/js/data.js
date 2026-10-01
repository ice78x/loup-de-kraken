// Couche de données : Supabase en vrai, ou démo (données fictives) si le site n'est pas configuré.
// Toutes les pages passent par ces fonctions : pour ajouter une fonctionnalité, commence ici.
import { createClient } from "../vendor/supabase.mjs";
import { demoBackend } from "./demo.js";

const cfg = window.LDK_CONFIG || {};
export const DEMO = !cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY;

function supabaseBackend() {
  const sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, { auth: { persistSession: true } });
  const q = async (p) => {
    const { data, error } = await p;
    if (error) throw new Error(error.message);
    return data;
  };
  return {
    sb,
    // --- auth
    session: async () => (await sb.auth.getSession()).data.session,
    onAuth: (cb) => sb.auth.onAuthStateChange((e, s) => {
      if (e === "SIGNED_IN" || e === "SIGNED_OUT" || e === "USER_UPDATED") setTimeout(() => cb(s), 0);
    }),
    signIn: (email, password) => q(sb.auth.signInWithPassword({ email, password })),
    signUp: (email, password, pseudo) => q(sb.auth.signUp({ email, password, options: { data: { pseudo } } })),
    signOut: () => sb.auth.signOut(),
    token: async () => (await sb.auth.getSession()).data.session?.access_token,
    // --- profils
    me: async () => {
      const uid = (await sb.auth.getUser()).data.user?.id;
      return uid ? q(sb.from("profiles").select("*").eq("id", uid).single()) : null;
    },
    updateMe: async (id, patch) => q(sb.from("profiles").update(patch).eq("id", id).select().single()),
    members: () => q(sb.from("profiles").select("id,pseudo,pseudo_pending,approved,is_admin,created_at,balance_eur").order("created_at")),
    setMember: (id, patch) => q(sb.from("profiles").update(patch).eq("id", id)),
    removeMember: (id) => q(sb.from("profiles").delete().eq("id", id)),
    balanceHistory: (id) => q(sb.from("balance_history").select("*").eq("user_id", id).order("created_at", { ascending: false }).limit(20)),
    // --- bot
    latestScan: async () => (await q(sb.from("scans").select("*").order("created_at", { ascending: false }).limit(1)))[0] || null,
    signalsOf: (scanId) => q(sb.from("signals").select("*").eq("scan_id", scanId).order("status").order("score", { ascending: false })),
    signal: (id) => q(sb.from("signals").select("*").eq("id", id).single()),
    recentSignals: (limit = 30) => q(sb.from("signals").select("id,created_at,display,direction,status,score,strategy").eq("status", "TRADE").order("created_at", { ascending: false }).limit(limit)),
    // Supabase renvoie au plus 1 000 lignes par requête : on lit la liste par pages pour avoir TOUTES les paires.
    instruments: async () => {
      const out = [];
      for (let from = 0; from < 10_000; from += 1000) {
        const page = await q(sb.from("instruments").select("*").order("key").range(from, from + 999));
        out.push(...page);
        if (page.length < 1000) break;
      }
      return out.sort((a, b) => String(a.display).localeCompare(String(b.display)));
    },
    instrumentsByKeys: (keys) => (keys.length ? q(sb.from("instruments").select("*").in("key", keys)) : Promise.resolve([])),
    instrument: async (key) => (await q(sb.from("instruments").select("*").eq("key", key).limit(1)))[0] || null,
    // Signaux du bot sur une paire (sans les bougies, plus léger), du plus récent au plus ancien.
    signalsFor: (key, limit = 20) => q(sb.from("signals").select("id,created_at,status,direction,display,strategy,score,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,quote,venue,asset_class,trigger_text,rr,instrument_key,api_symbol,api_asset_class")
      .eq("instrument_key", key).order("created_at", { ascending: false }).limit(limit)),
    edges: () => q(sb.from("bot_edges").select("*").order("asset_class")),
    settings: () => q(sb.from("bot_settings").select("*").order("key")),
    setSetting: (key, value) => q(sb.from("bot_settings").update({ value }).eq("key", key)),
    settingsLog: () => q(sb.from("bot_settings_log").select("*,profiles:changed_by(pseudo)").order("created_at", { ascending: false }).limit(20)),
    requestScan: async (mode = "normal") => {
      const r = await fetch("/api/scan", { method: "POST", headers: { authorization: `Bearer ${await backend.token()}`, "content-type": "application/json" }, body: JSON.stringify({ mode }) });
      const b = await r.json().catch(() => ({ error: `Erreur ${r.status}` }));
      if (!r.ok) throw new Error(b.error || `Erreur ${r.status}`);
      return b.message;
    },
    // --- trades
    trades: ({ userId, status, instrumentKey, limit = 200 } = {}) => {
      let r = sb.from("trades").select("*,profiles:user_id(pseudo)").order("opened_at", { ascending: false }).limit(limit);
      if (userId) r = r.eq("user_id", userId);
      if (instrumentKey) r = r.eq("instrument_key", instrumentKey);
      if (status) r = r.eq("status", status);
      return q(r);
    },
    trade: (id) => q(sb.from("trades").select("*,profiles:user_id(pseudo)").eq("id", id).single()),
    createTrade: (row) => q(sb.from("trades").insert(row).select().single()),
    updateTrade: (id, patch) => q(sb.from("trades").update(patch).eq("id", id).select().single()),
    deleteTrade: (id) => q(sb.from("trades").delete().eq("id", id)),
    leaderboard: () => q(sb.from("leaderboard").select("*").order("pnl_eur", { ascending: false })),
    // --- idées
    // Boîte à idées privée : un membre ne reçoit que les siennes, l'admin les reçoit toutes (règles de sécurité de la base).
    ideas: () => q(sb.from("ideas").select("*,profiles:user_id(pseudo)").order("created_at", { ascending: false })),
    addIdea: (title, body, category) => q(sb.from("ideas").insert({ title, body: body || null, category })),
    setIdea: (id, patch) => q(sb.from("ideas").update(patch).eq("id", id)),
    deleteIdea: (id) => q(sb.from("ideas").delete().eq("id", id)),
    unseenIdeas: async () => (await sb.from("ideas").select("id", { count: "exact", head: true }).eq("seen", false)).count || 0,
  };
}

export const backend = DEMO ? demoBackend() : supabaseBackend();
