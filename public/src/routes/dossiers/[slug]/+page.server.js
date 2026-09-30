// Un dossier. Seuls les dossiers publiables ont une page : un brouillon n'a
// pas d'URL, pas même une 404 qui trahirait son existence.
import { error } from '@sveltejs/kit'
import { lireDossiers } from '$lib/dossiers.server.js'

// Sans dossier publiable, la route n'a aucune page à produire, et SvelteKit
// refuse un build où une route prégénérée n'en produit aucune — c'est ce qui a
// cassé la CI du 30/09, où aucune instance n'a de dossier. Elle n'est donc
// prégénérée que s'il y a quelque chose à prégénérer ; sinon, une URL de
// dossier tombe sur la 404 de secours, ce qui est exact.
export const prerender = lireDossiers().length > 0

export function entries() {
  return lireDossiers().map((d) => ({ slug: d.slug }))
}

export function load({ params }) {
  const dossier = lireDossiers().find((d) => d.slug === params.slug)
  if (!dossier) throw error(404, 'Dossier introuvable.')
  return { dossier }
}
