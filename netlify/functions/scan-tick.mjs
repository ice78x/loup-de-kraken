// Horloge principale des scans : toutes les 15 min, 1 min après la clôture de chaque bougie 15 min
// (hh:01, hh:16, hh:31, hh:46 UTC = mêmes minutes à Paris). Déclenche le workflow GitHub "scan".
// Pourquoi ici et pas dans GitHub ? Le cron de GitHub part souvent 15 à 20 min en retard ; un lancement
// « à la demande » (workflow_dispatch) démarre en quelques secondes. Le cron GitHub reste en SECOURS
// (il ne fait rien si un scan a eu lieu il y a moins de 20 min : voir backup_should_skip dans cloud/run.py).
// Variables Netlify requises (les mêmes que le bouton Scanner) : GH_TOKEN, GH_REPO. Aucun secret journalisé.

export default async () => {
  const { GH_TOKEN, GH_REPO } = process.env;
  const branch = process.env.GH_BRANCH || "main";
  if (!GH_TOKEN || !GH_REPO) {
    console.log("scan-tick : GH_TOKEN ou GH_REPO absent, le cron GitHub de secours prend le relais");
    return new Response("non configuré", { status: 503 });
  }
  const gh = await fetch(`https://api.github.com/repos/${GH_REPO}/actions/workflows/scan.yml/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${GH_TOKEN}`, accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28", "user-agent": "loup-de-kraken",
    },
    body: JSON.stringify({ ref: branch, inputs: { mode: "normal" } }),
  }).catch((e) => ({ status: 0, text: async () => e.message }));
  if (gh.status !== 204) {
    console.log(`scan-tick : GitHub a refusé (${gh.status}) ${(await gh.text()).slice(0, 160)}`);
    return new Response("refusé", { status: 502 });
  }
  console.log("scan-tick : scan lancé");
  return new Response("ok");
};

export const config = { schedule: "1,16,31,46 * * * *" };
