// Le tableau de bord de l'accueil : douze indicateurs, calculés au build.
//
// Chaque tuile porte un libellé, la dernière valeur, un mini-graphique et sa
// provenance, et mène à la page qui détaille. Rien n'est tracé dans le
// navigateur : les séries sortent d'ici, le SVG est écrit au prérendu.
//
// Trois règles tiennent toutes les tuiles :
//  - la COMMUNE seule. `territoire.json`, `fiscalite.json` et `urbanisme.json`
//    portent toutes les communes de l'intercommunalité : chaque lecture filtre
//    sur le code INSEE de l'instance ;
//  - une tuile sans donnée ne s'affiche pas (`null`), et une série de moins de
//    trois points ne se trace pas : la valeur reste, seule ;
//  - l'année en cours est partielle, et sa barre le montre (`partiel`).
import { estAttribue } from '$lib/marches.js'

const nombre = (n) => Math.round(n).toLocaleString('fr-FR')
const decimal = (n, d = 2) =>
  n.toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d })
const millions = (n) =>
  n >= 1e6 ? `${(n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} M€`
           : `${nombre(n / 1e3)} k€`
const s = (n) => (n > 1 ? 's' : '')
const tracable = (points) => (points.length >= 3 ? points : null)

/** Compte par année, sans trou : une année sans rien est une barre à zéro. */
function parAnnee(dates, anneeCourante, max = 10) {
  const comptes = {}
  for (const d of dates) {
    const a = Number(String(d || '').slice(0, 4))
    if (a > 1900 && a <= anneeCourante) comptes[a] = (comptes[a] || 0) + 1
  }
  const annees = Object.keys(comptes).map(Number)
  if (!annees.length) return []
  const fin = Math.max(...annees)
  const debut = Math.max(Math.min(...annees), fin - max + 1)
  const points = []
  for (let a = debut; a <= fin; a++) {
    points.push({ x: a, y: comptes[a] || 0, partiel: a === anneeCourante })
  }
  return points
}

/** La dernière année ENTIÈRE d'une série annuelle, à défaut la seule connue. */
const derniereEntiere = (points) =>
  [...points].reverse().find((p) => !p.partiel) || points.at(-1)

export function tableauDeBord({ lire, insee, epciCourt, aujourdhui, chiffres, interco,
                                sourceMarches, extraitsMarches }) {
  const anneeCourante = Number(aujourdhui.slice(0, 4))
  const tuiles = []

  // ── 1. Délibérations ────────────────────────────────────────────────────
  // Celles du conseil municipal. Les délibérations communautaires ne s'y
  // ajoutent pas : nommées à part, comme sur la tuile d'avant.
  {
    const events = lire('events.json', { events: [] }).events || []
    const points = parAnnee(
      events.filter((e) => e.type === 'deliberation').map((e) => e.date), anneeCourante)
    if (chiffres.deliberations != null) {
      tuiles.push({
        cle: 'deliberations', href: '/deliberations', libelle: 'Délibérations',
        valeur: nombre(chiffres.deliberations),
        note: points.length ? `municipales, ${points[0].x} à ${points.at(-1).x}` : 'municipales',
        aussi: interco?.deliberations ? `${epciCourt} : ${nombre(interco.deliberations)}` : null,
        graphe: tracable(points) && { type: 'barres', points },
      })
    }
  }

  // ── 2. Séances ──────────────────────────────────────────────────────────
  // Douze mois de conseils, une marque par séance : le conseil municipal en
  // haut, le conseil communautaire dessous. Une séance mise en clair est
  // pleine, les autres pâles.
  {
    const seances = lire('seances.json', {}).seances || []
    const fin = new Date(aujourdhui + 'T00:00:00')
    const debut = new Date(fin)
    debut.setFullYear(debut.getFullYear() - 1)
    const duree = fin - debut
    const recentes = seances
      .map((x) => ({ ...x, t: new Date(x.date + 'T00:00:00') }))
      .filter((x) => x.t > debut && x.t <= fin)
    const cm = recentes.filter((x) => x.code === 'cm')
    const cc = recentes.filter((x) => x.code === 'cc')
    if (recentes.length) {
      const enClair = recentes.filter((x) => x.en_clair).length
      tuiles.push({
        cle: 'seances', href: '/conseils', libelle: 'Séances du conseil',
        valeur: nombre(cm.length),
        note: `municipales, 12 derniers mois${enClair ? `, ${enClair} en clair` : ''}`,
        aussi: cc.length ? `${epciCourt} : ${nombre(cc.length)}` : null,
        graphe: {
          type: 'frise',
          lignes: [cm, cc].filter((l) => l.length).map((l) =>
            l.map((x) => ({ x: (x.t - debut) / duree, plein: Boolean(x.en_clair) }))),
        },
      })
    }
  }

  // ── 3. Recettes et dépenses de fonctionnement ───────────────────────────
  {
    const lignes = lire('ofgl.json', { ofgl: [] }).ofgl || []
    const serie = (agregat) => lignes
      .filter((l) => l.agregat === agregat && l.montant != null)
      .sort((a, b) => a.year - b.year)
      .map((l) => ({ x: l.year, y: l.montant }))
    const recettes = serie('Recettes de fonctionnement')
    const depenses = serie('Dépenses de fonctionnement')
    if (recettes.length) {
      const r = recettes.at(-1)
      const d = depenses.find((p) => p.x === r.x)
      tuiles.push({
        cle: 'budget', href: '/budgets', libelle: 'Recettes de fonctionnement',
        valeur: millions(r.y),
        note: `${r.x}, OFGL`,
        aussi: d ? `dépenses : ${millions(d.y)}` : null,
        graphe: tracable(recettes) && {
          type: 'courbe',
          series: [{ ton: 'recette', points: recettes },
                   depenses.length >= 3 && { ton: 'depense', points: depenses }].filter(Boolean),
        },
      })
    }
  }

  // ── 4. Taxe foncière ────────────────────────────────────────────────────
  // Le taux VOTÉ par la commune, pas le taux global payé (qui ajoute celui de
  // l'intercommunalité) : c'est celui dont le conseil municipal décide.
  {
    const taux = (lire('fiscalite.json', { taux: [] }).taux || [])
      .filter((t) => t.insee === insee && t.indicateur === 'TFB_VOTE' && t.taux != null)
      .sort((a, b) => a.annee - b.annee)
      .map((t) => ({ x: t.annee, y: t.taux }))
    if (taux.length) {
      const t = taux.at(-1)
      tuiles.push({
        cle: 'foncier-bati', href: '/impots', libelle: 'Taxe foncière',
        valeur: `${decimal(t.y)} %`,
        note: `taux voté par la commune, ${t.x}`,
        graphe: tracable(taux) && { type: 'courbe', depuisZero: true,
                                    series: [{ ton: 'ardoise', points: taux }] },
      })
    }
  }

  // ── 5. Marchés attribués ────────────────────────────────────────────────
  // Le compte et la raison de son zéro sont ceux de l'accueil d'avant
  // (`chiffres.marches`, `sourceMarches`, `extraitsMarches`) : rien n'est
  // recalculé ici, seules les barres s'ajoutent.
  if (chiffres.marches != null) {
    const marches = lire('marches.json', { marches: [] }).marches || []
    const points = parAnnee(
      marches.filter((m) => (!m.portee || m.portee === 'commune') && estAttribue(m))
        .map((m) => m.date_notif), anneeCourante)
    const n = chiffres.marches
    const raisons = []
    if (n === 0) {
      raisons.push(sourceMarches === 'absente' ? 'collecte pas encore lancée'
                                               : "rien n'est publié sous 40 000 € HT")
    }
    const lus = n === 0 && extraitsMarches?.cas === 'en_attente' ? extraitsMarches.enAttente : 0
    tuiles.push({
      cle: 'marches', href: '/marches',
      libelle: n > 1 ? 'Marchés attribués' : 'Marché attribué',
      valeur: nombre(n), vide: n === 0,
      raison: raisons[0] || null,
      // La formule est celle de /marches, et la CI la cherche sur l'accueil.
      note: lus ? `${nombre(lus)} lu${s(lus)} dans les procès-verbaux, qui ${lus > 1 ? 'attendent leur' : 'attend sa'} relecture`
          : n > 0 ? 'par la commune' : null,
      aussi: interco?.marches ? `${epciCourt} : ${nombre(interco.marches)}` : null,
      graphe: n > 0 && tracable(points) ? { type: 'barres', points } : null,
    })
  }

  // ── 6. Ventes foncières ─────────────────────────────────────────────────
  {
    const points = parAnnee((lire('dvf.json', { dvf: [] }).dvf || []).map((v) => v.date),
                            anneeCourante)
    if (points.length) {
      const p = derniereEntiere(points)
      tuiles.push({
        cle: 'ventes', href: '/urbanisme', libelle: `Vente${s(p.y)} immobilière${s(p.y)}`,
        valeur: nombre(p.y), note: `${p.x}, DVF`,
        graphe: tracable(points) && { type: 'barres', points },
      })
    }
  }

  // ── 7. Acteurs en activité ──────────────────────────────────────────────
  // Le même ensemble que l'annuaire (cf. +page.server.js) : la barre le
  // découpe par nature, sans rien y ajouter.
  if (chiffres.acteurs != null) {
    const parts = [
      { label: 'entreprises', n: chiffres.entreprises },
      { label: 'associations', n: chiffres.associations },
      { label: 'services publics', n: chiffres.services },
      { label: 'lieux', n: chiffres.lieux },
    ].filter((p) => p.n > 0)
    tuiles.push({
      cle: 'acteurs', href: '/acteurs-publics', libelle: 'Acteurs en activité',
      valeur: nombre(chiffres.acteurs),
      note: chiffres.associations ? `dont ${nombre(chiffres.associations)} associations` : null,
      graphe: parts.length > 1 ? { type: 'parts', parts } : null,
    })
  }

  // ── 8 et 9. Habitants, résidences secondaires ───────────────────────────
  {
    const lignes = (lire('territoire.json', { insee: [] }).insee || [])
      .filter((r) => r.insee === insee && r.valeur != null)
    const serie = (code) => lignes.filter((r) => r.indicateur === code)
      .sort((a, b) => String(a.annee).localeCompare(String(b.annee)))
      .map((r) => ({ x: Number(r.annee), y: r.valeur }))
    const pop = serie('POP')
    const legale = serie('POPREF_PMUN').at(-1) || pop.at(-1)
    if (legale) {
      tuiles.push({
        cle: 'habitants', href: '/territoire', libelle: 'Habitants',
        valeur: nombre(legale.y),
        note: pop.length > 1 ? `${pop[0].x} à ${pop.at(-1).x}, Insee` : `${legale.x}, Insee`,
        graphe: tracable(pop) && { type: 'courbe', depuisZero: true,
                                   series: [{ ton: 'ardoise', points: pop }] },
      })
    }
    const logements = serie('DWELLINGS')
    const part = serie('DWELLINGS_DW_SEC_DW_OCC')
      .map((p) => {
        const total = logements.find((l) => l.x === p.x)?.y
        return total ? { x: p.x, y: (100 * p.y) / total } : null
      })
      .filter(Boolean)
    if (part.length) {
      const p = part.at(-1)
      tuiles.push({
        cle: 'secondaires', href: '/territoire#logement', libelle: 'Résidences secondaires',
        valeur: `${nombre(p.y)} %`,
        note: `des logements, ${p.x}, Insee`,
        graphe: tracable(part) && { type: 'courbe', depuisZero: true,
                                    series: [{ ton: 'ardoise', points: part }] },
      })
    }
  }

  // ── 10. Prix de l'eau ───────────────────────────────────────────────────
  // Un service par courbe. Deux services peuvent desservir la même commune à
  // des prix différents (cf. /environnement) : la tuile donne alors les deux
  // bornes, jamais une moyenne que personne ne paie.
  {
    const env = lire('environnement.json', {})
    const series = (env.sispea_services || [])
      .filter((x) => x.competence === 'AEP')
      .map((x) => (env.sispea_indicateurs || [])
        .filter((i) => i.code_service === x.code_service && i.code === 'D102.0' && i.valeur != null)
        .sort((a, b) => a.annee - b.annee)
        .map((i) => ({ x: i.annee, y: i.valeur })))
      .filter((points) => points.length)
    if (series.length) {
      const derniers = series.map((points) => points.at(-1))
      const prix = derniers.map((p) => p.y).sort((a, b) => a - b)
      const annees = derniers.map((p) => p.x).sort()
      tuiles.push({
        cle: 'eau', href: '/environnement#eau-du-robinet', libelle: "Prix de l'eau",
        valeur: series.length > 1 ? `${decimal(prix[0])} à ${decimal(prix.at(-1))} €`
                                  : `${decimal(prix[0])} €`,
        note: `le m³ TTC, ${annees[0] === annees.at(-1) ? annees[0] : `${annees[0]} et ${annees.at(-1)}`}`
            + (series.length > 1 ? `, ${series.length} services` : ''),
        graphe: series.some((points) => points.length >= 3) && {
          type: 'courbe', depuisZero: true,
          series: series.map((points) => ({ ton: 'ardoise', points })),
        },
      })
    }
  }

  // ── 11. Permis et déclarations ──────────────────────────────────────────
  {
    const points = parAnnee(
      (lire('urbanisme.json', { autorisations: [] }).autorisations || [])
        .filter((a) => !a.insee || a.insee === insee).map((a) => a.date_depot),
      anneeCourante)
    // Le total de la période tracée, pas la dernière année : une commune de
    // cette taille dépose une poignée de demandes par an, et les dernières
    // années du fichier sont encore incomplètes.
    const total = points.reduce((t, p) => t + p.y, 0)
    if (total) {
      tuiles.push({
        cle: 'autorisations', href: '/urbanisme', libelle: "Autorisations d'urbanisme",
        valeur: nombre(total), note: `déposées de ${points[0].x} à ${points.at(-1).x}`,
        graphe: tracable(points) && { type: 'barres', points },
      })
    }
  }

  // ── 12. Actes avec leur pièce ───────────────────────────────────────────
  // Ce que le site a pu rattacher à un document : sa propre mesure, à côté de
  // celles de la commune.
  {
    const c = lire('couverture.json', {})
    if (c.part_avec_piece != null) {
      tuiles.push({
        cle: 'pieces', href: '/couverture', libelle: 'Actes avec leur pièce',
        valeur: `${nombre(c.part_avec_piece)} %`,
        note: c.actes_total ? `sur ${nombre(c.actes_total)} actes publiés` : null,
        graphe: { type: 'jauge', part: c.part_avec_piece / 100 },
      })
    }
  }

  return tuiles
}
