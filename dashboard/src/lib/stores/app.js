import { writable, derived } from 'svelte/store'

// Vue active : carte géographique ou graphe de relations
export const viewMode = writable('map') // 'map' | 'graph'

// Onglet actif du panneau latéral
export const activeTab = writable('sources') // 'sources' | 'entity' | 'reseau' | 'ia'

// Entité sélectionnée (clic sur point/nœud)
export const selectedEntity = writable(null)

// Couches actives sur la carte
export const activeLayers = writable({
  businesses:   true,
  associations: true,
  services:     true,
  places:       true,
  persons:      false,
  dvf:          false,
})

// Filtre statut entreprise
export const bizStatus = writable('') // '' | 'A' | 'F'

// Afficher les entités hors commune (hors bbox Lasalle)
export const showExternal = writable(false)

// Zoom carte vers des coordonnées (set par SidePanel, lu par MapView)
export const mapFocus = writable(null) // { lat, lng, zoom? }

// Résultats de recherche
export const searchResults = writable([])
export const searchQuery   = writable('')

// Stats globales
export const stats = writable(null)

// Feed / événements récents
export const feedItems = writable([])

// Entité détaillée (chargée depuis /api/entities/:id)
export const entityDetail = writable(null)

// Profondeur du sous-graphe (1-3)
export const graphDepth = writable(2)

// Filtre min-relations (graphe global)
export const minRelations = writable(2)

// Couleur par type d'entité : des jetons (lib/theme.css). En CSS ils
// s'écrivent tels quels ; pour d3 ou Leaflet, `couleur()` (lib/theme.js) les lit.
export const TYPE_COLORS = {
  business:    'var(--serie-bleu)',
  association: 'var(--serie-vert)',
  service:     'var(--serie-ambre)',
  place:       'var(--serie-violet)',
  person:      'var(--serie-rouge)',
}

export const TYPE_LABELS = {
  business:    'Entreprise',
  association: 'Association',
  service:     'Service public',
  place:       'Lieu / POI',
  person:      'Personne',
}
