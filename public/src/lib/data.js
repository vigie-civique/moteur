// Chargement des données statiques exportées par build_public_snapshot.py
// Servies depuis /data/ (public/static/data/). Aucun backend.
const BASE = '/data'

export async function loadJSON(name) {
  const res = await fetch(`${BASE}/${name}`)
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`)
  return res.json()
}

export const TYPE_LABELS = {
  person: 'Personne',
  business: 'Entreprise',
  association: 'Association',
  service: 'Service public',
  place: 'Lieu',
  property: 'Propriété',
}

export function euros(n) {
  if (n == null) return '—'
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)
}
