#!/usr/bin/env node
// Garde-fou de publication : refuse un build dont les pages sont vides.
//
// Jusqu'au 12/08/2026, 20 des 24 routes chargeaient leurs données en `onMount`.
// Le HTML livré ne contenait donc que « Chargement… » : invisible des moteurs
// de recherche, vide dans Internet Archive, page blanche au moindre échec de
// fetch. Rien dans la chaîne ne le signalait — le build passait, le site
// s'affichait correctement dans un navigateur, et le défaut n'était visible
// qu'en lisant la source.
//
// Ce script fait échouer le build si le symptôme réapparaît. Il tourne après
// `vite build` (cf. package.json).
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Même répertoire que celui qu'`adapter-static` vient d'écrire : un aperçu
// figé (`VIGIE_BUILD_DIR`) doit être contrôlé, pas ignoré.
//
// `resolve` et non `join` : `join('/a/public', '/a/audits/build')` CONCATÈNE et
// donne `/a/public/a/audits/build`. L'aperçu de l'atelier passe un chemin
// absolu — le contrôle regardait donc un répertoire inexistant, n'y trouvait
// aucune page, et annonçait « ✓ 0 pages vérifiées : toutes livrent leur
// contenu ». Vrai, et vide de sens. Constaté le 23/08/2026 sur le premier
// aperçu construit depuis l'atelier.
const BUILD = resolve(process.cwd(), process.env.VIGIE_BUILD_DIR || 'build')

if (!existsSync(BUILD)) {
  console.error(`\n✖ ${BUILD} n'existe pas.`)
  console.error("\nVIGIE_BUILD_DIR ne désigne pas le répertoire qu'adapter-static")
  console.error("vient d'écrire, ou le build a échoué avant d'écrire quoi que ce soit.\n")
  process.exit(1)
}

// Exceptions assumées, chacune pour une raison précise. Toute nouvelle entrée
// ici doit être justifiée : c'est la porte par laquelle le défaut reviendrait.
//
//  - carte.html      Leaflet a besoin du DOM, et une carte n'a pas de contenu
//                    textuel à prérendre. Son équivalent tabulaire reste à faire.
//  - recherche.html  La page rend bien tout son contenu (formulaire, compteurs,
//                    explication) ; elle charge en arrière-plan l'index
//                    transversal de 940 Ko, trop lourd pour être embarqué —
//                    l'embarquer ferait une page à 1 Mo. Le mot « Chargement »
//                    y désigne cet index, pas le contenu de la page.
//
// ⚠️ Nommées par leur ROUTE, pas par leur fichier. Le dossier remis se construit
// avec `VIGIE_HORS_LIGNE=1` depuis le 12/09/2026 : chaque route y devient
// `carte/index.html` au lieu de `carte.html`. Des exceptions écrites en noms de
// fichiers ne matchaient plus rien, et le contrôle refusait le dossier entier
// pour la carte — une page dont l'attendeur est légitime et documenté ici.
const EXCEPTIONS = new Set(['carte', 'recherche'])

/** La route que sert cette page, quelle que soit la forme du build. */
const routeDe = (rel) => rel
  .replace(/\\/g, '/')
  .replace(/\/index\.html$/, '')
  .replace(/\.html$/, '')

// Le SYMPTÔME est « Chargement… », pas le mot « chargement ». Le contrôle
// cherchait /chargement/i n'importe où dans le rendu : il a refusé tout le site
// de Saillans le 23/08/2026 pour un marché intitulé « Acquisition d'un véhicule
// de collecte benne à CHARGEMENT vertical ». Trois pages bloquées, aucune vide,
// et l'instance entière impubliable à cause d'un mot d'une source publique.
//
// Un attendeur s'écrit toujours pareil — majuscule de début de phrase puis
// points de suspension : « Chargement de la carte… ». Une donnée, jamais. On
// exige donc les deux, et le filet de sécurité reste `MINI_RENDU` : une page
// réellement vide se fait prendre à sa taille, quel que soit son texte.
const ATTENTE = /Chargement[^<]{0,40}(…|\.\.\.)/

// Taille minimale de HTML rendu (hors <script>) en dessous de laquelle une page
// est forcément une coquille : l'en-tête et le pied de page pèsent déjà ~6 Ko.
const MINI_RENDU = 6500

// Valeurs qui trahissent un calcul cassé plutôt qu'une donnée absente.
//
// Le contrôle ne les cherchait NULLE PART : la page « Le territoire en
// chiffres » a servi onze « undefined » en production, dans la comparaison des
// niveaux de vie, parce qu'une projection à cinq champs avait jeté le sixième
// que le gabarit affichait. Le build passait, les pages étaient pleines, et le
// défaut n'était visible qu'à l'œil, sur le site en ligne.
//
// ⚠️ Avec la casse et des limites de mot, sinon « NaN » se trouve dans
// fi-NAN-ces et gouver-NAN-ce : cherché sans bornes, il accusait 162 pages à
// tort. `undefined` et `null` ne sont retenus qu'en TEXTE affiché — un attribut
// HTML ou une classe peut légitimement les contenir.
const VALEURS_CASSEES = [
  { motif: /(?<![\w-])undefined(?![\w-])/, nom: 'undefined' },
  { motif: /(?<![\w-])NaN(?![\w-])/,       nom: 'NaN' },
  { motif: /\[object Object\]/,             nom: '[object Object]' },
  { motif: /(?<![\w-])Invalid Date(?![\w-])/, nom: 'Invalid Date' },
]

// Fonds de carte servis par des tiers.
//
// Trois cartes du site les chargeaient ailleurs — CARTO pour /carte,
// `tile.openstreetmap.org` pour /urbanisme et /entite. L'adresse IP de chaque
// lecteur partait donc chez un tiers, sur un site dont la page Confidentialité
// promet qu'aucun traceur ne le suit ; le dossier hors-ligne n'avait aucun
// fond ; et la politique d'usage des tuiles d'openstreetmap.org exclut l'usage
// systématique qu'en fait un site prérendu de plusieurs milliers de fiches.
//
// Corrigé en deux fois : /carte le 29/08/2026, /urbanisme et /entite le
// 30/08/2026. Deux fois, parce que la première correction n'a pas été
// contrôlée — rien dans la chaîne ne pouvait dire qu'il en restait deux. C'est
// ce que ce garde-fou répare : la prochaine carte ajoutée au site sera prise
// ici si elle appelle un tiers.
//
// ⚠️ Ce sont les hôtes de TUILES qui sont refusés, jamais openstreetmap.org
// lui-même : l'attribution ODbL exige un lien vers `www.openstreetmap.org`, et
// une fiche a le droit de citer `openstreetmap.org/node/…` comme sa source.
// Un lien est une chose que le lecteur clique, une tuile est une requête que
// son navigateur fait sans lui demander.
const FONDS_TIERS = /(?:[a-z0-9-]+\.)*(?:tile\.openstreetmap\.org|tile\.osm\.org|cartocdn\.com|cartodb-basemaps[a-z0-9-]*\.global\.ssl\.fastly\.net|stadiamaps\.com|api\.mapbox\.com|opentopomap\.org|server\.arcgisonline\.com|tiles\.wmflabs\.org|maptiler\.com)/

// Le fond tiers ne vit pas dans le HTML : il est écrit dans le bundle que la
// page charge. Un contrôle limité aux `.html` aurait vu le site du 29/08 tout
// propre, alors que deux modules de `_app/immutable/nodes/` appelaient encore
// openstreetmap. On lit donc aussi ce qui est SERVI à côté des pages.
const EXT_SERVIES = /\.(html|js|css)$/

/** Texte réellement affiché : hors balises, hors commentaires HTML. */
const texteAffiche = (html) => html
  .replace(/<script[\s\S]*?<\/script>/g, ' ')
  .replace(/<style[\s\S]*?<\/style>/g, ' ')
  .replace(/<!--[\s\S]*?-->/g, ' ')
  .replace(/<[^>]+>/g, ' ')

const pages = []
const servis = []
const caches = []
;(function parcourir(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) {
      // Un site statique n'a aucun répertoire caché à servir, hormis
      // `.well-known`. Le 16/09/2026, `/.data.precedent/` — le retour arrière de
      // la publication, rangé dans `static/` — était servi avec le snapshot du
      // 23/08. `publier-site.sh` le refuse déjà, mais après ce script : un
      // aperçu construit par l'atelier ne passe que par ici.
      if (f.startsWith('.') && f !== '.well-known') caches.push(p.slice(BUILD.length + 1))
      else parcourir(p)
    }
    else {
      if (f.endsWith('.html')) pages.push(p)
      if (EXT_SERVIES.test(f)) servis.push(p)
    }
  }
})(BUILD)

const problemes = []

for (const c of caches) {
  problemes.push(`${c}/ : répertoire caché dans le build — il partirait en ligne `
    + "(retirer de public/static/ ce qui n'y a pas sa place)")
}

for (const p of pages) {
  const rel = p.slice(BUILD.length + 1)
  if (rel === '404.html' || EXCEPTIONS.has(routeDe(rel))) continue

  const html = readFileSync(p, 'utf8')
  const rendu = html.replace(/<script[\s\S]*?<\/script>/g, '')

  if (ATTENTE.test(rendu)) {
    problemes.push(`${rel} : contient « Chargement… » — la page attend un fetch client`)
  }
  if (rendu.length < MINI_RENDU) {
    problemes.push(`${rel} : ${rendu.length} o de HTML rendu (< ${MINI_RENDU}) — page probablement vide`)
  }

  const texte = texteAffiche(html)
  for (const { motif, nom } of VALEURS_CASSEES) {
    if (motif.test(texte)) {
      const m = texte.match(new RegExp(`.{0,60}${nom.replace(/[[\]]/g, '\\$&')}.{0,40}`))
      problemes.push(`${rel} : affiche « ${nom} » — ${(m ? m[0] : '').trim().replace(/\s+/g, ' ')}`)
    }
  }
}

for (const p of servis) {
  const rel = p.slice(BUILD.length + 1)
  const m = readFileSync(p, 'utf8').match(FONDS_TIERS)
  if (m) {
    problemes.push(`${rel} : appelle un fond de carte tiers (${m[0]}) — `
      + "l'IP du lecteur partirait chez lui")
  }
}

// Un contrôle qui passe sur zéro page ne contrôle rien, et son « ✓ » est plus
// dangereux qu'une erreur : c'est exactement ce qu'il a affiché le 23/08/2026
// devant un répertoire inexistant. Le garde-fou doit d'abord se garantir
// lui-même.
if (pages.length === 0) {
  console.error(`\n✖ Aucune page trouvée dans ${BUILD}.`)
  console.error("\nLe build n'a rien écrit, ou VIGIE_BUILD_DIR ne désigne pas")
  console.error("le répertoire qu'adapter-static vient de remplir.\n")
  process.exit(1)
}

// ── Le build est-il ENTIER ? ────────────────────────────────────────────────
//
// Tout ce qui précède juge les pages PRÉSENTES. Le 04/10/2026, la mise en ligne
// a vidé `.svelte-kit/output` sous un aperçu en construction : l'aperçu est
// sorti à 88 pages sur 1 528, sans `_app/immutable` — donc servi sans feuille de
// style ni JavaScript — et ce script a annoncé « ✓ 72 pages vérifiées ». Chacune
// des 72 était pleine. Un build tronqué ne se voit qu'en comptant ce qui manque.
const incomplet = []

// 1. Le code du site. Sans lui, chaque page est un HTML nu.
const IMMUTABLE = join(BUILD, '_app', 'immutable')
if (!existsSync(IMMUTABLE) || readdirSync(IMMUTABLE).length === 0) {
  incomplet.push("_app/immutable est absent ou vide : le site serait servi sans "
    + 'feuille de style ni JavaScript')
}

// 2. Ce que la page d'accueil charge existe. Les ressources seulement (feuilles
//    de style, modules, images) : les liens entre pages sont l'affaire du
//    prérendu, qui les suit un à un.
const ACCUEIL = join(BUILD, 'index.html')
if (!existsSync(ACCUEIL)) {
  incomplet.push("index.html est absent : le build n'a pas de page d'accueil")
} else {
  const html = readFileSync(ACCUEIL, 'utf8')
  const refs = new Set()
  for (const m of html.matchAll(/<(?:link|script|img)\b[^>]*?\s(?:href|src)="([^"]+)"/g)) refs.add(m[1])
  for (const m of html.matchAll(/\bimport\(\s*"([^"]+)"\s*\)/g)) refs.add(m[1])
  for (const ref of refs) {
    // Ailleurs que sur ce site (canonique, flux d'un tiers) : rien à trouver ici.
    if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(ref)) continue
    const chemin = decodeURIComponent(ref.split(/[?#]/)[0])
    const cible = chemin.startsWith('/') ? join(BUILD, chemin) : resolve(dirname(ACCUEIL), chemin)
    if (!existsSync(cible)) incomplet.push(`index.html référence ${ref}, qui n'existe pas dans le build`)
  }
}

// 3. Pas moins de fiches que le snapshot n'en annonce. Le manifeste du snapshot
//    (`scripts/snapshot/manifeste.py`) compte les objets de chaque fichier ;
//    `entity_index.json` est la liste que `entite/[id]` prérend, une page par
//    entrée. Lu là où le site lit ses données (`src/lib/donnees.server.js`).
const DONNEES = process.env.VIGIE_DATA_DIR
  ? resolve(process.env.VIGIE_DATA_DIR)
  : join(process.cwd(), 'static', 'data')
const fiches = pages.filter((p) => routeDe(p.slice(BUILD.length + 1)).startsWith('entite/')).length
let plancher = null
try {
  const manifeste = JSON.parse(readFileSync(join(DONNEES, 'manifeste.json'), 'utf8'))
  plancher = (manifeste.fichiers || []).find((f) => f.chemin === 'entity_index.json')?.objets ?? null
} catch { /* dit plus bas : un contrôle non fait ne se tait pas */ }
if (plancher !== null && fiches < plancher) {
  incomplet.push(`${fiches} fiches sur les ${plancher} qu'annonce le manifeste du snapshot `
    + `(${pages.length} pages en tout) : le prérendu s'est arrêté en route`)
}

if (incomplet.length) {
  console.error(`\n✖ Build INCOMPLET dans ${BUILD} :\n`)
  for (const i of incomplet) console.error('  ' + i)
  console.error("\nUn build tronqué vient presque toujours d'un autre build lancé en")
  console.error("même temps : tous écrivent dans `.svelte-kit/output`. Relancer, seul —")
  console.error("`deploy/publier-site.sh` et l'atelier prennent le même verrou.\n")
  process.exit(1)
}

if (problemes.length) {
  console.error(`\n✖ ${problemes.length} problème(s) dans le rendu :\n`)
  for (const p of problemes) console.error('  ' + p)
  console.error("\nPage vide : les données doivent être lues au build dans")
  console.error('+page.server.js — gabarit src/routes/marches/+page.server.js.')
  console.error("Valeur cassée : le gabarit affiche un champ que le `load` ne")
  console.error("renvoie pas, ou un calcul sur une valeur absente.")
  console.error("Fond tiers : poser le fond avec `poserFond` de")
  console.error("src/lib/carte/fond.js, jamais un L.tileLayer distant.\n")
  process.exit(1)
}

// ── Contraste des jetons ─────────────────────────────────────────────────────
// Une couleur de texte se juge contre les fonds sur lesquels elle s'écrit. Le
// site n'a qu'une palette, déclarée une fois (`:root` de +layout.svelte) : la
// mesurer là vaut pour toutes les pages. `--gris-clair` y a tenu 2,8:1 sur 68
// textes sans qu'aucun contrôle ne le dise (WCAG 2.1 AA : 4,5:1).
const TEXTES = ['encre', 'gris', 'gris-clair', 'ardoise', 'ardoise-fonce', 'ambre', 'recette', 'depense']
const FONDS = ['papier', 'blanc', 'ardoise-pale', 'ambre-pale']
const CONTRASTE_MIN = 4.5

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contraste = (a, b) => {
  const [clair, sombre] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (clair + 0.05) / (sombre + 0.05)
}

// À côté de CE script, pas du répertoire courant : le build contrôlé peut être
// ailleurs (aperçu de l'atelier, essais), la palette est celle du dépôt.
const GABARIT = fileURLToPath(new URL('../src/routes/+layout.svelte', import.meta.url))
const jetons = Object.fromEntries(
  [...readFileSync(GABARIT, 'utf8').matchAll(/^\s*--([a-z-]+):\s*(#[0-9a-fA-F]{6});/gm)]
    .map((m) => [m[1], m[2]]))
const ternes = []
for (const nom of [...TEXTES, ...FONDS]) {
  if (!jetons[nom]) ternes.push(`--${nom} : jeton introuvable dans src/routes/+layout.svelte`)
}
if (!ternes.length) {
  for (const texte of TEXTES) for (const fond of FONDS) {
    const c = contraste(jetons[texte], jetons[fond])
    if (c < CONTRASTE_MIN) {
      ternes.push(`--${texte} ${jetons[texte]} sur --${fond} ${jetons[fond]} : ${c.toFixed(2)}:1`)
    }
  }
}
if (ternes.length) {
  console.error(`\n✖ ${ternes.length} couple(s) de jetons sous ${CONTRASTE_MIN}:1 :\n`)
  for (const t of ternes) console.error('  ' + t)
  console.error("\nFoncer la couleur de texte dans `:root` (src/routes/+layout.svelte) —")
  console.error("pas éclaircir le fond, et pas retirer le couple de cette liste.\n")
  process.exit(1)
}

console.log(`✓ ${pages.length} pages vérifiées : toutes livrent leur contenu dans le HTML.`)
console.log(`✓ contraste : ${TEXTES.length} couleurs de texte sur ${FONDS.length} fonds, toutes à ${CONTRASTE_MIN}:1 ou plus.`)
console.log(plancher !== null
  ? `✓ build entier : ${fiches} fiches pour ${plancher} annoncées par le manifeste, _app/immutable présent.`
  : `⚠ nombre de pages NON contrôlé : pas de manifeste lisible dans ${DONNEES} (snapshot `
    + "d'avant le manifeste, ou dépôt sans données).")
