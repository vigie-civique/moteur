// Accueil — PRÉRENDU. Les chiffres et les dernières nouveautés sont lus au
// build dans le snapshot, comme pour la fiche acteur : l'accueil ne doit pas
// afficher « Chargement… » ni un compteur à zéro le temps d'un fetch.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'
import { estAttribue } from '$lib/marches.js'
import { TYPES_ACTEURS } from '$lib/actes.js'
import { etatSource, extraitsMarches } from '$lib/couverture.js'
import { lireDossiers } from '$lib/dossiers.server.js'
import { lireSujets } from '$lib/sujets.server.js'
import { tableauDeBord } from '$lib/tableau.server.js'
import { EPCI_COURT, INSEE } from '$lib/instance.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const stats = lire('stats.json')
  const actualite = lire('actualite.json', { items: [] })
  const index = lire('entity_index.json', { entities: [] })

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

  // ── Une séance n'est pas un acte de plus ────────────────────────────────
  // Elle est ce qui les rassemble. Trié par date seule, un conseil qui délibère
  // neuf fois le même jour prenait les SIX places de la page de garde et
  // pointait neuf fois vers le même PDF. Relevé le 15/09/2026 sur la séance du
  // 10 septembre : trois lignes « Délibération n° … » faute d'objet lu, une
  // ligne de tableau prise pour un titre — « COÛT TOTAL PRÉVISIONNEL (HT)
  // 401 906.00 € » — et la fiche de séance elle-même. Six liens, un document.
  //
  // La page de garde annonce donc la SÉANCE, son compte d'actes et les pièces
  // qui l'attestent. Le détail reste entier sur /deliberations et /nouveautes,
  // où il se lit acte par acte — c'est le bon endroit pour un titre qu'il faut
  // encore vérifier, pas la première ligne du site.
  //
  // ⚖️ Et une séance dont AUCUN acte n'a pu être lu ne tient pas cette place :
  // la section s'appelle « ce que la commune vient de décider », or cette
  // ligne-là ne le dit pas. Elle reste entière sur /deliberations et
  // /nouveautes — elle n'est pas effacée, elle n'est pas mise en avant.
  const ACTES_DE_SEANCE = new Set(['deliberation', 'deliberation_cc'])

  // ── Où mène une séance ─────────────────────────────────────────────────
  // Vers sa page (`/conseils/<date>_<assemblée>`), qui porte ses délibérations
  // et, si elle est relue, sa feuille en clair. Toutes menaient au sommaire de
  // /deliberations (632 Ko à Lasalle, toutes années confondues), y compris le
  // 10 septembre 2026 dont la feuille relue existait
  // (docs/refonte-du-contenu.md § 2.1). Un snapshot sans `seances.json` garde
  // le renvoi vers l'année.
  const ASSEMBLEE = { conseil_municipal: 'conseil-municipal', conseil_communautaire: 'conseil-communautaire' }
  const seances = (lire('seances.json', {}).seances) || []
  const pages = new Set(seances.map((s) => s.id))

  // ── Au conseil : la dernière séance de chaque assemblée ─────────────────
  // Une par assemblée, jamais deux de la même : la commune et
  // l'intercommunalité ne votent ni les mêmes actes ni avec les mêmes élus.
  // `seances.json` est trié du plus récent au plus ancien ; une séance datée
  // après l'arrêt des données n'a pas encore eu lieu.
  const dernieres = ['cm', 'cc']
    .map((code) => seances.find((s) => s.code === code && s.date <= aujourdhui))
    .filter(Boolean)
    .map(({ id, date, code, assemblee, nb_actes, en_clair }) =>
      ({ id, date, code, assemblee, nb_actes, en_clair: en_clair || null }))
  // Les années que couvrent les séances publiées : tant qu'il n'y en a qu'une,
  // le lien de l'accueil la nomme au lieu de promettre « toutes ».
  const anneesSeances = [...new Set(seances.map((s) => s.date.slice(0, 4)))].sort()
  const lienDeSeance = (i) => {
    const id = `${i.date}_${ASSEMBLEE[i.type]}`
    return pages.has(id) ? `/conseils/${id}` : `/deliberations/${i.date.slice(0, 4)}`
  }
  const recents = passes
    .filter((i) => GOUVERNANCE.has(i.genre))
    .filter(communal)
    .filter((i) => !ACTES_DE_SEANCE.has(i.type))
    .filter((i) => i.nb_actes == null || i.nb_actes > 0)
    .slice(0, 6)
    .map((i) => (i.nb_actes != null ? { ...i, lien: lienDeSeance(i) } : i))
  const agenda = passes.filter((i) => i.genre === 'vie').filter(communal).slice(0, 4)

  // ── Le prochain conseil ────────────────────────────────────────────────
  // Annoncé par sa convocation (heure, lieu, ordre du jour — cf.
  // collectors/convocation.py). La commune ne publie pas les siennes ; la
  // communauté de communes, si. Les deux assemblées sont montrées, nommées :
  // la séance de la CC engage aussi la commune. Le site est reconstruit chaque
  // jour : « à venir » est relu à chaque publication.
  const SEANCES = new Set(['conseil_municipal', 'conseil_communautaire'])
  const prochains = (actualite.items || [])
    .filter((i) => SEANCES.has(i.type) && i.date && i.date >= aujourdhui)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 2)
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
  // Le même ensemble que l'annuaire : sans les personnes. L'accueil comptait
  // 19 élus et agents dans ses « 713 acteurs », que /acteurs-publics ne
  // montre pas — le lecteur qui refaisait le chemin trouvait 694.
  for (const e of (index.entities || []).filter((e) => TYPES_ACTEURS.includes(e.t))) {
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
  // Le compteur de l'accueil dit « marché attribué » : il compte des
  // attributions, pas des avis (cf. `estAttribue`).
  const marchesCommune = marches
    .filter((m) => (!m.portee || m.portee === 'commune') && estAttribue(m)).length
  const marchesInterco = marches.filter((m) => m.portee === 'intercommunalite')
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

  const chiffres = {
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
    lieux: portees ? (parTypeCommune.place ?? 0) : (parType.place ?? null),
    // Ce que le chiffre unique cachait : la part qui produit, la part qui
    // détient, et ce qui a fermé.
    entreprisesProductives: (parNature.societe || 0) + (parNature.individuelle || 0),
    entreprisesPatrimoniales: parNature.patrimoniale || 0,
    cessees: cesseesCommune,
  }
  // Ce que l'intercommunalité décide POUR la commune. Annoncé à part, avec
  // son propre renvoi : ne pas le montrer serait cacher la moitié de ce qui
  // engage la commune ; le mêler serait mentir sur qui l'a voté.
  const interco = {
    deliberations: delibParPortee.intercommunalite ?? 0,
    acteurs: (index.entities || []).filter((e) => e.p === 'intercommunalite').length,
    marches: marchesInterco.filter(estAttribue).length,
    avis: marchesInterco.filter((m) => !estAttribue(m)).length,
    recents: ailleurs,
  }
  // Ce que vaut un zéro de marchés : une question non posée (collecte
  // absente) n'est pas un résultat (cf. $lib/couverture.js).
  const couverture = lire('couverture.json', {})
  const sourceMarches = etatSource(couverture, 'marches').etat
  const extraits = extraitsMarches(couverture, 'commune')

  return {
    prochains,
    dernieres,
    anneesSeances,
    // Trois dossiers publiés, sans leur corps : l'accueil n'en montre que le
    // titre et le chapeau. Un dossier « à développer » attend sur /dossiers.
    // Tirés au sort ICI, donc au build : la page est prérendue, le tirage
    // change à chaque publication et jamais sous les yeux du lecteur.
    dossiers: lireDossiers().filter((d) => d.statut !== 'a_developper')
      .map(({ slug, titre, chapeau }) => ({ slug, titre, chapeau, rang: Math.random() }))
      .sort((a, b) => a.rang - b.rang).slice(0, 3)
      .map(({ rang, ...d }) => d),
    // Sans dossier écrit, ce que les données disent déjà des mêmes sujets :
    // une instance neuve a un accueil qui part des sujets, sans rien à relire.
    sujets: lireSujets().filter((s) => s.donnees && !s.dossier)
      .map(({ titre, sections }) => ({ titre, lien: `${sections[0].page}${sections[0].ancre ? `#${sections[0].ancre}` : ''}` })),
    interco,
    // Le tableau de bord : douze indicateurs au plus, chacun avec sa série
    // et la page où il se détaille (cf. $lib/tableau.server.js).
    tableau: tableauDeBord({ lire, insee: INSEE, epciCourt: EPCI_COURT, aujourdhui, chiffres,
                             interco, sourceMarches, extraitsMarches: extraits }),
    recents,
    agenda,
    arreteLe: actualite.arrete_le || null,
  }
}
