import { writable } from 'svelte/store'

export const currentUser = writable(null)

/**
 * Fetch authentifié vers /api — gère le refresh automatique du token d'accès.
 * Redirige vers /atelier/login si la session est expirée.
 */
export async function authFetch(path, options = {}) {
  const token = sessionStorage.getItem('atelier_access')
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...(token ? { 'X-Atelier-Session': token } : {}),
      // Un FormData pose sa propre frontière multipart, que seul le navigateur
      // sait calculer. Lui coller « application/json » d'office — ce que faisait
      // cette ligne pour tout corps non typé — rend le dépôt de document
      // illisible côté serveur, avec une erreur qui parle de JSON invalide.
      ...(options.body && !options.headers?.['Content-Type']
          && !(typeof FormData !== 'undefined' && options.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
    },
  })

  if (res.status === 401 && !options._rejoue) {
    if (await rafraichir()) return authFetch(path, { ...options, _rejoue: true })
    _clearSession()
    // Ne pas rediriger si on est déjà sur le login — sinon boucle de reload
    // infinie (le layout racine fetch /stats au mount, 401 → redirect → remount).
    if (typeof window !== 'undefined'
        && !window.location.pathname.startsWith('/atelier/login')) {
      window.location.href = '/atelier/login'
    }
    throw new Error('Session expirée')
  }

  return res
}

/**
 * Demande un jeton d'accès neuf. Le jeton de rafraîchissement (sept jours) vit
 * dans un cookie HttpOnly, posé par l'API à la connexion : le navigateur
 * l'envoie de lui-même, et aucun script de la page — celui-ci compris — ne peut
 * le lire. Il vivait dans `localStorage`, à la portée de la première injection.
 */
export async function rafraichir() {
  const rr = await fetch('/api/auth/refresh', { method: 'POST' })
  if (!rr.ok) return false
  sessionStorage.setItem('atelier_access', (await rr.json()).access_token)
  return true
}

/**
 * Réhydrate currentUser au chargement (le store est perdu au reload,
 * mais le token d'accès survit dans sessionStorage).
 */
export async function initAuth() {
  if (typeof window === 'undefined') return
  if (!sessionStorage.getItem('atelier_access')) return
  try {
    const r = await authFetch('/auth/me')
    if (r.ok) currentUser.set(await r.json())
  } catch {
    /* session expirée — authFetch a déjà redirigé */
  }
}

export async function logout() {
  const token = sessionStorage.getItem('atelier_access')
  // Toujours appelé, même sans jeton d'accès : le cookie de rafraîchissement
  // (sept jours) est révoqué et retiré par l'API, qui seule peut le lire.
  // Attendu avant d'effacer la session, pour que la révocation ait lieu.
  await fetch('/api/auth/logout', {
    method: 'POST',
    headers: token ? { 'X-Atelier-Session': token } : {},
  }).catch(() => {})
  _clearSession()
}

function _clearSession() {
  sessionStorage.removeItem('atelier_access')
  // Reliquat d'avant le 02/10/2026 : le jeton n'y est plus écrit, on l'en retire.
  localStorage.removeItem('atelier_refresh')
  currentUser.set(null)
}
