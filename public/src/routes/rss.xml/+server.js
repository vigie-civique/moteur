import { COMMUNE_A, INSEE, SITE_NOM, SITE_URL } from '$lib/instance.js'
// Flux RSS des nouveautés — généré au build.
//
// C'est ce qui transforme un visiteur de passage en veilleur régulier, sans
// compte, sans newsletter et sans traceur : le lecteur s'abonne, le site
// n'apprend rien de lui.
//
// Le flux porte les changements de la DÉCISION PUBLIQUE, et rien d'autre.
// Sont donc exclus :
//   - l'agenda culturel (genre « vie »), consultable sur /vie-locale : il
//     noierait les délibérations sous les lotos et les vide-greniers ;
//   - les annonces BODACC (genre « légal »), qui relèvent de la vie des
//     entreprises et non de l'action publique — elles représentent 143 des
//     400 entrées du snapshot et rempliraient le flux à elles seules.
// Ces deux familles restent publiées sur le site ; elles n'ont simplement pas
// leur place dans un fil de vigie.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const MAX = 60

const echapper = (s) => (s || '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

const GENRES = {
  acte: 'Acte / décision',
  argent: 'Argent public',
  'marché': 'Marché public',
}

export function GET() {
  let d = { items: [] }
  try {
    d = JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', 'actualite.json'), 'utf8'))
  } catch { /* snapshot absent : flux vide plutôt que build cassé */ }

  const arreteLe = d.arrete_le || (d.genere_le || '').slice(0, 10)

  const items = (d.items || [])
    .filter((i) => GENRES[i.genre])
    // Le snapshot contient des événements à venir (annonces datées après
    // l'arrêt des données). Un flux annonce ce qui s'est produit, pas ce qui
    // est programmé : ils sortiront du flux quand ils auront eu lieu.
    .filter((i) => !arreteLe || (i.date || '') <= arreteLe)
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
    .slice(0, MAX)

  const dateRfc = (s) => {
    try { return new Date(s + 'T09:00:00Z').toUTCString() } catch { return new Date().toUTCString() }
  }

  const entrees = items.map((i) => {
    const lien = i.url || `${SITE_URL}/nouveautes`
    const desc = [
      GENRES[i.genre],
      i.categorie || null,
      i.montant ? `${i.montant} €` : null,
      i.corrige ? 'Information rectifiée — la donnée collectée est conservée à côté de la rectification.' : null,
    ].filter(Boolean).join(' · ')
    return `    <item>
      <title>${echapper(i.titre)}</title>
      <link>${echapper(lien)}</link>
      <guid isPermaLink="false">vigie-${INSEE}-${i.id ?? echapper(i.date + i.titre)}</guid>
      <pubDate>${dateRfc(i.date)}</pubDate>
      <category>${echapper(GENRES[i.genre])}</category>
      <description>${echapper(desc)}</description>
    </item>`
  }).join('\n')

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${SITE_NOM} — ce qui a changé</title>
    <link>${SITE_URL}/nouveautes</link>
    <atom:link href="${SITE_URL}/rss.xml" rel="self" type="application/rss+xml" />
    <description>Les décisions, marchés, flux financiers et changements de mandat ${COMMUNE_A} et dans son intercommunalité, d'après les documents publics. Agenda culturel exclu.</description>
    <language>fr</language>
    <lastBuildDate>${dateRfc(arreteLe)}</lastBuildDate>
${entrees}
  </channel>
</rss>
`
  return new Response(body, { headers: { 'content-type': 'application/rss+xml' } })
}
