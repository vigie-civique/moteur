// Rang hiérarchique d'une fonction élective, d'après le libellé du RNE
// (« 1er adjoint au Maire », « Conseiller municipal »).
// Partagé entre le tri au build (+page.server.js) et la mise en forme dans la
// page : deux définitions divergentes donneraient un ordre et un style
// incohérents.
export const rangFonction = (f) => {
  if (!f) return 50
  if (/^maire/i.test(f)) return 0
  const m = f.match(/^(\d+)\s*(?:er|ème|eme|e)?\s*adjoint/i)
  return m ? Number(m[1]) : 40
}

export const estAdjoint = (f) => /adjoint/i.test(f || '')
