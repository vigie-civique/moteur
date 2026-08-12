// Accueil — PRÉRENDU. Les chiffres et les dernières nouveautés sont lus au
// build dans le snapshot, comme pour la fiche acteur : l'accueil ne doit pas
// afficher « Chargement… » ni un compteur à zéro le temps d'un fetch.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const DATA_DIR = join(process.cwd(), 'static', 'data')

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const stats = lire('stats.json')
  const actualite = lire('actualite.json', { items: [] })
  const index = lire('entity_index.json', { entities: [] })
  const ofgl = lire('ofgl.json', { ofgl: [] })

  // Le flux mélange l'agenda à venir et les actes passés : l'accueil ne montre
  // que ce qui est déjà arrivé, pour ne pas ouvrir sur un concert de septembre.
  const aujourdhui = new Date().toISOString().slice(0, 10)
  const passes = (actualite.items || [])
    .filter((i) => i.date && i.date <= aujourdhui)
    .sort((a, b) => b.date.localeCompare(a.date))

  // Deux flux, pas un. Trié par date seule, « ce qui vient de bouger » affichait
  // six annonces culturelles d'affilée — loto, bal, semaine bouliste — sur
  // l'accueil d'un site de contrôle de l'action publique : la vie associative
  // produit simplement plus d'entrées, et plus régulièrement, que le conseil
  // municipal. L'accueil ressemblait à un second site de mairie.
  //
  // La décision publique passe donc devant, et l'agenda garde sa place, plus
  // bas et nommé pour ce qu'il est. Les annonces BODACC (genre « légal »)
  // relèvent de la vie des entreprises : elles restent sur /nouveautes.
  const GOUVERNANCE = new Set(['acte', 'argent', 'marché'])
  const recents = passes.filter((i) => GOUVERNANCE.has(i.genre)).slice(0, 6)
  const agenda = passes.filter((i) => i.genre === 'vie').slice(0, 4)

  // entity_index abrège les champs : `t` = type.
  const parType = {}
  for (const e of index.entities || []) parType[e.t] = (parType[e.t] || 0) + 1

  // Dernier exercice OFGL publié : un budget daté vaut mieux qu'un montant nu.
  const lignes = ofgl.ofgl || []
  const annee = lignes.reduce((max, l) => (l.year > max ? l.year : max), 0)
  const agregat = (nom) =>
    lignes.find((l) => l.year === annee && l.agregat === nom)?.montant ?? null
  const budget = annee
    ? {
        annee,
        recettes: agregat('Recettes de fonctionnement'),
        depenses: agregat('Dépenses de fonctionnement'),
        habitants: lignes.find((l) => l.year === annee)?.population ?? null,
      }
    : null

  return {
    chiffres: {
      acteurs: stats.entities_public ?? null,
      decisions: stats.events_public ?? null,
      marches: stats.marches_rows ?? null,
      surCarte: stats.map_features_public ?? null,
      associations: parType.association ?? null,
      entreprises: parType.business ?? null,
      services: parType.service ?? null,
    },
    budget,
    recents,
    agenda,
    arreteLe: actualite.arrete_le || null,
  }
}
