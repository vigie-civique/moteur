// Chiffres des cartes du hub, lus au build dans le snapshot : une carte qui
// annonce ce qu'elle contient donne envie de cliquer, et remplit la page avec
// de l'information plutôt qu'avec du vide.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const DATA_DIR = join(process.cwd(), 'static', 'data')
const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const stats = lire('stats.json')
  const ofgl = lire('ofgl.json', { ofgl: [] })
  const flows = lire('flows.json', [])
  const dvf = lire('dvf.json', [])
  const fiscalite = lire('fiscalite.json', {})

  const lignes = ofgl.ofgl || []
  const annee = lignes.reduce((max, l) => (l.year > max ? l.year : max), 0)
  const agregat = (nom) => lignes.find((l) => l.year === annee && l.agregat === nom)?.montant ?? null

  // Bénéficiaires distincts de l'argent public (hors demandes non acquises).
  const rows = Array.isArray(flows) ? flows : flows.flows || []
  const verses = rows.filter((f) => f.statut !== 'demande')
  const beneficiaires = new Set(verses.map((f) => f.to_id).filter(Boolean)).size
  const totalVerse = verses.reduce((s, f) => s + (f.amount || 0), 0)

  const transactions = Array.isArray(dvf) ? dvf : dvf.rows || dvf.dvf || []
  const annees = transactions.map((t) => (t.date || '').slice(0, 4)).filter(Boolean).sort()

  return {
    annee,
    recettes: agregat('Recettes de fonctionnement'),
    depenses: agregat('Dépenses de fonctionnement'),
    epargne: agregat('Épargne brute'),
    marches: stats.marches_rows ?? null,
    beneficiaires,
    totalVerse,
    dvf: transactions.length,
    dvfPeriode: annees.length ? `${annees[0]}–${annees[annees.length - 1]}` : null,
    // Communes réellement comparées dans /impots — compté sur le snapshot.
    // La carte annonçait « 7 communes comparées », vestige de l'ancien
    // ancien périmètre, plus étroit que celui de l'intercommunalité.
    communes: new Set((fiscalite.taux || []).map((t) => t.commune).filter(Boolean)).size || null,
  }
}
