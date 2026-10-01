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
    members: () => q(sb.from("profiles").select("id,pseudo,approved,is_admin,created_at,balance_eur").order("created_at")),
    setMember: (id, patch) => q(sb.from("profiles").update(patch).eq("id", id)),
    removeMember: (id) => q(sb.from("profiles").delete().eq("id", id)),
    balanceHistory: (id) => q(sb.from("balance_history").select("*").eq("user_id", id).order("created_at", { ascending: false }).limit(20)),
    // --- bot
    latestScan: async () => (await q(sb.from("scans").select("*").order("created_at", { ascending: false }).limit(1)))[0] || null,
    signalsOf: (scanId) => q(sb.from("signals").select("*").eq("scan_id", scanId).order("status").order("score", { ascending: false })),
    signal: (id) => q(sb.from("signals").select("*").eq("id", id).single()),
    recentSignals: (limit = 30) => q(sb.from("signals").select("id,created_at,display,direction,status,score,strategy").eq("status", "TRADE").order("created_at", { ascending: false }).limit(limit)),
    instruments: () => q(sb.from("instruments").select("*").order("display").limit(2000)),
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
    trades: ({ userId, status, limit = 200 } = {}) => {
      let r = sb.from("trades").select("*,profiles:user_id(pseudo)").order("opened_at", { ascending: false }).limit(limit);
      if (userId) r = r.eq("user_id", userId);
      if (status) r = r.eq("status", status);
      return q(r);
    },
    trade: (id) => q(sb.from("trades").select("*,profiles:user_id(pseudo)").eq("id", id).single()),
    createTrade: (row) => q(sb.from("trades").insert(row).select().single()),
    updateTrade: (id, patch) => q(sb.from("trades").update(patch).eq("id", id).select().single()),
    deleteTrade: (id) => q(sb.from("trades").delete().eq("id", id)),
    leaderboard: () => q(sb.from("leaderboard").select("*").order("pnl_eur", { ascending: false })),
    // --- idées
    ideas: () => q(sb.from("ideas").select("*,profiles:user_id(pseudo),idea_votes(user_id)").order("created_at", { ascending: false })),
    addIdea: (title, body) => q(sb.from("ideas").insert({ title, body })),
    setIdea: (id, patch) => q(sb.from("ideas").update(patch).eq("id", id)),
    vote: (idea_id) => q(sb.from("idea_votes").insert({ idea_id })),
    unvote: async (idea_id) => q(sb.from("idea_votes").delete().eq("idea_id", idea_id).eq("user_id", (await sb.auth.getUser()).data.user.id)),
  };
}

export const backend = DEMO ? demoBackend() : supabaseBackend();
