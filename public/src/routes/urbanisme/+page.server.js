// Mutations foncières DVF. La carte Leaflet reste montée côté client
// (`onMount`) : c'est du rendu interactif, pas de la donnée.
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
  const d = lire('dvf.json', { dvf: [] })
  const dvf = d.dvf || []

  // Constat sur le marché du bâti — et surtout sur ce qu'on ne peut PAS en
  // conclure. Avec vingt à quarante ventes par an, la médiane saute de 630 à
  // 1 284 €/m² d'une année sur l'autre : c'est du bruit d'échantillon, pas un
  // mouvement de marché. Afficher la courbe sans le dire inviterait à lire une
  // tendance là où il n'y en a pas de mesurable.
  const bati = dvf.filter((t) => t.price_per_m2 && /maison|appartement/i.test(t.nature_bien || ''))
  const parAnnee = new Map()
  for (const t of bati) {
    const a = (t.date || '').slice(0, 4)
    if (!a) continue
    if (!parAnnee.has(a)) parAnnee.set(a, [])
    parAnnee.get(a).push(t.price_per_m2)
  }

  const mediane = (arr) => {
    const s = [...arr].sort((x, y) => x - y)
    const m = Math.floor(s.length / 2)
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
  }

  const annees = [...parAnnee.entries()]
    .map(([annee, vals]) => ({ annee, n: vals.length, mediane: Math.round(mediane(vals)) }))
    .sort((a, b) => a.annee.localeCompare(b.annee))

  const medianes = annees.map((a) => a.mediane)

  return {
    dvf,
    constat: annees.length > 1 ? {
      annees,
      ventes: bati.length,
      minEchantillon: Math.min(...annees.map((a) => a.n)),
      maxEchantillon: Math.max(...annees.map((a) => a.n)),
      basse: Math.min(...medianes),
      haute: Math.max(...medianes),
    } : null,
  }
}
