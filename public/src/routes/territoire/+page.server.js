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
  const fichier = lire('territoire.json', {})
  const lignes = fichier.insee || []

  // Seuls ces cinq champs sont lus par la page. Embarquer les lignes entières
  // (avec `dims` et `dataset`) faisait un payload d'hydratation de 1 Mo pour
  // 22 Ko affichés — la donnée serait bloquante au premier rendu.
  //
  // ⚠️ Une projection est une liste de champs tenue à la main : elle vieillit
  // en silence. Celle-ci a jeté `commune` pendant que la page affichait
  // `{v.commune}` — d'où treize « undefined » dans la comparaison des niveaux
  // de vie, dont onze servis en production. Le nom de commune n'est utile qu'à
  // cette comparaison : il est donc joint à `voisines` ci-dessous plutôt
  // qu'ajouté ici, où il coûterait 116 Ko d'hydratation pour douze lignes.
  const insee = lignes.map(
    ({ insee, indicateur, libelle, annee, valeur }) =>
      ({ insee, indicateur, libelle, annee, valeur }))

  // Constat démographique. Le fichier porte les communes de l'intercommunalité :
  // filtrer sur le code INSEE de la commune est indispensable, sans quoi on
  // additionne des communes différentes — c'est l'erreur commise en lisant ces
  // données à la main le 12/08.
  const pop = insee
    .filter((r) => r.insee === INSEE && r.indicateur === 'POP' && r.valeur != null)
    .sort((a, b) => a.annee.localeCompare(b.annee))

  let constat = null
  if (pop.length > 2) {
    const premier = pop[0]
    const dernier = pop[pop.length - 1]
    const creux = pop.reduce((min, r) => (r.valeur < min.valeur ? r : min))
    const ecart = dernier.valeur - premier.valeur
    const ecartTotal = Math.round(100 * ecart / premier.valeur)
    // Le RÉGIME de la courbe, calculé — et non une phrase écrite pour Lasalle.
    // « Le même nombre à deux près » et « revenue à son niveau de 1968 » étaient
    // en dur : à Montselgues (−24 %) c'était faux, et à Lourdes, dont le point
    // bas EST la dernière année, la page annonçait une reprise de 0 % après un
    // creux qui n'a pas eu lieu.
    const stable = Math.abs(ecart) <= 2 || Math.abs(ecartTotal) < 2
    const regime = stable ? 'stable'
      : creux.annee === dernier.annee ? 'baisse'
      : ecart > 0 ? 'hausse' : 'reprise'
    constat = {
      premier, dernier, creux, ecart, ecartTotal, regime,
      // Une population revenue à son niveau de départ après un creux profond ne
      // raconte pas la même chose qu'une population stable : l'écart au creux
      // est le vrai fait.
      reprise: Math.round(100 * (dernier.valeur - creux.valeur) / creux.valeur),
      // Un creux qui n'est ni le premier ni le dernier point : seul cas où
      // parler d'un « creux » a un sens.
      creuxInterne: creux.annee !== premier.annee && creux.annee !== dernier.annee,
    }
  }

  // Niveau de vie médian des communes voisines : douze lignes, dont le NOM est
  // l'essentiel. Calculé ici plutôt que dans la page — la page devrait sinon
  // reparcourir les 4 000 lignes projetées, où le nom n'est plus.
  //
  // Borné à l'année la plus récente : le fichier peut porter plusieurs
  // millésimes, et les comparer entre eux ferait passer un écart de date pour
  // un écart de richesse.
  const filo = lignes.filter((r) => r.indicateur === 'FILO_MED_SL' && r.valeur != null)
  const anneeFilo = filo.reduce((mx, r) => (r.annee > mx ? r.annee : mx), '')
  const voisines = filo
    .filter((r) => r.annee === anneeFilo)
    .map(({ insee, commune, annee, valeur }) => ({ insee, commune, annee, valeur }))
    .sort((a, b) => b.valeur - a.valeur)

  // ── Équipements (BPE) ──────────────────────────────────────────────────
  // Deux échelles, à ne jamais confondre : l'ÉTAT est communal, la TRAJECTOIRE
  // ne l'est pas. L'INSEE ne publie l'évolution qu'à partir de
  // l'intercommunalité — la page doit donc le dire, et le champ `geo_type` est
  // ce qui l'en empêche de l'oublier.
  const equipements = fichier.equipements || []
  const etatCommune = equipements
    .filter((e) => e.geo_type === 'COM' && e.insee !== null && e.niveau === 'type'
                   && e.nombre > 0)
    .sort((a, b) => b.nombre - a.nombre || (a.libelle || '').localeCompare(b.libelle || ''))
  const totalCommune = equipements.find(
    (e) => e.geo_type === 'COM' && e.niveau === 'total')?.nombre ?? null

  const evolution = equipements.filter((e) => e.geo_type === 'EPCI' && e.niveau === 'type')
  const anneesEpci = [...new Set(evolution.map((e) => e.annee))].sort()
  const epciNom = evolution[0]?.geo_nom || null
  let mouvements = []
  if (anneesEpci.length > 1) {
    const [debut, fin] = [anneesEpci[0], anneesEpci[anneesEpci.length - 1]]
    const par = new Map()
    for (const e of evolution) {
      const clef = e.code
      const l = par.get(clef) || { code: clef, libelle: e.libelle }
      if (e.annee === debut) l.debut = e.nombre
      if (e.annee === fin) l.fin = e.nombre
      par.set(clef, l)
    }
    mouvements = [...par.values()]
      .filter((l) => l.debut != null && l.fin != null && l.debut !== l.fin)
      .map((l) => ({ ...l, ecart: l.fin - l.debut }))
      .sort((a, b) => a.ecart - b.ecart)
    mouvements = { debut, fin, pertes: mouvements.filter((m) => m.ecart < 0).slice(0, 8),
                   gains: mouvements.filter((m) => m.ecart > 0).slice(-6).reverse() }
  }

  // ── Transport et dispositifs de l'État ─────────────────────────────────
  const aom = (fichier.mobilite_aom || [])[0] || null
  const arrets = fichier.mobilite_arrets || []
  const reseaux = [...new Map(
    arrets.map((a) => [a.reseau, arrets.filter((x) => x.reseau === a.reseau).length])
  ).entries()].map(([reseau, n]) => ({ reseau, n })).sort((a, b) => b.n - a.n)
  const dispositifs = fichier.dispositifs_etat || []

  return {
    insee, constat, voisines, anneeFilo, commune: COMMUNE_DE,
    equipements: { etat: etatCommune.slice(0, 24), total: totalCommune,
                   mouvements, epciNom, anneesEpci },
    mobilite: { aom, arrets: arrets.length, reseaux,
                horsCommune: fichier.mobilite_arrets_hors_commune ?? 0 },
    dispositifs,
  }
}
