/**
 * API dynamique — appels vers FastAPI (port 8765, proxié via Vite).
 */
import { authFetch } from './stores/auth.js'

const BASE = '/api'

// Appels authentifiés (JWT atelier) — passent par authFetch (refresh auto).
async function getAuth(path) {
  const r = await authFetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function patchAuth(path, body) {
  const r = await authFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

// Toutes les requêtes API passent par authFetch (verrou global API — session 22) :
// le Bearer token est attaché quand il existe, et un 401 redirige vers le login.
async function get(path) {
  const r = await authFetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function getAdmin(path, adminKey) {
  const r = await authFetch(path, {
    headers: adminKey ? { 'x-admin-key': adminKey } : {},
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function post(path, body) {
  const r = await authFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function postAdmin(path, body, adminKey) {
  const r = await authFetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(adminKey ? { 'x-admin-key': adminKey } : {}),
    },
    body: JSON.stringify(body ?? {}),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function del(path) {
  const r = await authFetch(path, { method: 'DELETE' })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

function qs(params) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v !== null && v !== undefined) p.set(k, v)
  }
  const s = p.toString()
  return s ? '?' + s : ''
}

export const api = {
  stats: () => get('/stats'),
  // Entités structurantes résolues par leur nom côté serveur : la commune,
  // l'intercommunalité, l'État, la préfecture. À utiliser partout où un
  // identifiant d'entité serait autrement écrit en dur.
  pivots: () => get('/pivots'),

  entities: (params = {}) => get('/entities' + qs(params)),

  entity: (id) => get(`/entities/${id}`),

  search: (q, limit = 20) => get(`/search` + qs({ q, limit })),

  layer: (type, status = '', in_commune = true) =>
    get(`/layers/${type}` + qs({ status, in_commune })),

  graph: (entity_id, depth = 2, min_relations = 2, limit = 180) =>
    get('/graph' + qs({ entity_id, depth, min_relations, limit })),

  events: (type = '', limit = 50) => get('/events' + qs({ type, limit })),

  eventSearch: (q, limit = 50, civic = false) =>
    get('/events/search' + qs({ q, limit, civic })),

  dvf: (year = '', limit = 500) => get('/dvf' + qs({ year, limit })),

  flows: (year = '', type = '') => get('/flows' + qs({ year, type })),

  entitySynthesis: async (id) => {
    try { return await get(`/syntheses/${id}`) } catch { return null }
  },

  iaConfig: async () => {
    try { return await get('/ia/config') } catch { return { configuree: false } }
  },

  synthesize: async (topic, context = '') => {
    try {
      return await post('/synthesize', { topic, context })
    } catch {
      return { synthesis: null, error: 'Erreur lors de la synthèse.' }
    }
  },

  marches: (params = {}) => get('/marches' + qs(params)),

  budget: (year = '') => get('/budget' + qs({ year })),

  ofgl: (year = '', agregat = '') => get('/ofgl' + qs({ year, agregat })),

  candidates: (status = 'pending', signal = '') =>
    get('/candidates' + qs({ status, signal })),

  reviewCandidate: (cid, action, note = '') =>
    post(`/candidates/${cid}/review`, { action, note }),

  budgetAnnexe: (entity_id = null, year = null) =>
    get('/budget-annexe' + qs({ entity_id, year })),

  // Données importées (délibs / flux / marchés) — revue & annotation (atelier, JWT)
  donnees: (type, status = '', limit = 200, origine = '') =>
    getAuth('/atelier/donnees' + qs({ type, status, origine, limit })),

  annotate: (objectType, objectId, body) =>
    patchAuth(`/atelier/annotations/${objectType}/${objectId}`, body),

  // Contrat des corrections : quels champs l'API accepte de rectifier, par type.
  champsCorrigeables: () => getAuth('/atelier/champs-corrigeables'),

  // ─── Saisie manuelle ────────────────────────────────────────────────────
  // Ce que la collecte ne peut pas atteindre : le budget voté, les dotations
  // notifiées, une subvention lue dans un procès-verbal. La saisie n'écrit pas
  // en base directement — elle va dans config/saisies.json, que le collecteur
  // rejoue à chaque passage, et survit donc à une reconstruction de la base.
  saisiesChamps: () => getAuth('/atelier/saisies/champs'),

  saisies: () => getAuth('/atelier/saisies'),

  saisieCreer: (objet, valeurs, source, confidence = 'confirmed') =>
    post('/atelier/saisies', { objet, valeurs, source, confidence }),

  saisieRetirer: (id) => del(`/atelier/saisies/${id}`),

  // Documents archivés localement : une saisie s'y adosse, ou dit pourquoi
  // elle ne le peut pas.
  documents: (q = '', limit = 50) => getAuth('/atelier/documents' + qs({ q, limit })),

  documentDeposer: async (fichier, titre = '', url = '') => {
    const form = new FormData()
    form.append('fichier', fichier)
    if (titre) form.append('titre', titre)
    if (url) form.append('url', url)
    // Pas de Content-Type ici : le navigateur doit poser lui-même la frontière
    // multipart, et l'écraser à la main casse la lecture côté serveur.
    const r = await authFetch('/atelier/documents', { method: 'POST', body: form })
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
    return r.json()
  },

  documentUrl: (id) => `${BASE}/atelier/documents/${id}/fichier`,

  // Extraction assistée : le modèle PROPOSE des lignes lues dans un document.
  // Rien n'est écrit — les propositions pré-remplissent le formulaire, et
  // chacune porte la phrase du texte qui la justifie, vérifiée côté serveur.
  iaExtraire: (objet, { document_id = null, event_id = null }) =>
    post('/atelier/ia/extraire', { objet, document_id, event_id }),

  // ─── Décisions : le travail humain, exporté et repris ───────────────────
  // La base se reconstruit toute seule ; les arbitrages et les saisies, non.
  // ⚠ Un export peut nommer des personnes physiques : dépôt privé.
  decisionsEtat: () => getAuth('/atelier/decisions'),

  decisionsExporter: (sans_personnes = false) =>
    post('/atelier/decisions/exporter', { sans_personnes }),

  // `appliquer: false` par défaut — on regarde le rapport avant d'écrire.
  decisionsImporter: (appliquer = false, forcer = false) =>
    post('/atelier/decisions/importer', { appliquer, forcer }),

  publicSnapshotStatus: (adminKey) =>
    getAdmin('/admin/public-snapshot', adminKey),

  // Le geste unique d'avant : construit par-dessus ce qui est servi et
  // synchronise dans la foulée. Gardé pour les scripts de déploiement ; la page
  // Publication ne s'en sert plus, elle passe par le flux en deux temps.
  generatePublicSnapshot: (adminKey) =>
    postAdmin('/admin/public-snapshot/generate', {}, adminKey),

  // Publication en deux temps. `publicationEtat` est en lecture seule et ouvert
  // à tout l'atelier : savoir ce qui est en ligne n'est pas un droit d'admin.
  publicationEtat: (adminKey) =>
    getAdmin('/admin/publication', adminKey),

  publicationApercu: (adminKey) =>
    postAdmin('/admin/publication/apercu', {}, adminKey),

  publicationPublier: (adminKey) =>
    postAdmin('/admin/publication/publier', {}, adminKey),

  publicationServeurApercu: (action, adminKey) =>
    postAdmin('/admin/publication/apercu/serveur', { action }, adminKey),

  // Constater ce que le site public sert VRAIMENT : c'est le seul état que
  // l'atelier ne peut pas déduire de ses propres écritures.
  publicationVerifierEnLigne: (adminKey) =>
    postAdmin('/admin/publication/verifier-en-ligne', {}, adminKey),

  publicationRevenir: (adminKey) =>
    postAdmin('/admin/publication/revenir', {}, adminKey),

  publicationModifications: (adminKey) =>
    getAdmin('/admin/publication/modifications', adminKey),
}
