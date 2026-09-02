// Eau du robinet, cours d'eau, risques, ICPE, catastrophes naturelles.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

// Les étiquettes, dans l'ordre où elles se lisent, et la part de « passoires »
// au sens de la loi Climat et résilience (F et G).
const ETIQUETTES = ['A', 'B', 'C', 'D', 'E', 'F', 'G']

function dpeLu(d) {
  const agregats = d.dpe_agregats || []
  const couverture = d.dpe_couverture || []
  const existant = agregats.filter((a) => a.jeu === 'existant')
  const etiquettes = ETIQUETTES.map((lettre) => ({
    lettre,
    n: existant.find((a) => a.dimension === 'etiquette_dpe' && a.modalite === lettre)?.nombre || 0,
  }))
  const total = etiquettes.reduce((s, e) => s + e.n, 0)
  if (!total) return null
  const passoires = etiquettes.filter((e) => e.lettre === 'F' || e.lettre === 'G')
                              .reduce((s, e) => s + e.n, 0)
  const cp = couverture.find((c) => c.jeu === 'existant') || {}
  return {
    etiquettes, total,
    passoires, partPassoires: Math.round(1000 * passoires / total) / 10,
    // Ce que le compte NE VOIT PAS : les diagnostics du secteur qu'aucune
    // commune ne réclame, faute d'adresse reconnue. Sans ce chiffre, une part
    // calculée sur un parc amputé se lirait comme une part du parc entier.
    sansCommune: cp.sans_commune ?? null,
    secteur: cp.secteur_cp ?? null, codePostal: cp.code_postal || null,
    tertiaire: (couverture.find((c) => c.jeu === 'tertiaire') || {}).diagnostics || 0,
  }
}

export function load() {
  const d = lire('environnement.json', {})
  return {
    stations: d.eau_stations || [], series: d.eau_series || [],
    couverture: d.eau_couverture || [], risques: d.risques || [],
    icpe: d.icpe || [], catnat: d.catnat || [],
    // L'eau du ROBINET : prix du mètre cube, rendement du réseau, mode de
    // gestion. Une autre source et un autre sujet que les analyses de rivière
    // ci-dessus, et la page doit le dire au lieu de les ranger sous « Eau ».
    servicesEau: d.sispea_services || [], indicateursEau: d.sispea_indicateurs || [],
    // Le parc de logements, vu par les diagnostics de performance énergétique.
    // Des agrégats : aucune adresse n'a été collectée, donc aucune n'est ici.
    dpe: dpeLu(d),
  }
}
