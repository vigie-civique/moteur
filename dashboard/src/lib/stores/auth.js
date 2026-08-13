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
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.body && !options.headers?.['Content-Type']
        ? { 'Content-Type': 'application/json' }
        : {}),
    },
  })

  if (res.status === 401) {
    const refresh = localStorage.getItem('atelier_refresh')
    if (refresh) {
      const rr = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
      if (rr.ok) {
        const data = await rr.json()
        sessionStorage.setItem('atelier_access', data.access_token)
        return authFetch(path, options)
      }
    }
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
  if (token) {
    fetch('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {})
  }
  _clearSession()
}

function _clearSession() {
  sessionStorage.removeItem('atelier_access')
  localStorage.removeItem('atelier_refresh')
  currentUser.set(null)
}
