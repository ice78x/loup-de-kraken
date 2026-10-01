// Connexion / inscription, et page d'attente tant qu'un admin n'a pas approuvé le compte.
import { backend } from "../data.js";
import { busy, esc, toast } from "../ui.js";

export async function render(main) {
  main.innerHTML = `
  <div class="auth"><div class="carte">
    <img class="logo-grand" src="img/logo.svg" alt="">
    <h1>Le Loup de Kraken</h1>
    <p class="sous">Le club privé où l'on trade avec méthode, et où l'on progresse ensemble.</p>
    <div class="onglets" role="tablist">
      <button role="tab" aria-selected="true" data-tab="in">Se connecter</button>
      <button role="tab" aria-selected="false" data-tab="up">Créer un compte</button>
    </div>
    <form class="bloc form" id="f">
      <label class="champ" id="pseudo-f" hidden><span>Pseudo</span><input name="pseudo" maxlength="30" autocomplete="nickname"></label>
      <label class="champ"><span>E-mail</span><input name="email" type="email" required autocomplete="email"></label>
      <label class="champ"><span>Mot de passe</span><input name="password" type="password" required minlength="8" autocomplete="current-password">
        <small id="pw-help" hidden>8 caractères minimum.</small></label>
      <button class="btn principal plein" type="submit">Se connecter</button>
    </form>
    <p class="small muted" style="text-align:center;margin-top:16px">Club privé : chaque nouveau compte doit être approuvé par un admin.</p>
  </div></div>`;
  let mode = "in";
  const f = main.querySelector("#f");
  main.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.tab;
    main.querySelectorAll("[data-tab]").forEach((x) => x.setAttribute("aria-selected", x === b));
    f.querySelector("#pseudo-f").hidden = mode === "in";
    f.querySelector("#pw-help").hidden = mode === "in";
    f.password.autocomplete = mode === "in" ? "current-password" : "new-password";
    f.querySelector("[type=submit]").textContent = mode === "in" ? "Se connecter" : "Créer mon compte";
  }));
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    busy(e.submitter, async () => {
      if (mode === "in") return backend.signIn(f.email.value.trim(), f.password.value);
      if (!f.pseudo.value.trim()) throw new Error("Choisis un pseudo.");
      await backend.signUp(f.email.value.trim(), f.password.value, f.pseudo.value.trim());
      toast("Compte créé.");
    });
  });
}

export async function renderPending(main, ctx) {
  main.innerHTML = `<div class="auth"><div class="carte bloc" style="text-align:center">
    <img class="logo-grand" src="img/logo.svg" alt="">
    <h1>Presque dans la meute</h1>
    <p>Ton compte <b>${esc(ctx.me?.pseudo || "")}</b> est créé. Un admin doit maintenant l'approuver.</p>
    <p class="muted">Préviens la personne qui t'a invité, puis recharge cette page.</p>
    <div class="ligne" style="justify-content:center"><button class="btn principal" onclick="location.reload()">Recharger</button>
      <button class="btn discret" id="out">Se déconnecter</button></div></div></div>`;
  main.querySelector("#out").addEventListener("click", () => backend.signOut().catch((e) => toast(e.message, true)));
}
