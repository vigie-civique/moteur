// Une séance — une page par séance publiée, relue ou non (décisions 4 et 5 de
// docs/refonte-du-contenu.md). L'adresse est le nom de sa feuille en clair :
// `/conseils/2026-05-28_conseil-municipal`.
//
// Rien de nouveau n'y est publié : ses délibérations sont celles
// d'`events.json`, regroupées par date et par assemblée.
import { error } from '@sveltejs/kit'
import { actesDe, lireSeances } from '$lib/seances.server.js'

// Sans séance publiée, la route n'a rien à prérendre — et SvelteKit refuse une
// route prérendable qui ne produit aucune page (cf. dossiers/[slug]).
export const prerender = (lireSeances().seances || []).length > 0

export function entries() {
  return (lireSeances().seances || []).map((s) => ({ seance: s.id }))
}

export function load({ params }) {
  const s = (lireSeances().seances || []).find((x) => x.id === params.seance)
  if (!s) throw error(404, 'Séance introuvable.')
  return { seance: s, actes: actesDe(s) }
}
