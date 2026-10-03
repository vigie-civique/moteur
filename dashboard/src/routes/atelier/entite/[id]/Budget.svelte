<script>
  import { cleLocale } from './brouillon.js'

  export let lignes = []
  export let chargement = false
  export let brouillon            // { ajouts, suppr }

  const vide = () => ({ year: new Date().getFullYear(), section: 'fonctionnement', sens: 'recette',
                        compte: '', libelle: '', montant: '', source: '' })
  let nouvelle = vide()

  function ajouter() {
    if (!nouvelle.libelle || !nouvelle.montant || !nouvelle.source) return
    brouillon.ajouts = [...brouillon.ajouts, { cle: cleLocale(), corps: { ...nouvelle } }]
    nouvelle = vide()
  }
  const basculerSuppr = id => brouillon.suppr = brouillon.suppr.includes(id)
    ? brouillon.suppr.filter(x => x !== id) : [...brouillon.suppr, id]
  const retirer = cle => brouillon.ajouts = brouillon.ajouts.filter(a => a.cle !== cle)
  const euros = v => (+v).toLocaleString('fr-FR', { minimumFractionDigits: 2 })
</script>

<section class="card">
  <h2>Budget annexe</h2>
  {#if chargement}
    <p class="muted">Chargement…</p>
  {:else if lignes.length || brouillon.ajouts.length}
    <table class="budget-table">
      <thead>
        <tr><th>Année</th><th>Section</th><th>Sens</th><th>Compte</th><th>Libellé</th><th class="num">Montant (€)</th><th>Source</th><th></th></tr>
      </thead>
      <tbody>
        {#each lignes as b (b.id)}
          <tr class:a-supprimer={brouillon.suppr.includes(b.id)}>
            <td>{b.year}</td>
            <td><span class="section-badge sec-{b.section}">{b.section}</span></td>
            <td><span class="sens-badge sens-{b.sens}">{b.sens}</span></td>
            <td class="muted">{b.compte ?? '—'}</td>
            <td>{b.libelle}</td>
            <td class="num" class:neg={b.montant < 0}>{euros(b.montant)} €</td>
            <td class="muted small">{b.source}</td>
            <td>
              {#if brouillon.suppr.includes(b.id)}
                <button class="lien-annuler" on:click={() => basculerSuppr(b.id)}>rétablir</button>
              {:else}
                <button class="icon-del" title="Supprimer" on:click={() => basculerSuppr(b.id)}>✕</button>
              {/if}
            </td>
          </tr>
        {/each}
        {#each brouillon.ajouts as a (a.cle)}
          {@const b = a.corps}
          <tr class="a-enregistrer">
            <td>{b.year}</td>
            <td><span class="section-badge sec-{b.section}">{b.section}</span></td>
            <td><span class="sens-badge sens-{b.sens}">{b.sens}</span></td>
            <td class="muted">{b.compte || '—'}</td>
            <td>{b.libelle} <span class="tag-attente">à enregistrer</span></td>
            <td class="num" class:neg={b.montant < 0}>{euros(b.montant)} €</td>
            <td class="muted small">{b.source}</td>
            <td><button class="lien-annuler" on:click={() => retirer(a.cle)}>retirer</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="muted">Aucune ligne de budget annexe.</p>
  {/if}

  <details class="add-budget">
    <summary>+ Ajouter une ligne</summary>
    <div class="budget-add-grid">
      <label>Année<input type="number" bind:value={nouvelle.year} min="2015" max="2035" /></label>
      <label>Section
        <select bind:value={nouvelle.section}>
          <option value="fonctionnement">fonctionnement</option>
          <option value="investissement">investissement</option>
          <option value="dette">dette</option>
        </select>
      </label>
      <label>Sens
        <select bind:value={nouvelle.sens}>
          <option value="recette">recette</option>
          <option value="depense">dépense</option>
          <option value="solde">solde</option>
        </select>
      </label>
      <label>Compte M57<input bind:value={nouvelle.compte} placeholder="64, 74…" /></label>
      <label class="col2">Libellé<input bind:value={nouvelle.libelle} placeholder="Charges de personnel…" /></label>
      <label>Montant (€)<input type="number" step="0.01" bind:value={nouvelle.montant} placeholder="44000.00" /></label>
      <label class="col2">Source<input bind:value={nouvelle.source} placeholder="CM 27/04/2026, DGFiP…" /></label>
      <div class="col2">
        <button class="btn-add-small" on:click={ajouter}
                disabled={!nouvelle.libelle || !nouvelle.montant || !nouvelle.source}>
          + Ajouter à la fiche
        </button>
      </div>
    </div>
  </details>
</section>

<style>
  .budget-table { width: 100%; border-collapse: collapse; font-size: .78rem; margin-bottom: .75rem; }
  .budget-table th {
    text-align: left; color: var(--texte-doux); font-weight: 600;
    border-bottom: 1px solid var(--bordure); padding: .3rem .4rem;
  }
  .budget-table td { padding: .28rem .4rem; border-bottom: 1px solid var(--bordure-douce); }
  .budget-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .budget-table .neg { color: var(--danger); }
  .budget-table .small { font-size: .7rem; }

  .section-badge, .sens-badge { font-size: .68rem; padding: 1px 5px; border-radius: 3px; font-weight: 600; }
  .sec-fonctionnement { background: var(--info-doux); color: var(--info); }
  .sec-investissement { background: var(--succes-doux); color: var(--succes); }
  .sec-dette          { background: var(--danger-doux); color: var(--danger-texte); }
  .sens-recette { background: var(--succes-bordure); color: var(--succes-texte); }
  .sens-depense { background: var(--danger-bordure); color: var(--danger-texte); }
  .sens-solde   { background: var(--surface-2); color: var(--texte-2); }

  .add-budget summary {
    cursor: pointer; color: var(--lien); font-size: .8rem; font-weight: 600;
    padding: .4rem 0; list-style: none; user-select: none;
  }
  .add-budget summary::-webkit-details-marker { display: none; }
  .budget-add-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem .75rem; margin-top: .6rem; }
  .icon-del { background: none; border: none; color: var(--danger); cursor: pointer; font-size: .8rem; padding: 2px 4px; }
  .icon-del:hover { color: var(--danger); }
</style>
