<script>
  // Sous le titre d'une section de données : le dossier thématique qui en
  // parle, s'il est publié. Les deux s'ignoraient (docs/refonte-du-contenu.md,
  // § 1.5) ; rien ne s'affiche quand il n'y a pas de dossier.
  export let dossier = null
</script>

{#if dossier}
  <p class="vers-dossier">
    Dossier thématique&nbsp;: <a href="/dossiers/{dossier.slug}">{dossier.titre}</a>
  </p>
{/if}

<style>
  .vers-dossier {
    margin: -.2rem 0 .9rem; font-size: .88rem; color: var(--gris);
    border-left: 3px solid var(--ardoise); padding-left: .6rem;
  }
  .vers-dossier a { color: var(--ardoise); font-weight: 600; }
</style>
