// Mon compte : pseudo, solde (modifiable à tout moment), risque, historique du solde, et gestion des membres (admin).
import { backend, DEMO } from "../data.js";
import { ago, busy, dt, esc, eur, num, toast } from "../ui.js";
import { majSolde } from "../solde.js";
import { CATEGORIES, STATUTS } from "./ideas.js";

export async function render(main, ctx) {
  if (!ctx.me.solde) await majSolde(ctx, backend).catch(() => {});
  const me = ctx.me;
  const s = me.solde;
  const [hist, members, ideas] = await Promise.all([backend.balanceHistory(me.id), me.is_admin ? backend.members() : Promise.resolve([]),
    me.is_admin ? backend.ideas().catch(() => []) : Promise.resolve([])]);
  const unseen = ideas.filter((i) => !i.seen).length;
  const pending = members.filter((m) => !m.approved);
  const renames = members.filter((m) => m.approved && m.pseudo_pending && m.id !== me.id);
  main.innerHTML = `
    <h1>Mon compte</h1>
    <form class="bloc form" id="me">
      <div class="deux">
        <label class="champ"><span>Pseudo</span><input name="pseudo" required minlength="2" maxlength="30" value="${esc(me.pseudo)}">
          <small>${me.is_admin ? "Tu es admin : ton pseudo change tout de suite."
            : me.pseudo_pending ? `⏳ Demande envoyée : « ${esc(me.pseudo_pending)} », en attente de validation par l'admin. <button type="button" class="btn mini discret" id="annule-pseudo">Annuler</button>`
            : "Un changement de pseudo est envoyé à l'admin, qui le valide."}</small></label>
        <label class="champ"><span>Mon solde (€)</span><input name="balance" inputmode="decimal" value="${(+me.balance_eur).toFixed(2)}">
          <small>Il bouge tout seul avec tes trades${s ? ` (${eur(s.realise, true)} depuis le ${dt(s.since).split(" ")[0]}, sur un départ de ${eur(s.base)})` : ""}.
            Corrige-le ici après un dépôt, un retrait, ou pour l'aligner sur Kraken : on repart de cette valeur.</small></label>
      </div>
      <div class="trois">
        <label class="champ"><span>Risque par trade (%)</span><input name="risk" inputmode="decimal" value="${me.risk_pct}"><small>Conseillé : 1 %${me.guardrails === false ? "" : ". Maximum 2 %"}.</small></label>
        <label class="champ"><span>Risque ouvert max (%)</span><input name="open" inputmode="decimal" value="${me.max_open_risk_pct}"><small>Tous trades cumulés.</small></label>
        <label class="champ"><span>Perte max du jour (%)</span><input name="day" inputmode="decimal" value="${me.max_daily_loss_pct}"><small>Ensuite : stop jusqu'au lendemain.</small></label>
      </div>
      <label class="interrupteur">
        <input type="checkbox" name="guardrails" ${me.guardrails === false ? "" : "checked"}>
        <span><b>Garde-fous du club</b> — bloque les trades au-delà de 2 % de risque, au-delà de ton risque cumulé,
          après ta perte max du jour, ou si la liquidation arrive avant ton stop.
          <span class="muted">Coupés : rien n'est bloqué, le site t'avertit seulement.</span></span>
      </label>
      <p class="small muted" style="margin:0">Exemple : avec ${eur(+me.balance_eur)} et ${me.risk_pct} %, tu risques ${eur((me.balance_eur * me.risk_pct) / 100)} par trade.
        Ne monte jamais ton risque parce que tu peux redéposer de l'argent.</p>
      <button class="btn principal" type="submit">Enregistrer</button>
    </form>

    <section class="section"><h2>Historique de mon solde</h2>
      <div class="bloc"><ul>${hist.map((h) => `<li>${dt(h.created_at)} : ${eur(+h.old_balance)} → <b>${eur(+h.new_balance)}</b></li>`).join("") || "<li>Aucune modification.</li>"}</ul></div></section>

    ${me.is_admin ? `<section class="section" id="idees-recues"><h2>💡 Idées reçues ${unseen ? `<span class="pastille ambre">${unseen} nouvelle${unseen > 1 ? "s" : ""}</span>` : ""}</h2>
      <p class="muted">Les idées envoyées par les membres depuis l'onglet Idées. Toi seul les vois. Ta réponse s'affiche chez le membre.</p>
      ${ideas.length ? ideas.map((i) => `<form class="bloc pile idee ${i.seen ? "" : "nouvelle"}" data-idea="${i.id}">
        <div class="ligne entre"><b>${esc(i.title)}</b>${i.seen ? "" : '<span class="pastille ambre">nouvelle</span>'}</div>
        <span class="small muted">${esc(i.profiles?.pseudo || "membre")} · ${esc(CATEGORIES[i.category] || i.category || "")} · ${ago(i.created_at)}</span>
        ${i.body ? `<p class="small" style="margin:6px 0 0;white-space:pre-wrap">${esc(i.body)}</p>` : ""}
        <div class="deux">
          <label class="champ"><span>Statut</span><select name="status">${Object.entries(STATUTS).map(([k, [, l]]) => `<option value="${esc(k)}" ${k === i.status ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          <label class="champ"><span>Ta réponse (visible par le membre)</span><textarea name="reply" rows="2" maxlength="1000">${esc(i.admin_reply || "")}</textarea></label>
        </div>
        <div class="ligne"><button class="btn principal" type="submit">Enregistrer${i.seen ? "" : " et marquer comme lue"}</button>
          <button class="btn danger" type="button" data-del-idea="${i.id}">Supprimer</button></div>
      </form>`).join("") : '<p class="muted">Aucune idée reçue pour l\'instant.</p>'}
      <p class="small"><a href="#/bot">⚙️ Réglages et résultats du bot (réservé admin) →</a></p>
    </section>

    ${renames.length ? `<section class="section" id="pseudos"><h2>✏️ Changements de pseudo <span class="pastille ambre">${renames.length}</span></h2>
      <div class="pile">${renames.map((m) => `<div class="bloc ligne entre">
        <span><b>${esc(m.pseudo)}</b> veut s'appeler <b>${esc(m.pseudo_pending)}</b></span>
        <span class="ligne"><button class="btn principal mini" data-pseudo-ok="${m.id}">Accepter</button>
          <button class="btn danger mini" data-pseudo-non="${m.id}">Refuser</button></span></div>`).join("")}</div></section>` : ""}

    <section class="section"><h2>Membres ${pending.length ? `<span class="pastille ambre">${pending.length} en attente</span>` : ""}</h2>
      <p class="muted">Envoie l'adresse du site à tes amis. Après leur inscription, approuve-les ici.</p>
      <div class="table-wrap"><table><thead><tr><th>Membre</th><th>Inscrit</th><th>Statut</th><th></th></tr></thead><tbody>
      ${members.map((m) => `<tr><td>${esc(m.pseudo)}${m.id === me.id ? " (toi)" : ""}</td><td>${dt(m.created_at)}</td>
        <td>${m.approved ? (m.is_admin ? "admin" : "membre") : '<span class="pastille ambre">en attente</span>'}</td>
        <td class="ligne">${m.id === me.id ? "" : `
          ${m.approved ? "" : `<button class="btn principal" data-approve="${m.id}">Approuver</button>`}
          ${m.approved ? `<button class="btn" data-admin="${m.id}" data-v="${!m.is_admin}">${m.is_admin ? "Retirer admin" : "Rendre admin"}</button>` : ""}
          <button class="btn danger" data-remove="${m.id}">${m.approved ? "Retirer" : "Refuser"}</button>`}</td></tr>`).join("")}
      </tbody></table></div></section>` : ""}

    <section class="section ligne"><button class="btn" id="logout">Se déconnecter</button>
      ${DEMO ? '<span class="etiquette-demo">Mode démo</span>' : ""}</section>`;

  main.querySelector("#me").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const nom = f.pseudo.value.trim();
    if (nom.length < 2 || nom.length > 30) return toast("Le pseudo doit faire entre 2 et 30 caractères.", true);
    const renomme = nom !== me.pseudo;
    // Membre : le nouveau pseudo part en demande chez l'admin. Admin : changement direct.
    const patch = { ...(me.is_admin ? { pseudo: nom } : renomme ? { pseudo_pending: nom } : {}), balance_eur: num(f.balance.value), risk_pct: num(f.risk.value),
      max_open_risk_pct: num(f.open.value), max_daily_loss_pct: num(f.day.value), guardrails: f.guardrails.checked };
    const lim = patch.guardrails ? { risk: 2, open: 5, day: 10 } : { risk: 100, open: 100, day: 100 };
    if (!(patch.balance_eur >= 0)) return toast("Solde invalide.", true);
    if (!(patch.risk_pct > 0 && patch.risk_pct <= lim.risk)) return toast(`Le risque par trade doit être entre 0,1 et ${lim.risk} %.`, true);
    if (!(patch.max_open_risk_pct > 0 && patch.max_open_risk_pct <= lim.open)) return toast(`Risque ouvert max : entre 0,1 et ${lim.open} %.`, true);
    if (!(patch.max_daily_loss_pct > 0 && patch.max_daily_loss_pct <= lim.day)) return toast(`Perte max du jour : entre 0,1 et ${lim.day} %.`, true);
    busy(e.submitter, async () => {
      ctx.me = await backend.updateMe(me.id, patch);
      delete ctx.me.balance_base; delete ctx.me.solde; // le solde saisi devient le nouveau point de départ
      toast(renomme && !me.is_admin ? "Compte mis à jour. Ton nouveau pseudo est envoyé à l'admin pour validation." : "Compte mis à jour."); render(main, ctx);
    });
  });
  main.querySelectorAll("form[data-idea]").forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault();
    busy(e.submitter, async () => {
      await backend.setIdea(+f.dataset.idea, { status: f.status.value, admin_reply: f.reply.value.trim() || null, seen: true });
      toast("Idée mise à jour."); render(main, ctx);
    });
  }));
  main.querySelectorAll("[data-del-idea]").forEach((b) => b.addEventListener("click", () => {
    if (!confirm("Supprimer cette idée ?")) return;
    busy(b, async () => { await backend.deleteIdea(+b.dataset.delIdea); render(main, ctx); });
  }));
  main.querySelector("#logout").addEventListener("click", () => backend.signOut());
  main.querySelector("#annule-pseudo")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    ctx.me = await backend.updateMe(me.id, { pseudo_pending: null });
    toast("Demande de pseudo annulée."); render(main, ctx);
  }));
  main.querySelectorAll("[data-pseudo-ok]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const m = members.find((x) => x.id === b.dataset.pseudoOk);
    await backend.setMember(m.id, { pseudo: m.pseudo_pending, pseudo_pending: null });
    toast(`${m.pseudo} s'appelle maintenant ${m.pseudo_pending}.`); render(main, ctx);
  })));
  main.querySelectorAll("[data-pseudo-non]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.setMember(b.dataset.pseudoNon, { pseudo_pending: null }); toast("Changement de pseudo refusé."); render(main, ctx);
  })));
  main.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.setMember(b.dataset.approve, { approved: true }); toast("Membre approuvé."); render(main, ctx); })));
  main.querySelectorAll("[data-admin]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.setMember(b.dataset.admin, { is_admin: b.dataset.v === "true" }); render(main, ctx); })));
  main.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => {
    if (!confirm("Retirer ce membre et toutes ses données du club ?")) return;
    busy(b, async () => { await backend.removeMember(b.dataset.remove); toast("Membre retiré."); render(main, ctx); });
  }));
}
