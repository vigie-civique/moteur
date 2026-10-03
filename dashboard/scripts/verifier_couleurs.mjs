#!/usr/bin/env node
// Garde-fou du thème : refuse une couleur écrite en dur hors de src/lib/theme.css.
//
// Jusqu'au 03/10/2026, l'atelier écrivait ~1 600 couleurs en dur dans 55
// fichiers, sans aucune variable : un thème clair était impossible, et changer
// une nuance voulait dire la retrouver partout. Elles passent toutes par les
// jetons de lib/theme.css (`var(--texte)`), et pour d3 ou Leaflet par
// `couleur('--texte')` (lib/theme.js). Une seule couleur littérale de retour
// dans un composant, et le thème clair a un trou que personne ne voit en sombre.
//
// Ce script tourne AVANT `vite build` (cf. package.json) et le fait échouer.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'

const RACINE = resolve(process.cwd(), 'src')
const JETONS = 'lib/theme.css'          // le seul endroit où une couleur s'écrit

// Exceptions assumées, chacune pour une raison précise. Toute nouvelle entrée
// ici doit être justifiée : c'est la porte par laquelle le défaut reviendrait.
// `bloc` borne l'exception à un passage du fichier (début et fin inclus).
const EXCEPTIONS = [
  {
    fichier: 'routes/atelier/dossiers/+page.svelte',
    bloc: [/const STYLE = `/, /display:inline-block\}`/],
    raison: "Feuille de style du dossier EXPORTÉ : un document HTML autonome, " +
            "imprimé ou envoyé hors de l'atelier, qui ne charge pas theme.css et " +
            "doit rester noir sur blanc quel que soit le thème de qui l'exporte.",
  },
  {
    fichier: 'routes/beta/+page.svelte',
    raison: "Maquette figée de la page d'accueil du site PUBLIC, en clair dans " +
            "les deux thèmes : elle montre le public tel qu'il est (hors du " +
            "périmètre du thème de l'atelier). Aucun lien de l'atelier n'y mène.",
  },
]

const HEX = /(^|[\s:(,'"`=])(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{1}|[0-9a-fA-F]{3}|[0-9a-fA-F]{5})?)(?![0-9a-zA-Z_-])/g
const FONCTION = /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/g
// Noms de couleurs CSS : seulement dans une déclaration de style, où un mot
// comme « orange » est sûrement une couleur (ailleurs, c'est souvent une classe).
const NOMS = 'white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|silver|navy|teal|maroon|olive|lime|aqua|fuchsia|brown|gold|cyan|magenta|indigo|violet|crimson|tomato|coral|salmon|khaki|beige|ivory|lavender'
const NOMME = new RegExp(
  `\\b(color|background(?:-color)?|border(?:-[a-z]+)*|outline(?:-color)?|fill|stroke|box-shadow|text-decoration-color|caret-color|accent-color)\\s*:[^;{}"'\\n]*(?<![\\w-])(${NOMS})(?![\\w-])`, 'gi')

/** Remplace les commentaires par des espaces, en gardant les positions :
 *  une couleur citée dans un commentaire n'est pas affichée. */
function masquer(texte) {
  const blanc = (m) => m.replace(/[^\n]/g, ' ')
  return texte
    .replace(/<!--[\s\S]*?-->/g, blanc)
    .replace(/\/\*[\s\S]*?\*\//g, blanc)
    .replace(/(?<![:"'`\\])\/\/[^\n]*/g, blanc)
}

function fichiers(dir) {
  const out = []
  for (const nom of readdirSync(dir)) {
    const p = join(dir, nom)
    if (statSync(p).isDirectory()) out.push(...fichiers(p))
    else if (/\.(svelte|js|ts|css|html)$/.test(nom)) out.push(p)
  }
  return out
}

function lignesExclues(rel, lignes) {
  const exclues = new Set()
  for (const e of EXCEPTIONS.filter(e => e.fichier === rel)) {
    if (!e.bloc) return null                      // tout le fichier
    let dedans = false
    lignes.forEach((l, i) => {
      if (!dedans && e.bloc[0].test(l)) dedans = true
      if (dedans) exclues.add(i)
      if (dedans && e.bloc[1].test(l)) dedans = false
    })
  }
  return exclues
}

const constats = []
for (const chemin of fichiers(RACINE)) {
  const rel = relative(RACINE, chemin).split(sep).join('/')
  if (rel === JETONS) continue
  const brut = readFileSync(chemin, 'utf8')
  const lignes = masquer(brut).split('\n')
  const exclues = lignesExclues(rel, lignes)
  if (exclues === null) continue
  lignes.forEach((l, i) => {
    if (exclues.has(i)) return
    const vus = [
      ...[...l.matchAll(HEX)].map(m => m[2]),
      ...[...l.matchAll(FONCTION)].map(m => m[0] + '…)'),
      ...[...l.matchAll(NOMME)].map(m => m[2]),
    ]
    for (const v of vus) constats.push(`  src/${rel}:${i + 1}  ${v}`)
  })
}

if (constats.length) {
  console.error(`\n✖ ${constats.length} couleur(s) écrite(s) en dur hors de src/${JETONS} :\n`)
  console.error(constats.join('\n'))
  console.error(`\nUtiliser un jeton : var(--texte), var(--danger)… (la liste est dans`)
  console.error(`src/${JETONS}). Pour d3 ou Leaflet : couleur('--texte') de lib/theme.js.`)
  console.error(`Une exception se justifie dans scripts/verifier_couleurs.mjs, pas ailleurs.\n`)
  process.exit(1)
}
console.log(`✓ aucune couleur en dur hors de src/${JETONS} (${EXCEPTIONS.length} exceptions motivées)`)
