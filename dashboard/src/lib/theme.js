// Thème de l'atelier : Système (par défaut), Clair ou Sombre.
//
// Le choix pose `data-theme="light|dark"` sur <html> ; sans choix, c'est
// `prefers-color-scheme` qui décide (lib/theme.css). Il est relu avant le
// premier rendu par static/theme.js — un fichier, pas un script en ligne :
// la CSP de l'atelier n'accepte que les scripts signés ou servis par l'atelier
// lui-même (svelte.config.js, kit.csp).
import { writable, derived } from 'svelte/store'

export const CLE = 'atelier-theme'
export const CHOIX = [
  { cle: 'system', libelle: 'Système' },
  { cle: 'light',  libelle: 'Clair' },
  { cle: 'dark',   libelle: 'Sombre' },
]

// localStorage peut manquer ou lever (navigation privée, données bloquées) :
// l'atelier s'affiche alors selon le système, sans rien mémoriser.
function lire() {
  try {
    const v = localStorage.getItem(CLE)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch { return 'system' }
}

function ecrire(v) {
  try {
    if (v === 'system') localStorage.removeItem(CLE)
    else localStorage.setItem(CLE, v)
  } catch {}
}

const navigateur = typeof window !== 'undefined'

export const choix = writable(navigateur ? lire() : 'system')

const prefereClair = writable(
  navigateur && window.matchMedia?.('(prefers-color-scheme: light)').matches)
if (navigateur && window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: light)')
    .addEventListener?.('change', e => prefereClair.set(e.matches))
}

// Le thème réellement affiché : ce que redessinent les graphiques.
export const themeEffectif = derived([choix, prefereClair],
  ([$c, $clair]) => $c === 'system' ? ($clair ? 'light' : 'dark') : $c)

export function choisir(v) {
  ecrire(v)
  choix.set(v)
}

if (navigateur) {
  choix.subscribe(v => {
    const html = document.documentElement
    if (v === 'system') html.removeAttribute('data-theme')
    else html.setAttribute('data-theme', v)
  })
}

// Valeur courante d'un jeton, pour ce qui ne lit pas le CSS : attributs SVG
// posés par d3, options de Leaflet. Accepte '--texte' ou 'var(--texte)'.
export function couleur(jeton) {
  if (!navigateur || !jeton) return ''
  const nom = jeton.startsWith('var(') ? jeton.slice(4, -1).trim() : jeton
  return getComputedStyle(document.documentElement).getPropertyValue(nom).trim()
}
