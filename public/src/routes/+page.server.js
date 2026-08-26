// Accueil — PRÉRENDU. Les chiffres et les dernières nouveautés sont lus au
// build dans le snapshot, comme pour la fiche acteur : l'accueil ne doit pas
// afficher « Chargement… » ni un compteur à zéro le temps d'un fetch.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

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

  // ── La page de garde parle de la COMMUNE ────────────────────────────────
  // Elle mélangeait les deux assemblées sans le dire : le conseil municipal et
  // le conseil communautaire dans la même liste, sous le même titre. Ce ne sont
  // ni les mêmes élus, ni le même budget, ni le même bulletin de vote. Un site
  // communal doit d'abord répondre « qu'est-ce que MA commune a décidé », et
  // renvoyer vers l'intercommunalité — pas la lui servir mêlée.
  //
  // `portee` est posée par le snapshot (cf. `portee_evenement`). Un item sans
  // portée — snapshot d'avant ce champ — reste affiché : mieux vaut une page
  // de garde trop large qu'une page vide après un déploiement décalé.
  const communal = (i) => !i.portee || i.portee === 'commune'
  const recents = passes.filter((i) => GOUVERNANCE.has(i.genre)).filter(communal).slice(0, 6)
  const agenda = passes.filter((i) => i.genre === 'vie').filter(communal).slice(0, 4)
  const ailleurs = passes.filter(
    (i) => GOUVERNANCE.has(i.genre) && i.portee === 'intercommunalite').length

  // entity_index abrège les champs : `t` = type, `p` = portée.
  // `a` : 1 en activité, 0 cessée, ABSENT quand les registres se taisent.
  // Une fiche muette compte comme vivante — elle n'est pas donnée fermée. Ce
  // n'est pas la même chose que « active », et la page l'écrit.
  const vivant = (e) => e.a !== 0
  const parType = {}
  const parTypeCommune = {}
  let acteursCommune = 0
  let cesseesCommune = 0
  for (const e of index.entities || []) {
    parType[e.t] = (parType[e.t] || 0) + 1
    if (!e.p || e.p === 'commune') {
      if (vivant(e)) {
        parTypeCommune[e.t] = (parTypeCommune[e.t] || 0) + 1
        acteursCommune++
      } else cesseesCommune++
    }
  }
  // Ce qui produit, distingué de ce qui détient. 505 des « entreprises » de
  // Lasalle sont individuelles et 112 ont pour activité déclarée la gestion
  // immobilière : le chiffre unique décrivait un tissu économique qui n'existe
  // pas. Cf. `nature_entreprise` dans le constructeur de snapshot.
  const entreprisesVivantes = (index.entities || [])
    .filter((e) => e.t === 'business' && (!e.p || e.p === 'commune') && vivant(e))
  const parNature = {}
  for (const e of entreprisesVivantes) parNature[e.na || 'societe'] = (parNature[e.na || 'societe'] || 0) + 1
  const marches = lire('marches.json', { marches: [] }).marches || []
  const marchesCommune = marches.filter((m) => !m.portee || m.portee === 'commune').length
  const delibParPortee = stats.deliberations_public_par_portee || {}

  // ZÉRO EST UNE RÉPONSE. Un `||` de repli aurait retenu le total du snapshot
  // quand la commune n'a rien : les sept marchés publiés à Lasalle sont TOUS
  // ceux de l'intercommunalité, et la page de garde annonçait « 7 marchés »
  // comme s'ils étaient communaux. Ce zéro est le fait le plus intéressant de
  // la page — il dit que nos sources ne recensent aucun marché de la commune.
  // Le repli ne sert qu'à un snapshot ANTÉRIEUR à ce champ, et se décide sur
  // la présence du champ, jamais sur la valeur du compteur.
  const portees = (index.entities || []).some((e) => e.p)
  const marchesPortes = marches.some((m) => m.portee)

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
      acteurs: portees ? acteursCommune : (stats.entities_public ?? null),
      // `events_public` compte TOUT ce qui est publié — BODACC, agenda,
      // autorisations d'urbanisme comprises. L'afficher sous le mot
      // « décisions » faisait dire à l'accueil ce qu'aucune source ne dit.
      // Le compteur porte maintenant ce qu'il nomme.
      deliberations: delibParPortee.commune ?? stats.deliberations_public ?? null,
      evenements: stats.events_public ?? null,
      marches: marchesPortes ? marchesCommune : (stats.marches_rows ?? null),
      surCarte: stats.map_features_public ?? null,
      associations: portees ? (parTypeCommune.association ?? 0) : (parType.association ?? null),
      entreprises: portees ? (parTypeCommune.business ?? 0) : (parType.business ?? null),
      services: portees ? (parTypeCommune.service ?? 0) : (parType.service ?? null),
      // Ce que le chiffre unique cachait : la part qui produit, la part qui
      // détient, et ce qui a fermé.
      entreprisesProductives: (parNature.societe || 0) + (parNature.individuelle || 0),
      entreprisesPatrimoniales: parNature.patrimoniale || 0,
      cessees: cesseesCommune,
    },
    // Ce que l'intercommunalité décide POUR la commune. Annoncé à part, avec
    // son propre renvoi : ne pas le montrer serait cacher la moitié de ce qui
    // engage la commune ; le mêler serait mentir sur qui l'a voté.
    interco: {
      deliberations: delibParPortee.intercommunalite ?? 0,
      acteurs: (index.entities || []).filter((e) => e.p === 'intercommunalite').length,
      marches: marches.filter((m) => m.portee === 'intercommunalite').length,
      recents: ailleurs,
    },
    budget,
    recents,
    agenda,
    arreteLe: actualite.arrete_le || null,
  }
}
