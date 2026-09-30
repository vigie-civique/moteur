// Un dossier. Seuls les dossiers publiables ont une page : un brouillon n'a
// pas d'URL, pas même une 404 qui trahirait son existence.
import { error } from '@sveltejs/kit'
import { lireDossiers } from '$lib/dossiers.server.js'

export const prerender = true

export function entries() {
  return lireDossiers().map((d) => ({ slug: d.slug }))
}

export function load({ params }) {
  const dossier = lireDossiers().find((d) => d.slug === params.slug)
  if (!dossier) throw error(404, 'Dossier introuvable.')
  return { dossier }
}
