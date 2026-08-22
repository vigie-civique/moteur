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
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

// Même répertoire que celui qu'`adapter-static` vient d'écrire : un aperçu
// figé (`VIGIE_BUILD_DIR`) doit être contrôlé, pas ignoré.
const BUILD = join(process.cwd(), process.env.VIGIE_BUILD_DIR || 'build')

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
const EXCEPTIONS = new Set(['carte.html', 'recherche.html'])

// Taille minimale de HTML rendu (hors <script>) en dessous de laquelle une page
// est forcément une coquille : l'en-tête et le pied de page pèsent déjà ~6 Ko.
const MINI_RENDU = 6500

const pages = []
;(function parcourir(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) parcourir(p)
    else if (f.endsWith('.html')) pages.push(p)
  }
})(BUILD)

const problemes = []

for (const p of pages) {
  const rel = p.slice(BUILD.length + 1)
  if (rel === '404.html' || EXCEPTIONS.has(rel)) continue

  const html = readFileSync(p, 'utf8')
  const rendu = html.replace(/<script[\s\S]*?<\/script>/g, '')

  if (/Chargement/i.test(rendu)) {
    problemes.push(`${rel} : contient « Chargement » — la page attend un fetch client`)
  }
  if (rendu.length < MINI_RENDU) {
    problemes.push(`${rel} : ${rendu.length} o de HTML rendu (< ${MINI_RENDU}) — page probablement vide`)
  }
}

if (problemes.length) {
  console.error(`\n✖ ${problemes.length} page(s) livrée(s) sans contenu :\n`)
  for (const p of problemes) console.error('  ' + p)
  console.error('\nLes données doivent être lues au build dans +page.server.js.')
  console.error('Gabarit : src/routes/marches/+page.server.js\n')
  process.exit(1)
}

console.log(`✓ ${pages.length} pages vérifiées : toutes livrent leur contenu dans le HTML.`)
