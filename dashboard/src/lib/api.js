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
  donnees: (type, status = '', limit = 200) =>
    getAuth('/atelier/donnees' + qs({ type, status, limit })),

  annotate: (objectType, objectId, body) =>
    patchAuth(`/atelier/annotations/${objectType}/${objectId}`, body),

  // Contrat des corrections : quels champs l'API accepte de rectifier, par type.
  champsCorrigeables: () => getAuth('/atelier/champs-corrigeables'),

  publicSnapshotStatus: (adminKey) =>
    getAdmin('/admin/public-snapshot', adminKey),

  generatePublicSnapshot: (adminKey) =>
    postAdmin('/admin/public-snapshot/generate', {}, adminKey),
}
