// Apprendre : les règles, le lexique, et des graphiques d'exemple pour chaque condition utilisée par le bot.
import { candleChart } from "../charts.js";
import { EXAMPLES } from "../examples.js";
import { ladder } from "../ladder.js";
import { liqFraction, planTrade } from "../sizing.js";
import { krakenFees } from "../fees.js";
import { esc, eur, num, pct, px } from "../ui.js";

const LEXIQUE = [
  ["LONG", "Tu gagnes si le prix monte (achat)."], ["SHORT", "Tu gagnes si le prix baisse (vente à découvert, avec marge)."],
  ["Bougie 15 min", "Un bâton qui résume 15 minutes : ouverture, plus haut, plus bas, clôture. Vert = a monté, rouge = a baissé."],
  ["Clôture", "Le prix à la fin de la bougie. Le bot ne décide que sur des clôtures, jamais sur un mouvement en cours."],
  ["Mèche", "Le trait fin au-dessus ou en dessous de la bougie : là où le prix est allé sans y rester."],
  ["Support / résistance", "Un prix où le marché a déjà rebondi plusieurs fois (support en bas, résistance en haut)."],
  ["Stop loss (SL)", "L'ordre qui coupe ta perte automatiquement. Règle du club : toujours en mettre un. Sans stop, tu peux perdre toute ta mise (liquidation)."],
  ["Take profit (TP)", "Les prix où tu encaisses : 30 % au TP1, 40 % au TP2, 30 % au TP3."],
  ["R", "Ton risque. +2 R = tu gagnes deux fois ce que tu risquais. −1 R = le SL a été touché."],
  ["Mise (marge isolée)", "L'argent que tu bloques sur un trade. En marge isolée, c'est le maximum que ce trade peut te coûter : le reste de ton solde n'est pas touché."],
  ["Levier (multiplicateur)", "Position = mise × levier. Pour une même quantité, le levier réduit seulement la mise bloquée. Pour une même mise, plus de levier = position plus grosse : gains ET pertes multipliés."],
  ["Levier conseillé", "Le levier que le site propose pour chaque trade : la liquidation reste loin derrière le stop, et avec environ 25 % de ton solde en mise, le stop te coûte à peu près ton risque habituel."],
  ["Liquidation", "Si le prix va trop loin contre toi avec du levier, Kraken ferme ta position et tu perds la mise. Le site te prévient si elle arrive avant ton stop."],
  ["Ordre limite / au marché", "Limite : tu fixes ton prix et tu attends (frais Kraken plus bas). Au marché : exécuté tout de suite au prix du moment (frais plus hauts)."],
  ["Futures perpétuel (PF_…)", "Contrat Kraken qui suit le prix d'un actif, sans date de fin. C'est ce qui permet le levier et le SHORT."],
  ["Marge de maintenance", "Le minimum de marge à garder sur une position. En dessous, Kraken liquide. Futures EEE : la moitié de la marge minimale (5 % de la position à x10 max)."],
  ["Mark price", "Le prix de référence que Kraken utilise pour la liquidation et ta perte en cours (prix de l'indice + un petit écart). Il évite d'être liquidé sur une seule mèche."],
  ["Funding (financement)", "Petit paiement toutes les heures entre LONG et SHORT pour que le perpétuel colle au prix réel. Peut te coûter ou te rapporter."],
  ["Réduction seule (reduce-only)", "Option d'un ordre stop ou take profit : il ne peut que fermer ta position, jamais en ouvrir une nouvelle par erreur."],
  ["Break-even", "Remonter le SL au prix d'entrée : tu ne peux plus perdre sur la partie restante."],
  ["Paper", "Entraînement : on suit le trade sur les vrais prix, sans argent réel."],
  ["Spread", "L'écart entre le meilleur prix d'achat et de vente. Trop grand = trop cher à trader."],
  ["Volume", "La quantité échangée. Une cassure avec du volume est plus crédible."],
];

const REGLES = [
  ["Toujours un SL", "Placé dès l'ouverture, sur Kraken aussi. Sans exception."],
  ["1 % de risque par trade", "Sur 90 €, tu acceptes de perdre 0,90 € si le SL est touché. Avant d'enregistrer, le site te montre ta perte au stop pour la quantité choisie."],
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

    <section class="section" id="perps"><h2>Le vrai système Kraken : les futures perpétuels</h2>
      <p>Sur Kraken Pro, le trading avec levier (LONG ou SHORT) se fait avec des <b>futures perpétuels</b> (paires « PF_… », ex. PF_XBTUSD pour le bitcoin).
        Voici comment ça marche vraiment, et comment le club calcule ton risque.</p>
      <div class="grille">
        <div class="bloc"><h3>1. Un contrat qui suit le prix</h3><p class="muted" style="margin:0">Tu n'achètes pas la crypto : tu prends une position qui gagne
          ou perd comme son prix. <b>Pas de date de fin</b> (« perpétuel ») : tu fermes quand tu veux. Ta garantie est comptée en <b>dollars</b>
          (les euros sont acceptés comme garantie, avec une petite décote).</p></div>
        <div class="bloc"><h3>2. Marge isolée ou croisée</h3><p class="muted" style="margin:0"><b>Isolée</b> (celle du club) : seule la marge mise sur ce trade
          est en jeu. <b>Croisée</b> : tout ton portefeuille sert de garantie. Le choix se fait <b>par paire, avant d'ouvrir</b> : impossible de changer
          une position déjà ouverte.</p></div>
        <div class="bloc"><h3>3. Levier jusqu'à x10</h3><p class="muted" style="margin:0">En Europe, Kraken autorise jusqu'à <b>x10</b> sur la plupart des
          perpétuels. Marge (ta mise) = valeur de la position ÷ levier. x10 → 10 % de la position bloqués.</p></div>
        <div class="bloc"><h3>4. La liquidation</h3><p class="muted" style="margin:0">Kraken ferme ta position quand <b>ta marge + ta perte en cours</b>
          passe sous la <b>marge de maintenance</b> (la moitié de la marge minimale : 5 % de la position sur un contrat à x10 max).
          Résultat : à x10, liquidé après ≈ <b>−5 %</b> ; à x5 ≈ −15 % ; à x3 ≈ −28 % ; à x2 ≈ −45 %. Le prix utilisé est le <b>« mark price »</b>
          (prix de référence), pas le dernier échange.</p></div>
        <div class="bloc"><h3>5. Le financement (funding)</h3><p class="muted" style="margin:0">Pour coller au prix spot, <b>toutes les heures</b>
          les LONG paient les SHORT (ou l'inverse) un petit pourcentage. Sur un trade de quelques heures c'est en général faible, mais ça compte
          dans ton résultat réel sur Kraken. Le site ne peut pas le connaître à l'avance : il ne l'ajoute pas.</p></div>
        <div class="bloc"><h3>6. Les frais</h3><p class="muted" style="margin:0">Futures Kraken (niveau d'entrée) : <b>0,02 %</b> pour un ordre limite
          qui attend, <b>0,05 %</b> pour un ordre au marché, sur la <b>valeur de la position</b> (pas sur ta mise). Bien moins cher que le spot
          (0,40 % / 0,80 %).</p></div>
      </div>

      <h3 class="section">La méthode du club : % de risque d'abord, levier ensuite</h3>
      <ol class="etapes">
        <li><b>Repère l'entrée et le stop</b> sur le graphique (le stop = là où ton idée est fausse).</li>
        <li><b>Risque en €</b> = ton solde × ton % de risque. Ex. 90 € × 1 % = <b>0,90 €</b>.</li>
        <li><b>Quantité</b> = risque € ÷ (distance entrée → stop + frais). C'est elle qui fixe ta perte au stop.</li>
        <li><b>Levier ensuite</b> : il ne change que la marge bloquée. Choisis-le pour que la <b>liquidation reste au moins 2× plus loin que le stop</b>
          (le site te conseille un levier sur chaque trade).</li>
        <li><b>Sur Kraken Pro</b> : onglet Futures → la paire PF_… → marge <b>isolée</b> + levier → Acheter/Long ou Vendre/Short → ordre <b>Limite</b>
          → la quantité calculée. Puis ajoute tout de suite un <b>stop</b> et tes <b>take profit</b> en « réduction seule » (ils ne peuvent que fermer, jamais ouvrir).</li>
      </ol>

      <form class="bloc form" id="perp">
        <h3 style="margin-top:0">Calculette futures perpétuel (règles Kraken)</h3>
        <div class="choix" role="radiogroup" aria-label="Sens">
          <label class="long"><input type="radio" name="dir" value="LONG" checked><span>LONG ↑</span></label>
          <label class="short"><input type="radio" name="dir" value="SHORT"><span>SHORT ↓</span></label>
        </div>
        <div class="trois">
          <label class="champ"><span>Solde (€)</span><input name="bal" inputmode="decimal" value="${(+ctx.me?.balance_eur || 90).toFixed(2)}"></label>
          <label class="champ"><span>Risque (%)</span><input name="risk" inputmode="decimal" value="${+ctx.me?.risk_pct || 1}"></label>
          <label class="champ"><span>Levier : <b id="pv">x5</b></span><input type="range" name="lev" min="1" max="10" value="5"></label>
        </div>
        <div class="deux">
          <label class="champ"><span>Entrée ($)</span><input name="entry" inputmode="decimal" value="100"></label>
          <label class="champ"><span>Stop ($)</span><input name="sl" inputmode="decimal" value="98"></label>
        </div>
        <div class="choix" role="radiogroup" aria-label="Type d'ordre">
          <label><input type="radio" name="ord" value="limit" checked><span>Limite · 0,02 %</span></label>
          <label><input type="radio" name="ord" value="market"><span>Marché · 0,05 %</span></label>
        </div>
        <div id="perp-out" aria-live="polite"></div>
        <p class="small muted">Taux EUR/USD pris à 1 pour l'exemple. Le funding (toutes les heures) n'est pas compté. La liquidation est approximative :
          Kraken utilise le « mark price » et ses barèmes de marge.</p>
      </form>
    </section>

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

    <section class="section"><h2>Lire un graphique</h2>
      <p>Dans <a href="#/graphiques">Graphiques</a>, ouvre n'importe quelle paire : active les outils (moyennes, volume, supports, structure HH/HL, RSI, VWAP)
        un par un. Chaque outil affiche son explication sous le graphique, et la « lecture rapide » te résume ce qu'ils disent.</p></section>

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

  // Calculette « futures perpétuel » : taille par le % de risque, puis levier → marge, maintenance, liquidation (règles Kraken).
  const f = main.querySelector("#perp");
  const fees = krakenFees({ venue: "futures" });
  const calc = () => {
    const v = (n) => num(f.elements[n].value);
    const lev = +f.elements.lev.value;
    f.querySelector("#pv").textContent = "x" + lev;
    const dir = f.elements.dir.value, entry = v("entry"), sl = v("sl"), bal = v("bal");
    const limit = f.elements.ord.value === "limit";
    const p = planTrade({ balance: bal, riskPct: v("risk"), entry, sl, tps: [], direction: dir, leverage: lev, venue: "futures", maxLev: 10,
      feeTaker: fees.taker, feeMaker: fees.maker, entryIsMaker: limit, eurPerQuote: 1, lotDecimals: 6, strict: false });
    const out = f.querySelector("#perp-out");
    if (!p.qty) { out.innerHTML = `<p class="alerte rouge">${esc(p.errors.join(" "))}</p>`; return; }
    const d = liqFraction(lev, "futures", 10);
    const liq = dir === "LONG" ? entry * (1 - d) : entry * (1 + d);
    const maint = p.notionalEur * 0.05;
    out.innerHTML = `
      <dl class="chiffres">
        <div><dt>Perte si stop touché</dt><dd class="num perte">${eur(-p.lossAtSlEur)}</dd><span class="small muted">${pct(p.effectiveRiskPct, 2)} du solde, frais compris</span></div>
        <div><dt>Quantité</dt><dd class="num">${+p.qty.toPrecision(6)}</dd><span class="small muted">unités de l'actif</span></div>
        <div><dt>Valeur de la position</dt><dd class="num">${eur(p.notionalEur)}</dd></div>
        <div><dt>Ta mise (marge isolée x${lev})</dt><dd class="num">${eur(p.marginEur)}</dd><span class="small muted">${pct((p.marginEur / bal) * 100, 1)} du solde</span></div>
        <div><dt>Marge de maintenance</dt><dd class="num">${eur(maint)}</dd><span class="small muted">5 % de la position</span></div>
        <div><dt>Liquidation ≈</dt><dd class="num perte">${px(liq)} $</dd><span class="small muted">${pct(d * 100, 1)} de mouvement · stop à ${pct(p.slPct, 2)}</span></div>
        <div><dt>Frais (entrée + sortie au stop)</dt><dd class="num">${eur(-(p.notionalEur * ((limit ? fees.maker : fees.taker) + fees.taker)) / 100)}</dd></div>
      </dl>
      ${d * 100 < 2 * p.slPct ? `<p class="alerte rouge">⚠️ À x${lev}, la liquidation (${pct(d * 100, 1)}) est trop près du stop (${pct(p.slPct, 2)}) : baisse le levier.</p>`
        : `<p class="alerte verte">✅ La liquidation est ${((d * 100) / p.slPct).toLocaleString("fr-FR", { maximumFractionDigits: 1 })}× plus loin que le stop : ta perte réelle sera celle du stop.</p>`}
      ${p.marginEur > bal ? '<p class="alerte rouge">Ta mise dépasse ton solde : monte le levier (ta perte au stop ne change pas).</p>' : ""}
      <p class="small">Change le levier : la <b>quantité</b> et la <b>perte au stop</b> ne bougent pas, seules ta <b>mise</b> et la <b>liquidation</b> changent.
        C'est ça, utiliser le levier sans augmenter son risque.</p>`;
  };
  f.addEventListener("input", calc);
  f.addEventListener("change", calc);
  calc();
}
