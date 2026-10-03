<script>
  import { lienSur } from '$lib/liens.js'
  import { cleLocale } from './brouillon.js'

  export let sites = []
  export let tranche = false
  export let brouillon            // { ajouts, statuts: {id: statut}, suppr }

  const LIBELLE = { validated: 'validé', rejected: 'rejeté' }
  let url = ''

  function ajouter() {
    if (!url.trim()) return
    brouillon.ajouts = [...brouillon.ajouts, { cle: cleLocale(), corps: { url: url.trim() } }]
    url = ''
  }

  function trancher(w, statut) {
    const { [w.id]: _, ...autres } = brouillon.statuts
    brouillon.statuts = statut === w.status ? autres : { ...autres, [w.id]: statut }
  }

  const basculerSuppr = id => brouillon.suppr = brouillon.suppr.includes(id)
    ? brouillon.suppr.filter(x => x !== id) : [...brouillon.suppr, id]
  const retirer = cle => brouillon.ajouts = brouillon.ajouts.filter(a => a.cle !== cle)
</script>

<section class="card">
  <h2>Sites web <span class="count-badge">{sites.length}</span></h2>

  {#if sites.length || brouillon.ajouts.length}
    <ul class="web-list">
      {#each sites as w (w.id)}
        {@const statut = brouillon.statuts[w.id] ?? w.status}
        {@const supprime = brouillon.suppr.includes(w.id)}
        <li class="web-item" class:validated={statut==='validated'} class:rejected={statut==='rejected' && !brouillon.statuts[w.id]}
            class:a-supprimer={supprime} class:a-modifier={brouillon.statuts[w.id]}>
          <span class="web-status-dot web-{statut}" title={statut}></span>
          <a href={lienSur(w.url)} target="_blank" rel="noopener" class="web-url">{w.url}</a>
          <span class="web-meta">{w.found_by} {w.score != null ? `(${w.score.toFixed(2)})` : ''}</span>
          {#if supprime}
            <span class="tag-attente">supprimé à l'enregistrement</span>
            <button class="lien-annuler" on:click={() => basculerSuppr(w.id)}>rétablir</button>
          {:else if brouillon.statuts[w.id]}
            <span class="tag-attente">{LIBELLE[statut] ?? statut}, à enregistrer</span>
            <button class="lien-annuler" on:click={() => trancher(w, w.status)}>annuler</button>
          {/if}
          <div class="web-actions">
            {#if tranche && !supprime}
              {#if statut !== 'validated'}
                <button class="web-btn web-validate" on:click={() => trancher(w, 'validated')} title="Valider">✓</button>
              {/if}
              {#if statut !== 'rejected'}
                <button class="web-btn web-reject" on:click={() => trancher(w, 'rejected')} title="Rejeter">✕</button>
              {/if}
              <button class="web-btn web-del" on:click={() => basculerSuppr(w.id)} title="Supprimer">🗑</button>
            {/if}
          </div>
        </li>
      {/each}
      {#each brouillon.ajouts as a (a.cle)}
        <li class="web-item a-enregistrer">
          <span class="web-status-dot web-candidate"></span>
          <span class="web-url">{a.corps.url}</span>
          <span class="tag-attente">à enregistrer</span>
          <button class="lien-annuler" on:click={() => retirer(a.cle)}>retirer</button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">Aucune URL connue.</p>
  {/if}

  <div class="add-web">
    <input bind:value={url} placeholder="https://…" class="web-input" />
    <button class="btn-add-small" on:click={ajouter} disabled={!url.trim()}>+ Ajouter à la fiche</button>
  </div>
</section>

<style>
  .web-list { list-style: none; display: flex; flex-direction: column; gap: .35rem; margin-bottom: .6rem; }
  .web-item { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; font-size: .78rem; padding: .3rem .4rem; border-radius: 5px; background: #0f172a; }
  .web-item.validated { border-left: 3px solid #22c55e; }
  .web-item.rejected  { opacity: .45; }
  .web-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .web-candidate  { background: #f59e0b; }
  .web-validated  { background: #22c55e; }
  .web-rejected   { background: #64748b; }
  .web-broken     { background: #ef4444; }
  .web-url { color: #60a5fa; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  a.web-url:hover { text-decoration: underline; }
  .web-meta { color: #94a3b8; font-size: .7rem; white-space: nowrap; }
  .web-actions { display: flex; gap: .2rem; margin-left: auto; flex-shrink: 0; }
  .web-btn { background: none; border: none; cursor: pointer; font-size: .8rem; padding: 2px 5px; border-radius: 3px; }
  .web-validate { color: #22c55e; } .web-validate:hover { background: #14532d44; }
  .web-reject   { color: #f87171; } .web-reject:hover   { background: #7f1d1d44; }
  .web-del      { color: #94a3b8; } .web-del:hover      { color: #ef4444; }
  .add-web { display: flex; gap: .4rem; margin-top: .4rem; }
  .web-input { flex: 1; }
</style>
