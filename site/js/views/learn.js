// Apprendre : les règles, le lexique, et des graphiques d'exemple pour chaque condition utilisée par le bot.
import { candleChart } from "../charts.js";
import { EXAMPLES } from "../examples.js";
import { ladder } from "../ladder.js";
import { planTrade } from "../sizing.js";
import { esc, eur, num, pct } from "../ui.js";

const LEXIQUE = [
  ["LONG", "Tu gagnes si le prix monte (achat)."], ["SHORT", "Tu gagnes si le prix baisse (vente à découvert, avec marge)."],
  ["Bougie 15 min", "Un bâton qui résume 15 minutes : ouverture, plus haut, plus bas, clôture. Vert = a monté, rouge = a baissé."],
  ["Clôture", "Le prix à la fin de la bougie. Le bot ne décide que sur des clôtures, jamais sur un mouvement en cours."],
  ["Mèche", "Le trait fin au-dessus ou en dessous de la bougie : là où le prix est allé sans y rester."],
  ["Support / résistance", "Un prix où le marché a déjà rebondi plusieurs fois (support en bas, résistance en haut)."],
  ["Stop loss (SL)", "L'ordre qui coupe ta perte automatiquement. Obligatoire, toujours."],
  ["Take profit (TP)", "Les prix où tu encaisses : 30 % au TP1, 40 % au TP2, 30 % au TP3."],
  ["R", "Ton risque. +2 R = tu gagnes deux fois ce que tu risquais. −1 R = le SL a été touché."],
  ["Multiplicateur (levier)", "Permet d'ouvrir une position plus grosse que ton solde. Ici il ne sert qu'à réduire la marge bloquée : la perte au SL reste la même."],
  ["Liquidation", "Si le prix va trop loin contre toi avec du levier, Kraken ferme ta position. Le site refuse un multiplicateur qui mettrait la liquidation avant ton SL."],
  ["Break-even", "Remonter le SL au prix d'entrée : tu ne peux plus perdre sur la partie restante."],
  ["Paper", "Entraînement : on suit le trade sur les vrais prix, sans argent réel."],
  ["Spread", "L'écart entre le meilleur prix d'achat et de vente. Trop grand = trop cher à trader."],
  ["Volume", "La quantité échangée. Une cassure avec du volume est plus crédible."],
];

const REGLES = [
  ["Toujours un SL", "Placé dès l'ouverture, sur Kraken aussi. Sans exception."],
  ["1 % de risque par trade", "Sur 90 €, tu acceptes de perdre 0,90 € si le SL est touché. Le site calcule la taille pour toi."],
  ["2 % de risque ouvert au maximum", "Même avec plusieurs trades en même temps."],
  ["Stop à −3 % dans la journée", "Le site bloque les nouveaux trades jusqu'au lendemain."],
  ["Pas de 🟢, pas de trade", "Attendre est une décision. Les meilleures occasions sont rares."],
];

export async function render(main, ctx) {
  main.innerHTML = `
    <h1>Apprendre</h1>
    <p>Tout ce qu'il faut pour comprendre les signaux du bot, même si tu n'as jamais tradé.</p>

    <section class="section"><h2>Les 5 règles du club</h2>
      <div class="grille">${REGLES.map(([t, d]) => `<div class="bloc"><h3>${esc(t)}</h3><p class="muted" style="margin:0">${esc(d)}</p></div>`).join("")}</div></section>

    <section class="section"><h2>Lire un ticket</h2>
      <div class="split egal">
        <div class="bloc">${ladder({ direction: "LONG", entryLow: 99.9, entryHigh: 100.2, sl: 99, tps: [101.6, 102.8, 104.1] })}</div>
        <div class="pile">
          <p>À droite de chaque trade, l'<b>échelle</b> montre les prix <b>à leur vraie distance</b>.</p>
          <p><span class="perte">La barre rouge</span>, c'est ce que tu risques : de l'entrée au SL = 1 R.</p>
          <p><span class="gain">La barre verte</span>, c'est ce que tu peux gagner. TP1 à +1,2 R, TP2 à +2,2 R, TP3 à +3,2 R.</p>
          <p>Si la barre verte n'est pas nettement plus longue que la rouge, le trade ne vaut pas le risque : le bot le refuse.</p>
        </div></div></section>

    <section class="section"><h2>Les conditions du bot, en exemples</h2>
      <p class="muted">Graphiques dessinés pour l'exemple (pas des vrais prix). Choisis une situation :</p>
      <div class="onglets" role="tablist">${EXAMPLES.map((e, i) => `<button role="tab" aria-selected="${i === 0}" data-ex="${i}">${esc(e.titre.split(" (")[0])}</button>`).join("")}</div>
      <div class="split">
        <figure><div class="graph" id="ex-chart"></div><figcaption id="ex-cap"></figcaption></figure>
        <div class="bloc pile" id="ex-txt"></div>
      </div></section>

    <section class="section"><h2>Le multiplicateur ne change pas ton risque</h2>
      <p>Joue avec les chiffres : la <b>perte au SL</b> ne bouge pas quand tu changes le multiplicateur. Seule la marge bloquée change.</p>
      <form class="bloc form" id="calc">
        <div class="trois">
          <label class="champ"><span>Solde (€)</span><input name="bal" inputmode="decimal" value="90"></label>
          <label class="champ"><span>Risque (%)</span><input name="risk" inputmode="decimal" value="1"></label>
          <label class="champ"><span>Multiplicateur : <b id="lv">x3</b></span><input type="range" name="lev" min="1" max="10" value="3"></label>
        </div>
        <div class="deux">
          <label class="champ"><span>Entrée</span><input name="entry" inputmode="decimal" value="100"></label>
          <label class="champ"><span>Stop loss</span><input name="sl" inputmode="decimal" value="99"></label>
        </div>
        <div id="calc-out" aria-live="polite"></div>
      </form></section>

    <section class="section"><h2>Mots à connaître</h2><dl class="lexique bloc">${LEXIQUE.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></section>

    <section class="section"><h2>Installer le site sur ton téléphone</h2>
      <div class="grille">
        <div class="bloc"><h3>iPhone (Safari)</h3><p class="muted" style="margin:0">Bouton Partager → « Sur l'écran d'accueil ». L'icône du loup apparaît comme une app.</p></div>
        <div class="bloc"><h3>Android (Chrome)</h3><p class="muted" style="margin:0">Menu ⋮ → « Installer l'application » ou « Ajouter à l'écran d'accueil ».</p></div>
      </div></section>`;

  let chart;
  const show = (i) => {
    const ex = EXAMPLES[i];
    const d = ex.build();
    chart?.remove();
    chart = candleChart(main.querySelector("#ex-chart"), d.bars, { lines: d.lines, markers: d.markers });
    main.querySelector("#ex-cap").textContent = `Exemple illustratif · ${ex.sens ? "direction : " + ex.sens : "aucun trade"}`;
    main.querySelector("#ex-txt").innerHTML = `<h3>${esc(ex.titre)}</h3>${ex.texte.map((p) => `<p>${p}</p>`).join("")}`;
    main.querySelectorAll("[data-ex]").forEach((b) => b.setAttribute("aria-selected", b.dataset.ex == i));
  };
  main.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => show(+b.dataset.ex)));
  show(0);
  ctx.onLeave(() => chart?.remove());

  const f = main.querySelector("#calc");
  const calc = () => {
    const v = (n) => num(f.elements[n].value);
    const lev = +f.elements.lev.value;
    f.querySelector("#lv").textContent = "x" + lev;
    const entry = v("entry"), sl = v("sl");
    const p = planTrade({ balance: v("bal"), riskPct: v("risk"), entry, sl, tps: [], direction: sl < entry ? "LONG" : "SHORT",
      leverage: lev, feeTaker: 0, eurPerQuote: 1 });
    f.querySelector("#calc-out").innerHTML = !p.qty ? `<p class="alerte rouge">${esc(p.errors.join(" "))}</p>` : `
      <dl class="chiffres"><div><dt>Perte si SL touché</dt><dd class="perte">${eur(-p.lossAtSlEur)}</dd></div>
      <div><dt>Quantité</dt><dd>${+p.qty.toPrecision(5)}</dd></div><div><dt>Valeur de la position</dt><dd>${eur(p.notionalEur)}</dd></div>
      <div><dt>Marge bloquée</dt><dd>${eur(p.marginEur)}</dd></div><div><dt>SL à</dt><dd>${pct(p.slPct, 2)} de l'entrée</dd></div></dl>
      ${p.errors.length ? `<p class="alerte rouge">${esc(p.errors.join(" "))}</p>` : ""}`;
  };
  f.addEventListener("input", calc);
  calc();
}
