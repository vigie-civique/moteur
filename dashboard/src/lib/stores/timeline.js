import { writable } from 'svelte/store'

// null = toutes les années, number = filtrer sur cette année
export const timelineYear = writable(null)

// Mode : 'exact' (année seule) | 'cumulative' (jusqu'à l'année)
export const timelineMode = writable('cumulative')

// Plage globale détectée depuis les données chargées
export const timelineRange = writable({ min: 2000, max: new Date().getFullYear() })
