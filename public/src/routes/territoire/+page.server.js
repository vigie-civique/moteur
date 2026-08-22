import { COMMUNE_DE, INSEE } from '$lib/instance.js'
// Données INSEE du territoire.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  // Seuls ces cinq champs sont lus par la page. Embarquer les lignes entières
  // (avec `dims` et `dataset`) faisait un payload d'hydratation de 1 Mo pour
  // 22 Ko affichés — la donnée serait bloquante au premier rendu.
  const insee = (lire('territoire.json', {}).insee || []).map(
    ({ insee, indicateur, libelle, annee, valeur }) =>
      ({ insee, indicateur, libelle, annee, valeur }))

  // Constat démographique. Le fichier porte les 15 communes de
  // l'intercommunalité : filtrer sur le code INSEE la commune est indispensable,
  // sans quoi on additionne des communes différentes — c'est l'erreur commise
  // en lisant ces données à la main le 12/08.
  const pop = insee
    .filter((r) => r.insee === INSEE && r.indicateur === 'POP' && r.valeur != null)
    .sort((a, b) => a.annee.localeCompare(b.annee))

  let constat = null
  if (pop.length > 2) {
    const premier = pop[0]
    const dernier = pop[pop.length - 1]
    const creux = pop.reduce((min, r) => (r.valeur < min.valeur ? r : min))
    constat = {
      premier, dernier, creux,
      // Une population revenue à son niveau de départ après un creux profond ne
      // raconte pas la même chose qu'une population stable : l'écart au creux
      // est le vrai fait.
      reprise: Math.round(100 * (dernier.valeur - creux.valeur) / creux.valeur),
      ecartTotal: Math.round(100 * (dernier.valeur - premier.valeur) / premier.valeur),
    }
  }

  return { insee, constat }
}
