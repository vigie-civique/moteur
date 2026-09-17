// Les horodatages de la base sont écrits par SQLite (`datetime('now')`) : en
// UTC, SANS fuseau — « 2026-09-16 23:24:19 ». Découpés tels quels, ils
// affichaient « 16/09 23:24 » pour une modification faite le 17/09 à 01:24.
// Et `new Date()` lit cette forme en heure LOCALE : la même erreur, mieux cachée.
const SANS_FUSEAU = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

export function versDate(horodatage) {
  if (!horodatage) return null
  const s = String(horodatage).trim()
  const d = new Date(SANS_FUSEAU.test(s) ? s.replace(' ', 'T') + 'Z' : s)
  return isNaN(d) ? null : d
}

/** « 17/09/2026 01:24 », en heure du navigateur. */
export function heureLocale(horodatage) {
  const d = versDate(horodatage)
  if (!d) return horodatage || '—'
  return d.toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
