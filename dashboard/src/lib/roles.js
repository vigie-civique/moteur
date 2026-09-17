// Rôles EMBOÎTÉS (arbitré le 17/09/2026) — le miroir de `api_auth.ROLES`.
// L'interface s'en sert pour ne pas proposer un geste que l'API refuserait ;
// le droit, lui, est tenu par l'API.
export const ROLES = ['contributor', 'validator', 'admin']

export const LIBELLE_ROLE = {
  contributor: 'Contributeur',
  validator: 'Validateur',
  admin: 'Administrateur',
}

export const DESCRIPTION_ROLE = {
  contributor: "Propose : corrige les fiches, ajoute des notes et des sites, saisit des données à confirmer. Ne rend rien publiable.",
  validator: "Tout ce que fait le contributeur, et tranche : confirme ou écarte ce qui part sur le site, voit les analyses.",
  admin: "Tout ce que fait le validateur, et invite des personnes, gère les comptes, publie le site.",
}

export function auMoins(user, role) {
  return !!user && ROLES.indexOf(user.role) >= ROLES.indexOf(role)
}

/** Le message d'une erreur d'API : `detail` est une chaîne ou `{ message, … }`. */
export function messageErreur(detail, defaut = 'Opération refusée.') {
  if (!detail) return defaut
  if (typeof detail === 'string') return detail
  return detail.message || defaut
}
