// Boîte à idées : chaque membre propose une amélioration (bot, site, trading…). Elle arrive directement chez l'admin
// (Mon compte → Idées reçues). Un membre ne voit que ses propres idées et la réponse de l'admin.
import { backend } from "../data.js";
import { ago, busy, esc, toast } from "../ui.js";

export const CATEGORIES = { bot: "Le bot (signaux, stratégies)", site: "Le site (pages, affichage)", trading: "Le trading (règles, gestion)", autre: "Autre" };
export const STATUTS = { "proposée": ["", "envoyée"], "en cours": ["ambre", "en cours"], "faite": ["long", "faite ✓"], "refusée": ["short", "pas retenue"] };

export async function render(main, ctx) {
  const mine = (await backend.ideas().catch(() => [])).filter((i) => i.user_id === ctx.me.id);
  main.innerHTML = `
    <h1>Idées d'amélioration</h1>
    <p class="muted">Une idée pour améliorer le bot ou le site ? Écris-la ici : elle part directement chez l'administrateur.
      Personne d'autre ne la voit. Tu suivras sa réponse juste en dessous.</p>

    <form class="bloc form" id="idea">
      <label class="champ"><span>Ça concerne</span>
        <select name="category">${Object.entries(CATEGORIES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <label class="champ"><span>Ton idée en une phrase</span>
        <input name="title" required minlength="3" maxlength="140" placeholder="Ex. une alerte sur mon téléphone quand un trade devient imminent"></label>
      <label class="champ"><span>Détails (facultatif)</span>
        <textarea name="body" rows="4" maxlength="2000" placeholder="Pourquoi ce serait utile, un exemple, ce qui te gêne aujourd'hui…"></textarea></label>
      <button class="btn principal" type="submit">Envoyer à l'admin</button>
    </form>

    <section class="section"><h2>Mes idées envoyées ${mine.length ? `<span class="muted small">(${mine.length})</span>` : ""}</h2>
      ${mine.length ? mine.map((i) => {
        const [k, lbl] = STATUTS[i.status] || ["", i.status];
        return `<div class="bloc pile idee">
          <div class="ligne entre"><b>${esc(i.title)}</b><span class="pastille ${k}">${esc(lbl)}</span></div>
          <span class="small muted">${esc(CATEGORIES[i.category] || i.category || "")} · envoyée ${ago(i.created_at)}${i.seen ? " · lue par l'admin" : ""}</span>
          ${i.body ? `<p class="small" style="margin:6px 0 0;white-space:pre-wrap">${esc(i.body)}</p>` : ""}
          ${i.admin_reply ? `<div class="reponse"><b>Réponse de l'admin :</b> <span style="white-space:pre-wrap">${esc(i.admin_reply)}</span></div>` : ""}
          ${i.status === "proposée" && !i.seen ? `<button class="btn discret mini" data-del="${i.id}">Retirer</button>` : ""}
        </div>`;
      }).join("") : '<p class="muted">Tu n\'as encore envoyé aucune idée.</p>'}
    </section>`;

  main.querySelector("#idea").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const title = f.title.value.trim();
    if (title.length < 3) return toast("Écris ton idée en quelques mots.", true);
    busy(e.submitter, async () => {
      await backend.addIdea(title, f.body.value.trim(), f.category.value);
      toast("Idée envoyée à l'admin. Merci !");
      render(main, ctx);
    });
  });
  main.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.deleteIdea(+b.dataset.del);
    render(main, ctx);
  })));
}
