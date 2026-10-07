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

  // L'infobulle d'une citation d'acte : titre, date, assemblée, vote, pièce
  // source — ce que la base porte, rien d'autre. Les liens sont posés au build
  // (collectors/citations.py) ; on retrouve la citation par son adresse.
  $: parUrl = new Map((d.citations || []).map((c) => [c.url, c]))
  let fiche = null, place = { x: 0, y: 0 }, fermeture
  function citationDe(cible) {
    const a = cible?.closest?.('a')
    return a && corps?.contains(a) ? [a, parUrl.get(a.getAttribute('href'))] : [null, null]
  }
  function montrer(ev) {
    const [a, c] = citationDe(ev.target)
    if (!c) return
    clearTimeout(fermeture)
    const r = a.getBoundingClientRect(), boite = corps.getBoundingClientRect()
    place = { x: Math.max(0, Math.min(r.left - boite.left, boite.width - 300)), y: r.bottom - boite.top + 6 }
    fiche = c
  }
  function cacher() { fermeture = setTimeout(() => { fiche = null }, 250) }
  const vote = (v) => !v ? '' : v.unanimite ? 'unanimité'
    : [`${v.pour ?? '?'} pour`, v.contre ? `${v.contre} contre` : '', v.abstention ? `${v.abstention} abst.` : ''].filter(Boolean).join(' · ')
  const jour = (x) => x ? `${x.slice(8, 10)}/${x.slice(5, 7)}/${x.slice(0, 4)}` : ''
  function basculer() {
    toutOuvert = !toutOuvert
    corps?.querySelectorAll('details').forEach((e) => { e.open = toutOuvert })
  }
</script>

<svelte:head>
  <title>{d.titre} - {SITE_NOM}</title>
  <meta name="description" content={d.chapeau || d.titre} />
</svelte:head>

<article>
  <nav class="fil" aria-label="Fil d'Ariane"><a href="/dossiers">Dossiers thématiques</a> › {d.titre}</nav>
  {#if d.statut === 'brouillon'}
    <p class="bandeau">Brouillon : aperçu local, cette page n'est pas publiée.</p>
  {/if}
  <h1>{d.titre}</h1>
  {#if d.perime}
    <!-- Le dossier a été relu, et rien de ce qu'il affirme n'a changé ; un acte
         qu'il cite, si. Il reste publié, et le dit. -->
    <div class="bandeau perime" role="note">
      <p><b>Un élément cité a changé depuis la relecture du {fmt(d.perime.relu_le)}.</b>
        Le texte ci-dessous est celui qui a été relu ; vérifiez l'acte avant de vous y fier.</p>
      <ul>
        {#each d.perime.elements as el}
          <li>{el.libelle}{#if el.titre}, {el.titre}{/if} :
            {el.quoi === 'disparu' ? "n'est plus publiée" : `${el.champs.join(', ') || 'son contenu'} ${el.champs.length > 1 ? 'ont' : 'a'} changé`}</li>
        {/each}
      </ul>
    </div>
  {/if}
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
    <!-- focusin/focusout portent le clavier (ils remontent, focus/blur non). -->
    <!-- svelte-ignore a11y-no-static-element-interactions a11y-mouse-events-have-key-events -->
    <div class="corps" bind:this={corps}
         on:mouseover={montrer} on:focusin={montrer} on:mouseout={cacher} on:focusout={cacher}
         on:keydown={(ev) => { if (ev.key === 'Escape') fiche = null }}>
      {@html d.html}
      {#if fiche}
        <div class="fiche" role="tooltip" style="left:{place.x}px; top:{place.y}px"
             on:mouseenter={() => clearTimeout(fermeture)} on:mouseleave={cacher}>
          <p class="quoi">
            {fiche.type === 'seance' ? 'Séance' : fiche.type === 'piece' ? 'Pièce source' : 'Délibération'}{#if fiche.numero}{' '}n°{fiche.numero}{/if}
            · {fiche.assemblee} · {jour(fiche.date)}
          </p>
          {#if fiche.type !== 'seance' && fiche.titre}<p class="titre">{fiche.titre}</p>{/if}
          {#if fiche.vote}<p>Vote : {vote(fiche.vote)}</p>{/if}
          {#if fiche.statut === 'imprecis'}<p class="imprecis">Renvoi imprécis : {fiche.raison}.</p>{/if}
          {#if fiche.cle_faible}<p class="imprecis">Cet acte n'a pas de numéro : ce lien peut changer.</p>{/if}
          {#if fiche.source_url}<p><a href={fiche.source_url} target="_blank" rel="noopener">Ouvrir la pièce source ↗</a></p>{/if}
        </div>
      {/if}
    </div>

    {#if data.donnees?.length}
      <aside class="donnees">
        <h2>Les données de ce sujet</h2>
        <p>Les mêmes faits, tels que les sources publiques les donnent, sans commentaire&nbsp;:</p>
        <ul>
          {#each data.donnees as sec}
            <li><a href="{sec.page}{sec.ancre ? `#${sec.ancre}` : ''}">{sec.titre}</a></li>
          {/each}
        </ul>
      </aside>
    {/if}

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
  .perime { margin: 0 0 1rem; }
  .perime p { margin: 0 0 .3rem; }
  .perime ul { margin: 0; padding-left: 1.2rem; }

  .corps { position: relative; }
  .fiche { position: absolute; z-index: 5; width: min(300px, 100%); background: var(--blanc);
           border: 1px solid var(--trait); border-radius: .5rem; padding: .55rem .75rem;
           box-shadow: 0 4px 14px rgb(0 0 0 / .12); font-size: .84rem; line-height: 1.45; }
  .fiche p { margin: 0 0 .25rem; max-width: none; }
  .fiche .quoi { color: var(--gris); font-size: .78rem; }
  .fiche .titre { font-weight: 600; }
  .fiche .imprecis { color: var(--ambre); }

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

  .donnees { margin-top: 2.5rem; padding: 1rem 1.2rem; border-left: 3px solid var(--ardoise);
             font-size: .92rem; line-height: 1.55; }
  .donnees h2 { font-size: 1rem; margin: 0 0 .4rem; }
  .donnees p { margin: 0 0 .3rem; color: var(--gris); }
  .donnees ul { margin: 0; padding-left: 1.2rem; }
  .reponse { margin-top: 2.5rem; padding: 1rem 1.2rem; background: var(--papier);
             border-radius: .5rem; font-size: .92rem; line-height: 1.55; }
  .reponse h2 { font-size: 1rem; margin: 0 0 .4rem; }
  .reponse p { margin: 0; }

  @media print {
    .sommaire button, .reponse, .bandeau { display: none; }
    .corps :global(details.plus) { border: none; padding: 0; }
  }
</style>
