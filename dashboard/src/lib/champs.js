import { VERDICT } from './axes.js'

// Libellés des champs, pour l'historique, le conflit et le journal : « validation_status »
// ne dit rien à qui corrige une fiche.
export const LIBELLES = {
    name: 'Nom complet', short_name: 'Nom court', address: 'Adresse',
    confidence: 'Fiabilité de la source', validation_status: 'Statut (avant le 21/09)',
    responsible: 'Responsable', firstname: 'Prénom', lastname: 'Nom',
    birth_year: 'Année de naissance', birth_month: 'Mois de naissance', gender: 'Genre',
    naf_code: 'Code NAF', naf_label: 'Activité', legal_form: 'Forme juridique',
    biz_status: 'Statut', capital: 'Capital', employees_range: 'Effectif',
    biz_creation: 'Date de création', closing_date: 'Date de fermeture',
    rna_id: 'N° RNA', asso_object: 'Objet social', asso_status: 'Statut',
    asso_creation: 'Date de création', dissolution_date: 'Date de dissolution',
    osm_category: 'Catégorie OSM', osm_value: 'Valeur OSM', svc_category: 'Catégorie',
    operator: 'Opérateur', opening_hours: 'Horaires',
    lat: 'Latitude', lng: 'Longitude',
}


// Une décision entre au journal sous « entity/<id> », avec avant et après en
// JSON ({statut, note…}) : illisible tel quel dans l'historique d'une fiche.
const DECISION = /^(entity|relation|deliberation|flow|marche)\/\d+$/

export function champLisible(champ) {
    if (DECISION.test(champ ?? '')) return 'Verdict'
    return LIBELLES[champ] ?? champ
}

export function valeurLisible(champ, valeur) {
    if (!DECISION.test(champ ?? '') || !valeur) return valeur
    try {
        const d = JSON.parse(valeur)
        const verdict = VERDICT[d.statut]?.libelle ?? d.statut ?? '—'
        return d.note ? `${verdict} — « ${d.note} »` : verdict
    } catch { return valeur }
}
