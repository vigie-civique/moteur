<script>
  // Système / Clair / Sombre. « Système » suit le réglage de l'ordinateur et
  // reste le choix par défaut ; le choix est mémorisé sur ce navigateur.
  import { choix, choisir, CHOIX } from '$lib/theme.js'

  export let libelle = 'Affichage'
</script>

<div class="choix-theme" role="radiogroup" aria-label={libelle}>
  {#each CHOIX as c}
    <button type="button" role="radio" aria-checked={$choix === c.cle}
            class:actif={$choix === c.cle} on:click={() => choisir(c.cle)}>
      {c.libelle}
    </button>
  {/each}
</div>

<style>
  .choix-theme {
    display: flex;
    max-width: 16rem;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--bordure);
    border-radius: 6px;
    background: var(--fond);
  }
  button {
    flex: 1;
    padding: .2rem .3rem;
    border-radius: 4px;
    font-size: .72rem;
    color: var(--texte-doux);
    white-space: nowrap;
  }
  button:hover:not(.actif) { color: var(--texte); background: var(--surface-2); }
  button.actif { background: var(--bouton); color: var(--sur-accent); }
  button:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
</style>
