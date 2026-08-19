// robots.txt, généré au build — et non plus servi comme fichier statique.
//
// Il l'était, avec l'adresse du sitemap écrite en dur. Une instance répliquée
// annonçait donc le sitemap de la commune d'origine : le 19/08/2026, Saillans
// et Brassac renvoyaient tous les deux les robots vers le site de Lasalle.
// `verifier_generique.py` ne l'avait pas vu parce qu'il inspecte le code, et
// que celui-là était un fichier de contenu.
//
// Toute adresse absolue dans ce site doit venir de SITE_URL, sans exception.
import { SITE_URL } from '$lib/instance.js'

export const prerender = true

export function GET() {
  const corps = [
    '# Ce site a vocation à être trouvé, cité et archivé : tout est indexable.',
    'User-agent: *',
    'Allow: /',
    '',
    // Sans SITE_URL renseigné, mieux vaut pas de ligne Sitemap qu'une ligne
    // relative : un sitemap doit être annoncé en absolu, et une valeur vide
    // ferait pointer les robots vers « /sitemap.xml » sur leur propre hôte.
    ...(SITE_URL ? [`Sitemap: ${SITE_URL}/sitemap.xml`] : []),
    '',
  ].join('\n')

  return new Response(corps, {
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  })
}
