// Les sujets (`sujets.json`, cf. scripts/snapshot/sujets.py) : quel dossier
// publié et quelles sections de données parlent de la même chose. C'est le
// pont qui manquait entre les dossiers et les pages de données.
import { lireJSON } from '$lib/donnees.server.js'
import { lireDossiers } from '$lib/dossiers.server.js'

/** Les sujets, chacun avec le titre de son dossier quand il en a un. */
export function lireSujets() {
  const titres = new Map(lireDossiers().map((d) => [d.slug, d.titre]))
  return ((lireJSON('sujets.json', {}) || {}).sujets || []).map((s) => ({
    ...s,
    dossier: s.dossier && titres.has(s.dossier) ? { slug: s.dossier, titre: titres.get(s.dossier) } : null,
  }))
}

/** Pour une page de données : ancre de section → dossier qui en parle. */
export function dossiersDeLaPage(page) {
  const sortie = {}
  for (const s of lireSujets()) {
    if (!s.dossier) continue
    for (const sec of s.sections) if (sec.page === page && sec.ancre) sortie[sec.ancre] = s.dossier
  }
  return sortie
}
