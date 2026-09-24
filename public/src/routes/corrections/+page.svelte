<script>
  import { CONTACT_EMAIL, SITE_NOM } from '$lib/instance.js'
  import { INSTITUTIONAL, anneeDe } from '$lib/actes.js'

  // Rendu au build par +page.server.js.
  export let data
  $: site = data.journal?.site || []
  $: donnees = data.journal?.donnees || []

  const NATURES = { acte: 'Acte', flux: 'Versement', marche: 'Marché' }
  // Un acte d'assemblée s'ouvre à sa ligne, dans son millésime ; le reste
  // renvoie à la page qui le liste.
  const LIENS = {
    acte: (d) => INSTITUTIONAL[d.type] ? `/deliberations/${anneeDe(d)}#a${d.id}` : '/nouveautes',
    marche: () => '/marches', flux: () => '/finances',
  }
  const fmt = (d) => {
    if (!d) return '—'
    if (/^\d{4}$/.test(d)) return d
    try { return new Date(d.slice(0, 10) + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
</script>

<svelte:head>
  <title>Journal des corrections — {SITE_NOM}</title>
  <meta name="description" content="Les erreurs reconnues sur ce site et leur correction : calculs, doublons, libellés, et données rectifiées après vérification sur le document d'origine." />
</svelte:head>

<section>
  <p class="fil"><a href="/methode">Méthode &amp; sources</a> › Corrections</p>
  <h1>Journal des corrections</h1>
  <p class="chapeau">
    Ce que ce site a affiché de faux, quand il l'a corrigé, et comment. Une
    erreur signalée qui n'est pas ici n'a pas encore été traitée&nbsp;: elle se
    signale par la page <a href="/contact">Droit de réponse</a>{#if CONTACT_EMAIL}
    ou à <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>{/if}.
  </p>

  {#if !data.journal}
    <p class="vide">Ce journal n'existait pas encore lors de la dernière publication des données.</p>
  {:else}
    <h2>Erreurs du site</h2>
    <p class="aide">
      Un calcul faux, un doublon compté deux fois, un chiffre mal nommé&nbsp;:
      ces erreurs ne laissent aucune trace dans les données. Elles sont
      écrites ici, à la main, par ceux qui tiennent le site.
    </p>
    {#if site.length}
      <ol class="journal">
        {#each site as e}
          <li>
            <time datetime={e.date}>{fmt(e.date)}</time>
            {#if e.page}<a class="page" href={e.page}>{e.page}</a>{/if}
            <p><b>Constat&nbsp;:</b> {e.constat}</p>
            <p><b>Correction&nbsp;:</b> {e.correction}</p>
            {#if e.signale_par}<p class="par">Signalé par {e.signale_par}.</p>{/if}
          </li>
        {/each}
      </ol>
    {:else}
      <p class="vide">Aucune erreur du site n'a été consignée à ce jour.</p>
    {/if}

    <h2>Données rectifiées</h2>
    <p class="aide">
      Une donnée lue de travers dans un document — un numéro d'article pris
      pour un montant, une date fausse — est rectifiée après vérification sur
      le document d'origine. La valeur collectée est conservée à côté&nbsp;;
      sur le site, la donnée porte la mention <b>✎ rectifié</b>.
    </p>
    {#if donnees.length}
      <ul class="donnees">
        {#each donnees as d}
          <li>
            <span class="nature">{NATURES[d.nature] || d.nature}</span>
            <span class="quand">{fmt(d.date)}</span>
            <a href={LIENS[d.nature]?.(d) || '/nouveautes'}>{d.libelle || '(sans libellé)'}</a>
            <span class="champs">champ{d.champs.length > 1 ? 's' : ''} rectifié{d.champs.length > 1 ? 's' : ''}&nbsp;: {d.champs.join(', ')}</span>
            {#if d.motif}<span class="motif">{d.motif}</span>{/if}
          </li>
        {/each}
      </ul>
    {:else}
      <p class="vide">
        Aucune donnée n'a encore été rectifiée à la main{#if data.arreteLe}
        (données arrêtées au {fmt(data.arreteLe)}){/if}. Ce zéro ne veut pas dire
        que tout est juste&nbsp;: il veut dire que personne n'a encore relu une
        donnée publiée au point de la corriger.
      </p>
    {/if}
  {/if}
</section>

<style>
  section { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a, .chapeau a, .journal a, .donnees a { color: var(--ardoise); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 1rem; overflow-wrap: anywhere; }
  .aide { color: var(--gris); font-size: .88rem; max-width: 66ch; line-height: 1.55; margin: 0 0 .8rem; }
  .vide { max-width: 62ch; border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem;
          color: var(--gris); line-height: 1.6; }

  .journal { list-style: none; padding: 0; margin: 0; }
  .journal li { padding: .8rem 0; border-bottom: 1px solid var(--trait-pale); }
  .journal time { font-weight: 600; font-size: .9rem; }
  .journal .page { margin-left: .6rem; font-size: .82rem; font-family: var(--data); }
  .journal p { margin: .3rem 0 0; line-height: 1.5; font-size: .92rem; }
  .journal .par { color: var(--gris); font-size: .82rem; }

  .donnees { list-style: none; padding: 0; margin: 0; }
  .donnees li { display: flex; flex-wrap: wrap; gap: .2rem .7rem; align-items: baseline;
                padding: .55rem 0; border-bottom: 1px solid var(--trait-pale); font-size: .9rem; }
  .donnees a { flex: 1; min-width: 12rem; overflow-wrap: anywhere; }
  .nature { font-size: .68rem; font-weight: 700; text-transform: uppercase; color: var(--ardoise-fonce);
            background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .45rem; }
  .quand { color: var(--gris); font-size: .82rem; font-variant-numeric: tabular-nums; }
  .champs, .motif { flex-basis: 100%; color: var(--gris); font-size: .8rem; }
</style>
