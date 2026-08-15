// Les chiffres cités par la page « Méthode » sont lus dans le snapshot au
// build, jamais recopiés à la main.
//
// C'est la page qui décrit comment le site traite ses données : elle est la
// dernière où un compteur périmé serait acceptable. Un nombre écrit en dur y
// finirait par contredire la base, et c'est précisément ce genre d'écart qui a
// été trouvé le 12/08 sur les « niveaux de fiabilité ».
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

export function load() {
  let s = {}
  try {
    s = JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', 'stats.json'), 'utf8'))
  } catch { /* snapshot absent : la page s'affiche sans ses chiffres */ }

  const ex = s.exclusions || {}

  return {
    arreteLe: (s.generated_at || '').slice(0, 10) || null,
    // Écartés parce que la donnée n'a pas atteint le niveau requis pour être
    // publiée — à distinguer des exclusions de périmètre ou de vie privée.
    ecartes: {
      entites: ex.entities?.private_confidence ?? null,
      relations: ex.relations?.private_confidence ?? null,
      flux: ex.flows?.private_confidence ?? null,
    },
    // Répartition sur les trois axes, produite par build_public_snapshot.py.
    provenance: s.provenance || null,
    publies: {
      entites: s.entities_public ?? null,
      relations: s.relations_public ?? null,
      events: s.events_public ?? null,
      flux: s.flows_public ?? null,
    },
    // Dette de réplication, recomptée à chaque publication par le même contrôle
    // qui sert d'admission au kit (scripts/verifier_generique.py). La page
    // affirmait « changer de commune tient dans un seul fichier de
    // configuration » ; elle affiche maintenant la mesure, qui peut être
    // refaite par quiconque a le dépôt.
    replicabilite: s.replicabilite || null,
  }
}
