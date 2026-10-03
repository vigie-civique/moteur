<script>
  import { createEventDispatcher } from 'svelte'
  import { enumerer } from './brouillon.js'

  // Ce que le bouton enregistrera, en mots (brouillon.js : resumer).
  export let resume = []
  export let enregistrement = false
  // Un conflit sur les champs bloque l'envoi : il se règle d'abord, en haut.
  export let bloque = false
  export let bilan = []           // [{ ok, texte }] du dernier enregistrement

  const dispatch = createEventDispatcher()
</script>

<div class="barre" class:attente={resume.length}>
  {#if bilan.length}
    <ul class="bilan" role="status">
      {#each bilan as b}<li class:echec={!b.ok}>{b.ok ? '✓' : '⚠'} {b.texte}</li>{/each}
    </ul>
  {/if}
  <div class="ligne">
    <button class="btn-enregistrer" on:click={() => dispatch('enregistrer')}
            disabled={enregistrement || bloque || !resume.length}>
      {#if enregistrement}
        Enregistrement…
      {:else if !resume.length}
        Rien à enregistrer
      {:else}
        Enregistrer {enumerer(resume)}
      {/if}
    </button>
    {#if resume.length && !enregistrement}
      <button class="btn-annuler" on:click={() => dispatch('annuler')}>Annuler ces changements</button>
    {/if}
    {#if bloque}
      <span class="bloque">Réglez d'abord le conflit en haut de la fiche.</span>
    {/if}
  </div>
</div>

<style>
  .barre {
    flex-shrink: 0;
    padding: .55rem 1rem;
    background: var(--surface);
    border-top: 1px solid var(--bordure);
    display: flex; flex-direction: column; gap: .4rem;
  }
  .barre.attente { border-top-color: var(--alerte-bordure); }
  .ligne { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }

  .btn-enregistrer {
    padding: .45rem 1rem;
    background: var(--bouton); color: var(--sur-accent);
    border-radius: 6px; font-size: .82rem; font-weight: 600;
    cursor: pointer; text-align: left; line-height: 1.35;
    transition: background .12s;
  }
  .btn-enregistrer:hover:not(:disabled) { background: var(--accent-fort); }
  .btn-enregistrer:disabled { opacity: .45; cursor: default; }

  .btn-annuler {
    padding: .4rem .8rem; border: 1px solid var(--bordure); border-radius: 6px;
    font-size: .78rem; color: var(--texte-doux); cursor: pointer;
  }
  .btn-annuler:hover { border-color: var(--bordure-forte); color: var(--texte); }

  .bloque { font-size: .78rem; color: var(--alerte); }

  .bilan { list-style: none; display: flex; flex-direction: column; gap: .15rem; font-size: .78rem; color: var(--succes); }
  .bilan .echec { color: var(--danger); }
</style>
