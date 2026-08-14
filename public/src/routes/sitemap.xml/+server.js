// Plan du site, généré au build.
//
// Les pages ne contiennent plus « Chargement… » depuis la bascule des routes
// sur `+page.server.js` : elles valent donc d'être indexées et archivées.
// Le sitemap est ce qui rend les 1 800 fiches et les 12 millésimes d'actes
// atteignables autrement qu'en cliquant de proche en proche.
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { SITE_URL } from '$lib/instance.js'
import { INSTITUTIONAL, anneeDe } from '$lib/actes.js'

export const prerender = true

const DATA_DIR = join(process.cwd(), 'static', 'data')
const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

// Routes éditoriales, dans l'ordre d'importance décroissante. Les pages de
// navigation pure (hub) portent une priorité plus haute que les listes.
const PAGES = [
  ['/', 1.0], ['/qui-decide', 0.9], ['/argent', 0.9], ['/comprendre', 0.8],
  ['/methode', 0.8], ['/couverture', 0.7], ['/nouveautes', 0.8], ['/deliberations', 0.8],
  ['/marches', 0.7], ['/elus', 0.7], ['/budgets', 0.7], ['/finances', 0.7],
  ['/impots', 0.7], ['/elus-et-structures', 0.7], ['/elections', 0.7],
  ['/com-com', 0.7], ['/acteurs-publics', 0.6], ['/urbanisme', 0.6],
  ['/environnement', 0.6], ['/territoire', 0.6], ['/vie-locale', 0.5],
  ['/projets-approuves', 0.5], ['/carte', 0.5], ['/graphe', 0.5],
  ['/recherche', 0.5], ['/comprendre/budget', 0.6],
  ['/comprendre/intercommunalite', 0.6], ['/comprendre/mandats', 0.6],
  ['/contact', 0.4], ['/mentions-legales', 0.3],
]

export function GET() {
  // Date d'arrêt des données : le sitemap ne doit pas prétendre à une
  // fraîcheur que le snapshot n'a pas.
  const stats = lire('stats.json', {})
  const maj = (stats.generated_at || new Date().toISOString()).slice(0, 10)

  const urls = PAGES.map(([loc, prio]) => ({ loc, prio }))

  // Un millésime d'actes par page.
  const actes = (lire('events.json', { events: [] }).events || [])
    .filter((e) => INSTITUTIONAL[e.type])
  for (const a of [...new Set(actes.map(anneeDe))]) {
    urls.push({ loc: `/deliberations/${a}`, prio: 0.6 })
  }

  // Fiches acteurs : prérendues une par une, ce sont les pages de fond du site.
  try {
    for (const f of readdirSync(join(DATA_DIR, 'entite'))) {
      if (f.endsWith('.json')) urls.push({ loc: `/entite/${f.slice(0, -5)}`, prio: 0.5 })
    }
  } catch { /* pas de fiches : sitemap réduit aux pages éditoriales */ }

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(({ loc, prio }) => `  <url><loc>${SITE_URL}${loc}</loc><lastmod>${maj}</lastmod><priority>${prio}</priority></url>`).join('\n')}
</urlset>
`
  return new Response(body, { headers: { 'content-type': 'application/xml' } })
}
