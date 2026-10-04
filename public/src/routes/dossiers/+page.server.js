// La liste des dossiers — cf. $lib/dossiers.server.js pour ce qui se publie.
import { lireDossiers } from '$lib/dossiers.server.js'
import { lireSujets } from '$lib/sujets.server.js'

export const prerender = true

export function load() {
  return {
    // Sans le corps ni les citations : la liste n'affiche que titre, chapeau
    // et date (58 Ko à Lasalle pour huit dossiers, citations comprises).
    dossiers: lireDossiers().map(({ slug, titre, chapeau, maj, statut }) =>
      ({ slug, titre, chapeau, maj, statut })),
    // Les sujets sans dossier dont cette instance publie des données : une
    // instance qui n'a rien écrit montre ce que les données en disent (lot 8).
    sujets: lireSujets().filter((s) => s.donnees && !s.dossier)
      .map(({ id, titre, sections }) => ({ id, titre, sections })),
  }
}
