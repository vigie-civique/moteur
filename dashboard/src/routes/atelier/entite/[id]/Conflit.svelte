<script>
  import { createEventDispatcher } from 'svelte'
  import { heureLocale } from '$lib/heure.js'
  import { LIBELLES } from '$lib/champs.js'

  // Détail d'un 409 : { message, par, le, champs, updated_at }
  export let conflit
  export let modifies = []

  const dispatch = createEventDispatcher()
</script>

<div class="conflit" role="alert">
  <strong>⚠ {conflit.message}</strong>
  <p>
    {#if conflit.par}Par <b>{conflit.par}</b>{#if conflit.le}, le {heureLocale(conflit.le)}{/if}.{:else if conflit.le}Le {heureLocale(conflit.le)}.{/if}
    Rien de ce que vous avez tapé n'est perdu : c'est toujours dans le formulaire.
  </p>
  {#if conflit.champs?.length}
    <ul>
      {#each conflit.champs as c}
        <li>
          {LIBELLES[c.champ] ?? c.champ} : « {c.avant ?? '—'} » → « {c.apres ?? '—'} »
          {#if c.par && c.par !== conflit.par}<span class="muted">({c.par})</span>{/if}
          {#if modifies.includes(c.champ)}<em> — vous l'avez modifié aussi : c'est votre valeur qui sera gardée</em>{/if}
        </li>
      {/each}
    </ul>
  {/if}
  <div class="conflit-actions">
    <button class="btn-reprendre" on:click={() => dispatch('reprendre')}>Charger la version à jour en gardant mes modifications</button>
    <button class="btn-secondaire" on:click={() => dispatch('abandonner')}>Abandonner mes modifications des champs</button>
  </div>
</div>

<style>
  .conflit {
    flex-shrink: 0;
    padding: .75rem 1rem;
    background: #3b2506;
    border-bottom: 1px solid #b45309;
    color: #fde68a;
    font-size: .85rem;
    line-height: 1.45;
  }
  .conflit p { margin: .3rem 0; }
  .conflit ul { margin: .3rem 0 .5rem 1.1rem; }
  .conflit em { color: #fca5a5; font-style: normal; }
  .conflit-actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .4rem; }
  .btn-reprendre {
    padding: .38rem .9rem; background: #2563eb; color: #fff;
    border-radius: 6px; font-size: .8rem; font-weight: 600; cursor: pointer;
  }
  .btn-reprendre:hover { background: #1d4ed8; }
  .btn-secondaire {
    padding: .38rem .9rem; border: 1px solid #b45309; border-radius: 6px;
    font-size: .8rem; color: #fde68a; cursor: pointer;
  }
  .btn-secondaire:hover { background: #451a03; }
</style>
