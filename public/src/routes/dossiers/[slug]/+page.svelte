<script>
  import { CONTACT_EMAIL, SITE_NOM } from '$lib/instance.js'

  export let data
  $: d = data.dossier

  const fmt = (x) => {
    try { return new Date(x + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return x }
  }
</script>

<svelte:head>
  <title>{d.titre} — {SITE_NOM}</title>
  <meta name="description" content={d.chapeau || d.titre} />
</svelte:head>

<article>
  <p class="fil"><a href="/dossiers">Dossiers</a> › {d.titre}</p>
  {#if d.statut === 'brouillon'}
    <p class="bandeau">Brouillon — aperçu local, cette page n'est pas publiée.</p>
  {/if}
  <h1>{d.titre}</h1>
  {#if d.chapeau}<p class="chapeau">{d.chapeau}</p>{/if}
  {#if d.maj}<p class="maj">Mis à jour le {fmt(d.maj)}</p>{/if}

  {#if d.statut === 'a_developper'}
    <p class="vide">Sujet identifié, dossier non instruit à ce jour.</p>
  {:else}
    <!-- Rendu au build depuis le markdown de l'instance : un texte que nous
         écrivons nous-mêmes, jamais une saisie de lecteur. -->
    <div class="corps">{@html d.html}</div>

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
  .fil a, .reponse a { color: var(--ardoise); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 .4rem; }
  .maj { color: var(--gris); font-size: .8rem; margin: 0 0 1.5rem; }
  .vide { border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem; color: var(--gris); }
  .bandeau { background: #fdebd0; color: #8a4b00; padding: .5rem .8rem; border-radius: .4rem; font-size: .88rem; }

  .corps { line-height: 1.65; overflow-wrap: anywhere; }
  .corps :global(h2) { font-size: 1.3rem; margin: 2.2rem 0 .6rem; }
  .corps :global(h3) { font-size: 1.05rem; margin: 1.6rem 0 .4rem; }
  .corps :global(p), .corps :global(li) { max-width: 70ch; }
  .corps :global(a) { color: var(--ardoise); }
  .corps :global(blockquote) { margin: 1rem 0; padding: .2rem 0 .2rem 1rem;
                               border-left: 3px solid var(--trait); color: var(--gris); }
  /* Les tableaux défilent dans leur cadre plutôt que d'élargir la page. */
  .corps :global(table) { display: block; overflow-x: auto; border-collapse: collapse;
                          margin: 1rem 0; font-size: .9rem; max-width: 100%; }
  .corps :global(th), .corps :global(td) { border-bottom: 1px solid var(--trait-pale);
                                           padding: .35rem .6rem; text-align: left; vertical-align: top; }
  .corps :global(th) { font-weight: 600; border-bottom-color: var(--trait); }
  .corps :global(td[align="right"]), .corps :global(th[align="right"]) { text-align: right;
                                           font-variant-numeric: tabular-nums; }
  .corps :global(code) { font-family: var(--data); font-size: .88em; }

  .reponse { margin-top: 2.5rem; padding: 1rem 1.2rem; background: var(--papier);
             border-radius: .5rem; font-size: .92rem; line-height: 1.55; }
  .reponse h2 { font-size: 1rem; margin: 0 0 .4rem; }
  .reponse p { margin: 0; }
</style>
