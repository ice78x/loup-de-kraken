// Bouton "Scanner maintenant" : vérifie que la personne est un membre approuvé,
// limite à 1 demande toutes les 10 minutes, puis déclenche le workflow GitHub "scan".
// Bouton "Vérifier ce setup" (mode "cible" + symbol) : le bot ne réanalyse qu'une paire (≈ 2 min) ; 1 demande / 2 min.
// Bouton "Lancer le backtest" (mode "backtest", ADMIN seulement) : workflow GitHub "backtest" (30 à 90 min) ; 1 demande / heure.
// Variables Netlify requises : SUPABASE_URL, SUPABASE_ANON_KEY, GH_TOKEN, GH_REPO (ex. "moi/loup-de-kraken").

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

export default async (req) => {
  if (req.method !== "POST") return json({ error: "Méthode non autorisée" }, 405);
  const { SUPABASE_URL, SUPABASE_ANON_KEY, GH_TOKEN, GH_REPO } = process.env;
  const branch = process.env.GH_BRANCH || "main";
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !GH_TOKEN || !GH_REPO) {
    return json({ error: "Le bouton de scan n'est pas encore configuré (variables Netlify manquantes). Le bot scanne quand même toutes les heures." }, 503);
  }
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!token) return json({ error: "Connecte-toi d'abord." }, 401);
  const sb = { apikey: SUPABASE_ANON_KEY, authorization: `Bearer ${token}` };

  const u = await fetch(`${SUPABASE_URL}/auth/v1/user`, { headers: sb });
  if (!u.ok) return json({ error: "Session expirée, reconnecte-toi." }, 401);
  const user = await u.json();

  const p = await fetch(`${SUPABASE_URL}/rest/v1/profiles?id=eq.${user.id}&select=approved,is_admin`, { headers: sb });
  const prof = (await p.json())[0];
  if (!prof?.approved) return json({ error: "Ton compte attend l'approbation d'un admin." }, 403);

  const body = await req.json().catch(() => ({}));
  const mode = ["urgent", "cible", "backtest"].includes(body.mode) ? body.mode : "normal";
  const symbol = String(body.symbol || "");
  if (mode === "cible" && !/^[a-z]+:[A-Za-z0-9._]{2,30}$/.test(symbol)) return json({ error: "Paire invalide." }, 400);
  if (mode === "backtest" && !prof.is_admin) return json({ error: "Réservé aux admins." }, 403);
  const attente = mode === "cible" ? 2 : mode === "backtest" ? 60 : 10;
  const jours = Math.min(365, Math.max(30, Math.round(+body.days || 120)));
  const nb = Math.min(40, Math.max(3, Math.round(+body.instruments || 16)));

  // Dernières demandes (la colonne mode peut ne pas exister si schema.sql n'a pas été relancé : on s'adapte)
  let rows = await fetch(`${SUPABASE_URL}/rest/v1/scan_requests?select=created_at,mode&order=created_at.desc&limit=20`, { headers: sb });
  const avecMode = rows.ok;
  if (!avecMode) rows = await fetch(`${SUPABASE_URL}/rest/v1/scan_requests?select=created_at&order=created_at.desc&limit=1`, { headers: sb });
  const famille = (m) => (m === "cible" || m === "backtest" ? m : "scan");
  const lastRow = ((await rows.json().catch(() => [])) || []).find((r) => !avecMode || famille(r.mode) === famille(mode));
  if (lastRow) {
    const ago = (Date.now() - new Date(lastRow.created_at).getTime()) / 60000;
    const quoi = { cible: "Une vérification a été demandée", backtest: "Un backtest a été demandé", scan: "Un scan a été demandé" }[famille(mode)];
    if (ago < attente) return json({ error: `${quoi} il y a ${Math.floor(ago)} min. Réessaie dans ${Math.ceil(attente - ago)} min.` }, 429);
  }

  const workflow = mode === "backtest" ? "backtest.yml" : "scan.yml";
  const inputs = mode === "backtest" ? { days: String(jours), instruments: String(nb) }
    : mode === "cible" ? { mode: "normal", symbol } : { mode };
  const gh = await fetch(`https://api.github.com/repos/${GH_REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${GH_TOKEN}`, accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28", "user-agent": "loup-de-kraken",
    },
    body: JSON.stringify({ ref: branch, inputs }),
  });
  if (gh.status !== 204) {
    const txt = await gh.text();
    return json({ error: `GitHub a refusé le lancement (${gh.status}). Vérifie GH_TOKEN et GH_REPO. ${txt.slice(0, 160)}` }, 502);
  }
  await fetch(`${SUPABASE_URL}/rest/v1/scan_requests`, {
    method: "POST", headers: { ...sb, "content-type": "application/json", prefer: "return=minimal" },
    body: JSON.stringify(avecMode ? { user_id: user.id, mode } : { user_id: user.id }),
  });
  const message = { cible: "Vérification lancée : réponse du bot dans 1 à 3 minutes.",
    backtest: `Backtest lancé (${jours} jours, ${nb} perpétuels) : résultats sur le site dans 30 à 90 minutes.` }[mode]
    || "Scan lancé. Résultat sur le site dans 2 à 4 minutes.";
  return json({ ok: true, message });
};

export const config = { path: "/api/scan" };
