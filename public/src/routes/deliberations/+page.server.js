// Index des actes institutionnels : un millésime par page.
//
// La page unique embarquait les 592 actes complets — 586 Ko de HTML, dont
// 271 Ko de payload d'hydratation, pour une liste que personne ne déroule
// jusqu'à 2016. Le découpage par année donne aussi à chaque millésime une URL
// stable, citable et archivable, ce qui est le point d'un site de vigie.
//
// Cette page-ci ne porte que le sommaire et un index compact des titres (~57 Ko)
// pour que la recherche reste transverse aux années — c'était la seule chose que
// le découpage faisait perdre.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { INSTITUTIONAL, anneeDe } from '$lib/actes.js'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  let d = { events: [] }
  try {
    d = JSON.parse(readFileSync(join(DATA_DIR, 'events.json'), 'utf8'))
  } catch { /* snapshot absent : page vide plutôt que build cassé */ }

  const actes = (d.events || []).filter((e) => INSTITUTIONAL[e.type])

  const parAnnee = new Map()
  for (const e of actes) {
    const a = anneeDe(e)
    if (!parAnnee.has(a)) parAnnee.set(a, { annee: a, total: 0, cm: 0, cc: 0 })
    const g = parAnnee.get(a)
    g.total++
    if (INSTITUTIONAL[e.type].instance === 'CM') g.cm++
    else g.cc++
  }

  // Années récentes d'abord ; « sans-date » en dernier plutôt qu'en tête, où le
  // tri alphabétique la placerait.
  const annees = [...parAnnee.values()].sort((a, b) =>
    a.annee === 'sans-date' ? 1 : b.annee === 'sans-date' ? -1 : b.annee.localeCompare(a.annee))

  // Index de recherche : strictement ce qu'affiche une ligne de résultat.
  const index = actes.map((e) => ({
    id: e.id,
    date: e.date || null,
    titre: e.title || '',
    annee: anneeDe(e),
    instance: INSTITUTIONAL[e.type].instance,
    label: INSTITUTIONAL[e.type].label,
  })).sort((a, b) => (b.date || '').localeCompare(a.date || ''))

  // Constat sur les votes.
  //
  // Attention au piège : `vote.unanimite` n'est vrai que lorsque le compte rendu
  // emploie le mot « unanimité ». Beaucoup d'actes portent un décompte (13 pour,
  // 0 contre, 0 abstention) sans ce mot : les compter comme « divisés » ferait
  // passer 104 délibérations pour contestées alors qu'aucune ne l'est. Un vote
  // n'est divisé que s'il y a au moins un contre ou une abstention.
  const divise = (v) => Boolean(v && (v.contre || v.abstention))
  const avecVote = actes.filter((e) => e.vote)
  const divises = avecVote.filter((e) => divise(e.vote))

  const anneeCourante = new Date().toISOString().slice(0, 4)

  return {
    annees,
    index,
    total: actes.length,
    nCM: actes.filter((e) => INSTITUTIONAL[e.type].instance === 'CM').length,
    nCC: actes.filter((e) => INSTITUTIONAL[e.type].instance === 'CC').length,
    anneeCourante,
    nCourante: parAnnee.get(anneeCourante)?.total ?? 0,
    votes: avecVote.length ? {
      connus: avecVote.length,
      sansOpposition: avecVote.length - divises.length,
      divises: divises.length,
      // Les rares actes qui ont fait débat, remontés plutôt que noyés : c'est
      // sur eux qu'un conseil municipal se lit.
      exemples: divises
        .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
        .slice(0, 5)
        .map((e) => ({
          id: e.id, date: e.date, titre: e.title,
          annee: anneeDe(e), vote: e.vote,
        })),
    } : null,
  }
}
