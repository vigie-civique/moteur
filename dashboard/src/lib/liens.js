// Une adresse venue de la BASE devient un lien cliquable. L'API refuse depuis le
// 02/10/2026 une adresse saisie qui ne soit pas http(s) ; mais les adresses des
// collecteurs viennent de sites tiers, et une base déjà remplie garde ce qu'elle
// a. `javascript:…` dans un `href` est un script, pas une adresse : ce qui n'est
// pas une adresse ordinaire ne se clique pas.
const ORDINAIRE = /^(https?:\/\/|mailto:|tel:|\/(?!\/))/i

export function lienSur(adresse) {
  const a = typeof adresse === 'string' ? adresse.trim() : ''
  return ORDINAIRE.test(a) ? a : undefined
}
