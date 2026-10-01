// Mon compte : pseudo, solde (modifiable à tout moment), risque, historique du solde, et gestion des membres (admin).
import { backend, DEMO } from "../data.js";
import { busy, dt, esc, eur, num, toast } from "../ui.js";

export async function render(main, ctx) {
  const me = ctx.me;
  const [hist, members] = await Promise.all([backend.balanceHistory(me.id), me.is_admin ? backend.members() : Promise.resolve([])]);
  const pending = members.filter((m) => !m.approved);
  main.innerHTML = `
    <h1>Mon compte</h1>
    <form class="bloc form" id="me">
      <div class="deux">
        <label class="champ"><span>Pseudo</span><input name="pseudo" required maxlength="30" value="${esc(me.pseudo)}"></label>
        <label class="champ"><span>Mon solde (€)</span><input name="balance" inputmode="decimal" value="${me.balance_eur}">
          <small>Mets ton solde réel Kraken (ou ton capital d'entraînement). Change-le quand tu veux.</small></label>
      </div>
      <div class="trois">
        <label class="champ"><span>Risque par trade (%)</span><input name="risk" inputmode="decimal" value="${me.risk_pct}"><small>Conseillé : 1 %. Maximum 2 %.</small></label>
        <label class="champ"><span>Risque ouvert max (%)</span><input name="open" inputmode="decimal" value="${me.max_open_risk_pct}"><small>Tous trades cumulés.</small></label>
        <label class="champ"><span>Perte max du jour (%)</span><input name="day" inputmode="decimal" value="${me.max_daily_loss_pct}"><small>Ensuite : stop jusqu'au lendemain.</small></label>
      </div>
      <p class="small muted" style="margin:0">Exemple : avec ${eur(+me.balance_eur)} et ${me.risk_pct} %, tu risques ${eur((me.balance_eur * me.risk_pct) / 100)} par trade.
        Ne monte jamais ton risque parce que tu peux redéposer de l'argent.</p>
      <button class="btn principal" type="submit">Enregistrer</button>
    </form>

    <section class="section"><h2>Historique de mon solde</h2>
      <div class="bloc"><ul>${hist.map((h) => `<li>${dt(h.created_at)} : ${eur(+h.old_balance)} → <b>${eur(+h.new_balance)}</b></li>`).join("") || "<li>Aucune modification.</li>"}</ul></div></section>

    ${me.is_admin ? `<section class="section"><h2>Membres ${pending.length ? `<span class="pastille ambre">${pending.length} en attente</span>` : ""}</h2>
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
    const patch = { pseudo: f.pseudo.value.trim(), balance_eur: num(f.balance.value), risk_pct: num(f.risk.value),
      max_open_risk_pct: num(f.open.value), max_daily_loss_pct: num(f.day.value) };
    if (!(patch.balance_eur >= 0)) return toast("Solde invalide.", true);
    if (!(patch.risk_pct > 0 && patch.risk_pct <= 2)) return toast("Le risque par trade doit être entre 0,1 et 2 %.", true);
    if (!(patch.max_open_risk_pct > 0 && patch.max_open_risk_pct <= 5)) return toast("Risque ouvert max : entre 0,1 et 5 %.", true);
    if (!(patch.max_daily_loss_pct > 0 && patch.max_daily_loss_pct <= 10)) return toast("Perte max du jour : entre 0,1 et 10 %.", true);
    busy(e.submitter, async () => { ctx.me = await backend.updateMe(me.id, patch); toast("Compte mis à jour."); render(main, ctx); });
  });
  main.querySelector("#logout").addEventListener("click", () => backend.signOut());
  main.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.setMember(b.dataset.approve, { approved: true }); toast("Membre approuvé."); render(main, ctx); })));
  main.querySelectorAll("[data-admin]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    await backend.setMember(b.dataset.admin, { is_admin: b.dataset.v === "true" }); render(main, ctx); })));
  main.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => {
    if (!confirm("Retirer ce membre et toutes ses données du club ?")) return;
    busy(b, async () => { await backend.removeMember(b.dataset.remove); toast("Membre retiré."); render(main, ctx); });
  }));
}
