// D'où le site lit ses données, en un seul endroit.
//
// Les pages sont prérendues : chaque `+page.server.js` lit le snapshot sur le
// disque au moment du build. Le chemin était écrit trente fois, toujours le
// même — `join(process.cwd(), 'static', 'data')` — et donc impossible à
// détourner sans toucher trente fichiers.
//
// `VIGIE_DATA_DIR` sert à l'aperçu de l'atelier : le site public s'y branche
// sur un snapshot BROUILLON, sans qu'aucun répertoire servi ne bouge. C'est ce
// qui permet à l'aperçu d'être le site lui-même — mêmes composants, mêmes
// gabarits, même feuille de style — et pas une imitation.
//
// Non définie, ce qui est le cas de tout build de production et de la CI, la
// variable ne change rien : `static/data`, comme avant.
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

export const DATA_DIR = process.env.VIGIE_DATA_DIR
  ? resolve(process.env.VIGIE_DATA_DIR)
  : join(process.cwd(), 'static', 'data')

/** Lit un fichier du snapshot. Absent ou illisible → `defaut`, jamais un build cassé. */
export function lireJSON(nom, defaut = null) {
  try {
    return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8'))
  } catch {
    return defaut
  }
}
