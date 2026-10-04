// Bouton "Scanner maintenant" : vérifie que la personne est un membre approuvé,
// limite à 1 demande toutes les 10 minutes, puis déclenche le workflow GitHub "scan".
// Bouton "Vérifier ce setup" (mode "cible" + symbol) : le bot ne réanalyse qu'une paire (≈ 2 min) ; 1 demande / 2 min.
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

  const p = await fetch(`${SUPABASE_URL}/rest/v1/profiles?id=eq.${user.id}&select=approved`, { headers: sb });
  const prof = (await p.json())[0];
  if (!prof?.approved) return json({ error: "Ton compte attend l'approbation d'un admin." }, 403);

  const body = await req.json().catch(() => ({}));
  const mode = ["urgent", "cible"].includes(body.mode) ? body.mode : "normal";
  const symbol = String(body.symbol || "");
  if (mode === "cible" && !/^[a-z]+:[A-Za-z0-9._]{2,30}$/.test(symbol)) return json({ error: "Paire invalide." }, 400);
  const attente = mode === "cible" ? 2 : 10;

  // Dernières demandes (la colonne mode peut ne pas exister si schema.sql n'a pas été relancé : on s'adapte)
  let rows = await fetch(`${SUPABASE_URL}/rest/v1/scan_requests?select=created_at,mode&order=created_at.desc&limit=20`, { headers: sb });
  const avecMode = rows.ok;
  if (!avecMode) rows = await fetch(`${SUPABASE_URL}/rest/v1/scan_requests?select=created_at&order=created_at.desc&limit=1`, { headers: sb });
  const lastRow = ((await rows.json().catch(() => [])) || []).find((r) => !avecMode || (r.mode === "cible") === (mode === "cible"));
  if (lastRow) {
    const ago = (Date.now() - new Date(lastRow.created_at).getTime()) / 60000;
    if (ago < attente) return json({ error: `${mode === "cible" ? "Une vérification" : "Un scan"} a été demandé${mode === "cible" ? "e" : ""} il y a ${Math.floor(ago)} min. Réessaie dans ${Math.ceil(attente - ago)} min.` }, 429);
  }

  const gh = await fetch(`https://api.github.com/repos/${GH_REPO}/actions/workflows/scan.yml/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${GH_TOKEN}`, accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28", "user-agent": "loup-de-kraken",
    },
    body: JSON.stringify({ ref: branch, inputs: mode === "cible" ? { mode: "normal", symbol } : { mode } }),
  });
  if (gh.status !== 204) {
    const txt = await gh.text();
    return json({ error: `GitHub a refusé le lancement (${gh.status}). Vérifie GH_TOKEN et GH_REPO. ${txt.slice(0, 160)}` }, 502);
  }
  await fetch(`${SUPABASE_URL}/rest/v1/scan_requests`, {
    method: "POST", headers: { ...sb, "content-type": "application/json", prefer: "return=minimal" },
    body: JSON.stringify(avecMode ? { user_id: user.id, mode } : { user_id: user.id }),
  });
  return json({ ok: true, message: mode === "cible" ? "Vérification lancée : réponse du bot dans 1 à 3 minutes." : "Scan lancé. Résultat sur le site dans 2 à 4 minutes." });
};

export const config = { path: "/api/scan" };
