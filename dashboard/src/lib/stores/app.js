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

// Thème couleurs par type d'entité
export const TYPE_COLORS = {
  business:    '#3b82f6',
  association: '#10b981',
  service:     '#f59e0b',
  place:       '#8b5cf6',
  person:      '#ef4444',
}

export const TYPE_LABELS = {
  business:    'Entreprise',
  association: 'Association',
  service:     'Service public',
  place:       'Lieu / POI',
  person:      'Personne',
}
