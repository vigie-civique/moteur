// Budgets votés et comptes administratifs.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR, lireJSON } from '$lib/donnees.server.js'
import { etatSource } from '$lib/couverture.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  return {
    budgetVote: lire('budget_vote.json', {}),
    budget: lire('budget.json', {}),
    ofgl: lire('ofgl.json', { ofgl: [] }),
    // Le budget VOTÉ se lit dans les comptes rendus du conseil : un dossier
    // national ne les collecte pas. Sans le dire, la page paraît simplement
    // n'avoir que du réalisé.
    sourceVote: etatSource(lireJSON('couverture.json', {}), 'budget_vote'),
  }
}
