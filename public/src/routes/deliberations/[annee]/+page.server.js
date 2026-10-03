// Les actes d'un millésime — une page HTML statique par année.
// `entries()` + `load()` ne tournent qu'au build : on lit le disque avec
// `node:fs` sans rien embarquer dans le bundle client (même motif que
// entite/[id]/+page.server.js).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { error } from '@sveltejs/kit'
import { INSTITUTIONAL, instanceDe, anneeDe } from '$lib/actes.js'
import { DATA_DIR } from '$lib/donnees.server.js'

const lireActes = () => {
  try {
    const d = JSON.parse(readFileSync(join(DATA_DIR, 'events.json'), 'utf8'))
    return (d.events || []).filter((e) => INSTITUTIONAL[e.type])
  } catch { return [] }
}

// Absent sur un snapshot d'avant le 03/10/2026 : la page reste celle d'avant.
const lireLiens = () => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, 'liens.json'), 'utf8')) }
  catch { return { actes: {}, alias: {} } }
}

// Une base peut ne porter AUCUN acte d'assemblée : c'est le cas de tout dossier
// national, qui exclut par conception les collecteurs de procès-verbaux. La
// route n'a alors aucun millésime à produire, et `prerender = true` faisait
// échouer le build entier — « marked as prerenderable, but not prerendered ».
// Le contournement en place était pire que le défaut : la base de la CI
// amorçait une ÉLECTION comptée comme un acte du conseil, pour que cette route
// existe. C'est cette élection qui se retrouvait dans « 87 actes recensés ·
// 87 conseil municipal » sur le dossier de Lourdes.
export const prerender = lireActes().length > 0

/** Une page par millésime présent dans le snapshot, « sans-date » compris. */
export function entries() {
  return [...new Set(lireActes().map(anneeDe))].map((annee) => ({ annee }))
}

export function load({ params }) {
  const actes = lireActes()
  // Combien d'actes renvoient au même PDF : à Lasalle, 2 381 délibérations sur
  // 2 466 partagent le recueil ou le compte rendu de leur séance. Un lien vers
  // ce document n'ouvre pas « l'acte » — il ouvre la séance entière.
  const parPdf = new Map()
  for (const e of actes) if (e.pdf_url) parPdf.set(e.pdf_url, (parPdf.get(e.pdf_url) || 0) + 1)
  const items = actes
    .filter((e) => anneeDe(e) === params.annee)
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
    .map((e) => (e.pdf_url ? { ...e, pdf_partage: parPdf.get(e.pdf_url) } : e))

  if (!items.length) throw error(404, 'Aucun acte pour cette année.')

  // Vers le haut : les dossiers et séances en clair qui citent chaque acte
  // (`liens.json`, écrit par le snapshot — collectors/graphe.py). Un acte que
  // personne ne cite n'en reçoit rien, et la page n'affiche rien pour lui.
  const liens = lireLiens()
  for (const e of items) {
    const cite = e.cle && liens.actes?.[e.cle]
    if (cite?.length) e.cite = cite
  }
  // Les anciennes ancres `#a{id}` de CE millésime, pour un cycle : un lien
  // posé avant le 03/10/2026 retrouve l'acte sous sa clé datée.
  const ici = new Set(items.map((e) => e.ancre).filter(Boolean))
  const alias = Object.fromEntries(Object.entries(liens.alias || {}).filter(([, c]) => ici.has(c)))

  // Années voisines, pour naviguer de millésime en millésime sans repasser
  // par le sommaire.
  const annees = [...new Set(actes.map(anneeDe))]
    .sort((a, b) => (a === 'sans-date' ? 1 : b === 'sans-date' ? -1 : b.localeCompare(a)))
  const i = annees.indexOf(params.annee)

  return {
    annee: params.annee,
    items,
    nCM: items.filter((e) => instanceDe(e) === 'CM').length,
    nCC: items.filter((e) => instanceDe(e) === 'CC').length,
    precedente: annees[i + 1] ?? null,   // plus ancienne
    suivante: annees[i - 1] ?? null,     // plus récente
    annees,
    alias,
  }
}
