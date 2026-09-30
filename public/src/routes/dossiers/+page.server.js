// La liste des dossiers — cf. $lib/dossiers.server.js pour ce qui se publie.
import { lireDossiers } from '$lib/dossiers.server.js'

export const prerender = true

export function load() {
  return { dossiers: lireDossiers().map(({ html, ...d }) => d) }
}
