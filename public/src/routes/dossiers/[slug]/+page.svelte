<script>
  import { CONTACT_EMAIL, SITE_NOM } from '$lib/instance.js'

  export let data
  $: d = data.dossier

  const fmt = (x) => {
    try { return new Date(x + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return x }
  }

  // « Pour aller plus loin » est replié pour l'habitant pressé ; le spécialiste
  // déplie tout d'un geste. Sans JavaScript, chaque bloc s'ouvre seul.
  let corps
  let toutOuvert = false
  function basculer() {
    toutOuvert = !toutOuvert
    corps?.querySelectorAll('details').forEach((e) => { e.open = toutOuvert })
  }
</script>

<svelte:head>
  <title>{d.titre} — {SITE_NOM}</title>
  <meta name="description" content={d.chapeau || d.titre} />
</svelte:head>

<article>
  <nav class="fil" aria-label="Fil d'Ariane"><a href="/dossiers">Dossiers</a> › {d.titre}</nav>
  {#if d.statut === 'brouillon'}
    <p class="bandeau">Brouillon — aperçu local, cette page n'est pas publiée.</p>
  {/if}
  <h1>{d.titre}</h1>
  {#if d.chapeau}<p class="chapeau">{d.chapeau}</p>{/if}
  <p class="maj">
    {#if d.maj}Mis à jour le {fmt(d.maj)}{/if}{#if d.minutes} · environ {d.minutes} min de lecture{#if d.minutesTout > d.minutes}, {d.minutesTout} avec le détail{/if}{/if}
  </p>

  {#if d.statut === 'a_developper'}
    <p class="vide">Sujet identifié, dossier non instruit à ce jour.</p>
  {:else}
    {#if d.sommaire?.length > 2}
      <nav class="sommaire" aria-labelledby="sommaire-titre">
        <h2 id="sommaire-titre">Sommaire</h2>
        <ul>
          {#each d.sommaire as s}<li><a href="#{s.id}">{s.titre}</a></li>{/each}
        </ul>
        <p class="mode">
          Chaque partie commence par l'essentiel, en mots simples. Le détail
          chiffré et les sources sont dans les blocs « Pour aller plus loin ».
          {#if d.replis}
            <button type="button" on:click={basculer} aria-pressed={toutOuvert}>
              {toutOuvert ? 'Replier' : 'Déplier'} les {d.replis} blocs de détail
            </button>
          {/if}
        </p>
      </nav>
    {/if}

    <!-- Rendu au build depuis le markdown de l'instance : un texte que nous
         écrivons nous-mêmes, jamais une saisie de lecteur. -->
    <div class="corps" bind:this={corps}>{@html d.html}</div>

    <aside class="reponse">
      <h2>Droit de réponse</h2>
      <p>
        Vous êtes cité ou concerné par ce dossier, ou vous y relevez une
        erreur&nbsp;? Écrivez-nous par la page <a href="/contact">Droit de réponse</a>{#if CONTACT_EMAIL}
        ou à <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>{/if}. Votre réponse
        sera publiée ici, et une erreur reconnue entre au
        <a href="/corrections">journal des corrections</a>.
      </p>
    </aside>
  {/if}
</article>

<style>
  article { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a, .reponse a, .sommaire a { color: var(--ardoise); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; text-wrap: balance; }
  .chapeau { font-size: 1.12rem; max-width: 62ch; line-height: 1.55; margin: 0 0 .5rem; }
  .maj { color: var(--gris); font-size: .82rem; margin: 0 0 1.5rem; }
  .vide { border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem; color: var(--gris); }
  .bandeau { background: #fdebd0; color: #8a4b00; padding: .5rem .8rem; border-radius: .4rem; font-size: .88rem; }

  .sommaire { border-top: 1px solid var(--trait); border-bottom: 1px solid var(--trait);
              padding: .8rem 0 1rem; margin: 0 0 2rem; font-size: .92rem; }
  .sommaire h2 { font-size: .78rem; text-transform: uppercase; letter-spacing: .06em;
                 color: var(--gris); margin: 0 0 .5rem; }
  .sommaire ul { list-style: none; margin: 0; padding: 0; columns: 2 16rem; column-gap: 2rem; line-height: 1.7; }
  .sommaire li { break-inside: avoid; }
  .sommaire .mode { color: var(--gris); font-size: .85rem; margin: .8rem 0 0; max-width: 66ch; line-height: 1.5; }
  .sommaire button { display: block; margin-top: .6rem; font: inherit; font-size: .85rem;
                     color: var(--ardoise); background: none; border: 1px solid var(--ardoise);
                     border-radius: .4rem; padding: .25rem .7rem; cursor: pointer; }
  .sommaire button:hover, .sommaire button:focus-visible { background: var(--ardoise); color: var(--blanc); }

  /* Lecture confortable : 17 px, interligne large, lignes courtes. */
  .corps { font-size: 1.06rem; line-height: 1.7; overflow-wrap: anywhere; }
  .corps :global(section) { scroll-margin-top: 5rem; }
  .corps :global(h2) { font-size: 1.35rem; margin: 2.6rem 0 .7rem; text-wrap: balance; scroll-margin-top: 5rem; }
  .corps :global(h3) { font-size: 1.08rem; margin: 1.8rem 0 .4rem; scroll-margin-top: 5rem; }
  .corps :global(p), .corps :global(li) { max-width: 68ch; }
  .corps :global(li) { margin: .25rem 0; }
  .corps :global(a) { color: var(--ardoise); }
  .corps :global(blockquote) { margin: 1rem 0; padding: .2rem 0 .2rem 1rem;
                               border-left: 3px solid var(--trait); color: var(--gris); }
  .corps :global(code) { font-family: var(--data); font-size: .88em; }

  /* L'essentiel : la réponse, avant toute démonstration. */
  .corps :global(section.essentiel) { background: var(--papier); border-left: 4px solid var(--ardoise);
                                      border-radius: 0 .6rem .6rem 0; padding: .3rem 1.3rem 1rem; margin: 0 0 1rem; }
  .corps :global(section.essentiel h2) { margin-top: .9rem; font-size: 1.15rem; }
  .corps :global(section.essentiel li) { margin: .45rem 0; }

  /* Pour aller plus loin : le détail du spécialiste, replié. */
  .corps :global(details.plus) { margin: 1rem 0; border: 1px solid var(--trait); border-radius: .5rem;
                                 padding: 0 1rem; font-size: .96rem; }
  .corps :global(details.plus[open]) { padding-bottom: .6rem; }
  .corps :global(details.plus > summary) { cursor: pointer; padding: .6rem 0; font-weight: 600;
                                           color: var(--ardoise); list-style-position: outside; margin-left: 1rem; }
  .corps :global(details.plus > summary:focus-visible) { outline: 2px solid var(--ardoise); outline-offset: 2px; }

  /* Lexique */
  .corps :global(section.mots ul) { list-style: none; padding: 0; }
  .corps :global(section.mots li) { padding: .45rem 0; border-bottom: 1px solid var(--trait-pale); }

  /* Les tableaux défilent dans leur cadre plutôt que d'élargir la page. */
  .corps :global(.tableau) { overflow-x: auto; margin: 1rem 0; }
  .corps :global(.tableau:focus-visible) { outline: 2px solid var(--ardoise); outline-offset: 2px; }
  .corps :global(table) { border-collapse: collapse; font-size: .9rem; }
  .corps :global(th), .corps :global(td) { border-bottom: 1px solid var(--trait-pale);
                                           padding: .4rem .6rem; text-align: left; vertical-align: top; }
  .corps :global(th) { font-weight: 600; border-bottom-color: var(--trait); }
  .corps :global(td[align="right"]), .corps :global(th[align="right"]) { text-align: right;
                                           font-variant-numeric: tabular-nums; white-space: nowrap; }

  .reponse { margin-top: 2.5rem; padding: 1rem 1.2rem; background: var(--papier);
             border-radius: .5rem; font-size: .92rem; line-height: 1.55; }
  .reponse h2 { font-size: 1rem; margin: 0 0 .4rem; }
  .reponse p { margin: 0; }

  @media print {
    .sommaire button, .reponse, .bandeau { display: none; }
    .corps :global(details.plus) { border: none; padding: 0; }
  }
</style>
