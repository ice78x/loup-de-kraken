// Graphiques d'EXEMPLE pour apprendre (données inventées, dessinées à la main pour illustrer une règle).
// Chaque scénario = des bougies 15 min + les lignes/marqueurs qui expliquent ce qu'il faut voir.

function build(closes, start = 99) {
  const t0 = Math.floor(Date.UTC(2026, 0, 5, 8) / 1000);
  let o = start;
  return closes.map((c, i) => {
    const [close, hi, lo] = Array.isArray(c) ? c : [c];
    const h = hi ?? Math.max(o, close) + 0.15;
    const l = lo ?? Math.min(o, close) - 0.15;
    const bar = [t0 + i * 900, o, h, l, close];
    o = close;
    return bar;
  });
}
const RANGE = [99.2, 98.8, 99.5, 98.6, 99.6, 99.1, 98.7, [99.5, 99.95], 99.0, 98.5, 99.3, 98.9, 99.6, 99.2, 98.8, [99.4, 99.9], 99.0];
const t = (bars, i) => bars[i][0];

export const EXAMPLES = [
  {
    id: "cassure", titre: "Cassure + retest (le setup préféré du bot)", sens: "LONG",
    build() {
      const bars = build([...RANGE, [101.1, 101.3, 99.0], 100.9, 100.6, [100.5, 100.8, 100.05], [101.3, 101.4, 100.45],
        101.8, 102.3, 102.1, 102.9, 103.4, 103.2, 104.1]);
      const i = RANGE.length;
      return {
        bars,
        lines: [
          { price: 100, color: "#9DB4C8", title: "Résistance", dashed: true, width: 1 },
          { price: 100.5, color: "#F2B544", title: "Entrée", width: 1 },
          { price: 99.55, color: "#FF6B6B", title: "SL" },
          { price: 101.8, color: "#3DDC97", title: "TP1", width: 1 }, { price: 102.7, color: "#3DDC97", title: "TP2", width: 1 },
          { price: 103.9, color: "#3DDC97", title: "TP3", width: 1 },
        ],
        markers: [
          { time: t(bars, i), text: "1. Cassure clôturée", position: "aboveBar" },
          { time: t(bars, i + 3), text: "2. Retest", position: "belowBar", shape: "arrowUp", color: "#9DB4C8" },
          { time: t(bars, i + 4), text: "3. Confirmation → entrée", position: "belowBar", shape: "arrowUp", color: "#3DDC97" },
        ],
      };
    },
    texte: [
      "Le prix bute plusieurs fois sous 100 : c'est une <b>résistance</b>.",
      "Une bougie 15 min <b>clôture</b> au-dessus, avec du volume. Une mèche seule ne suffit pas.",
      "Le prix revient toucher 100 par le haut (le <b>retest</b>) et repart : l'ancienne résistance devient un support.",
      "On entre après la bougie de confirmation. Le SL va juste sous le retest : si le prix repasse sous 100, le scénario est faux.",
    ],
  },
  {
    id: "fausse", titre: "Fausse cassure (piège)", sens: "SHORT",
    build() {
      const bars = build([...RANGE, [100.7, 100.9, 99.2], [99.3, 100.8, 99.1], 99.0, 98.6, 98.9, 98.2, 97.9, 98.1, 97.4, 97.1]);
      const i = RANGE.length;
      return {
        bars,
        lines: [
          { price: 100, color: "#9DB4C8", title: "Résistance", dashed: true, width: 1 },
          { price: 99.2, color: "#F2B544", title: "Entrée", width: 1 }, { price: 101.1, color: "#FF6B6B", title: "SL" },
          { price: 98.3, color: "#3DDC97", title: "TP1", width: 1 }, { price: 97.4, color: "#3DDC97", title: "TP2", width: 1 },
        ],
        markers: [
          { time: t(bars, i), text: "Cassure…", position: "aboveBar" },
          { time: t(bars, i + 1), text: "…réintégrée : piège", position: "aboveBar", color: "#FF6B6B" },
        ],
      };
    },
    texte: [
      "Le prix clôture au-dessus de 100… puis la bougie suivante clôture <b>de nouveau dessous</b>.",
      "Les acheteurs de la cassure sont piégés : leurs stops, juste en dessous, poussent le prix vers le bas.",
      "Le bot ne l'achète pas. Il peut proposer un SHORT, avec le SL au-dessus du plus haut du piège.",
    ],
  },
  {
    id: "sweep", titre: "Sweep de liquidité (chasse aux stops)", sens: "SHORT",
    build() {
      const bars = build([...RANGE, [99.4, 101.2, 99.1], [98.9, 99.5, 98.7], 98.6, 98.9, 98.2, 97.8, 98.0, 97.3]);
      const i = RANGE.length;
      return {
        bars,
        lines: [
          { price: 100, color: "#9DB4C8", title: "Plus hauts", dashed: true, width: 1 },
          { price: 99.0, color: "#F2B544", title: "Entrée", width: 1 }, { price: 101.45, color: "#FF6B6B", title: "SL" },
          { price: 97.9, color: "#3DDC97", title: "TP1", width: 1 },
        ],
        markers: [
          { time: t(bars, i), text: "Longue mèche au-dessus", position: "aboveBar" },
          { time: t(bars, i + 1), text: "Confirmation", position: "aboveBar", color: "#FF6B6B" },
        ],
      };
    },
    texte: [
      "Au-dessus des plus hauts, beaucoup de traders ont placé leurs stops : c'est de la <b>liquidité</b>.",
      "Une grande mèche va la chercher, puis la bougie clôture sous le niveau, avec beaucoup de volume.",
      "Le bot attend la <b>clôture suivante plus bas</b> avant de proposer un SHORT. Jamais sur la mèche elle-même.",
    ],
  },
  {
    id: "meche", titre: "Une mèche seule : pas de trade", sens: null,
    build() {
      const bars = build([...RANGE, [99.5, 100.7, 99.2], 99.6, 99.2, 99.7, 99.3, 99.8, 99.4, 99.6]);
      return {
        bars,
        lines: [{ price: 100, color: "#9DB4C8", title: "Résistance", dashed: true, width: 1 }],
        markers: [{ time: t(bars, RANGE.length), text: "Mèche, pas de clôture", position: "aboveBar", color: "#9DB4C8" }],
      };
    },
    texte: [
      "La mèche dépasse 100, mais la bougie <b>clôture dessous</b>, sans volume particulier : ce n'est pas une cassure.",
      "Ce n'est pas non plus un vrai rejet : le prix reste coincé dans son range.",
      "Résultat : 🛑 aucun trade. Acheter une mèche, c'est souvent se faire piéger.",
    ],
  },
  {
    id: "tendance", titre: "Repli dans une tendance", sens: "LONG",
    build() {
      const bars = build([99, 99.6, 100.4, 100.1, 101.0, 101.8, 101.4, 102.3, 103.1, 103.9, 103.5, 102.9, 102.6,
        [102.5, 102.8, 102.2], [103.2, 103.3, 102.4], 103.8, 104.4, 104.1, 104.9, 105.6, 105.2, 106.1], 98.8);
      return {
        bars,
        lines: [
          { price: 103.2, color: "#F2B544", title: "Entrée", width: 1 }, { price: 101.95, color: "#FF6B6B", title: "SL" },
          { price: 104.4, color: "#3DDC97", title: "TP1", width: 1 }, { price: 105.3, color: "#3DDC97", title: "TP2", width: 1 },
          { price: 106.4, color: "#3DDC97", title: "TP3", width: 1 },
        ],
        markers: [
          { time: t(bars, 9), text: "Plus haut", position: "aboveBar", color: "#9DB4C8" },
          { time: t(bars, 13), text: "Creux plus haut", position: "belowBar", shape: "arrowUp", color: "#9DB4C8" },
          { time: t(bars, 14), text: "Reprise → entrée", position: "belowBar", shape: "arrowUp", color: "#3DDC97" },
        ],
      };
    },
    texte: [
      "Des plus hauts de plus en plus hauts et des creux de plus en plus hauts : c'est une <b>tendance haussière</b>.",
      "Le prix recule (30 à 80 % de la dernière poussée) sans casser le creux précédent.",
      "Dès qu'une bougie 15 min repart au-dessus des dernières, on entre dans le sens de la tendance, SL sous le creux.",
    ],
  },
  {
    id: "etendu", titre: "Mouvement déjà trop étendu", sens: null,
    build() {
      const bars = build([...RANGE, [101.1, 101.3, 99.0], 101.9, 102.8, 103.6, 104.3, 104.9]);
      return {
        bars,
        lines: [{ price: 100, color: "#9DB4C8", title: "Niveau cassé", dashed: true, width: 1 }],
        markers: [{ time: t(bars, RANGE.length + 5), text: "Trop loin : on attend", position: "aboveBar", color: "#F2B544" }],
      };
    },
    texte: [
      "La cassure est bonne, mais le prix est déjà parti très loin du niveau, sans retest.",
      "Entrer ici oblige à mettre un SL très loin (gros risque) ou très près (il saute sur le moindre recul).",
      "Le bot passe en 🟡 SURVEILLER : il attend un retour vers le niveau.",
    ],
  },
];
