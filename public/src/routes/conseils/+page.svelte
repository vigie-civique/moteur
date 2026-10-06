<script>
  import { SITE_NOM } from '$lib/instance.js'
  import { enumerer } from '$lib/couverture.js'
  // Rendu au build par +page.server.js.
  export let data
  $: seances = data.seances || []
  $: relues = seances.filter((s) => s.en_clair).length
  $: annees = [...new Set(seances.map((s) => s.date.slice(0, 4)))].sort().reverse()
  const fmt = (d) => {
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
  const compte = (n) => (n > 0 ? `${n} délibération${n > 1 ? 's' : ''} publiée${n > 1 ? 's' : ''}`
                                : 'aucune délibération lue dans les pièces')
</script>

<svelte:head>
  <title>Les conseils en clair - {SITE_NOM}</title>
  <meta name="description" content="Chaque séance du conseil municipal et du conseil communautaire : ce qui a été décidé, les pièces qui l'attestent, et pour les séances relues, trois feuilles en clair." />
</svelte:head>

<section>
  <p class="fil"><a href="/qui-decide">Qui décide</a> › Les conseils en clair</p>
  <h1>Les conseils en clair</h1>
  <p class="chapeau">
    Chaque séance a sa page&nbsp;: ses délibérations, et les pièces qui les
    attestent. Une séance <b>mise en clair</b> a en plus trois feuilles A4,
    ce qui était annoncé, ce qui a été décidé, et ce que les documents publics
    ont de faux ou d'incomplet, rédigées à partir des procès-verbaux,
    vérifiées automatiquement et relues par une personne.
  </p>

  {#if data.seances === null}
    <p class="vide">Les pages de séance n'existaient pas encore lors de la dernière publication des données.</p>
  {:else if !seances.length}
    <p class="vide">
      {#if data.source.etat === 'absente'}
        Aucune séance ne figure ici&nbsp;: {enumerer(data.source.sources)} n'ont
        pas été collectés pour ce site. C'est une question non posée, pas une
        absence de séances.
      {:else}
        Aucune séance n'est publiée pour l'instant.
      {/if}
    </p>
  {:else}
    <p class="aide">
      {seances.length.toLocaleString('fr-FR')} séance{seances.length > 1 ? 's' : ''},
      dont {relues ? `${relues} mise${relues > 1 ? 's' : ''} en clair` : 'aucune encore mise en clair'}.
    </p>
    {#each annees as a}
      <h2>{a}</h2>
      <ol class="seances">
        {#each seances.filter((s) => s.date.startsWith(a)) as s}
          <li>
            <span class="nature" class:cc={s.code === 'cc'}>{s.assemblee}</span>
            <a href="/conseils/{s.id}"><time datetime={s.date}>{fmt(s.date)}</time>{#if s.en_clair} : {s.en_clair.titre}{/if}</a>
            <span class="quand">
              {compte(s.nb_actes)} ·
              {#if s.en_clair}<b class="clair">mise en clair</b>, relue le {s.en_clair.relu_le}
              {:else}pas encore mise en clair{/if}
            </span>
          </li>
        {/each}
      </ol>
    {/each}
  {/if}
</section>

<style>
  section { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a { color: var(--ardoise); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 .6rem; }
  .aide { color: var(--gris); font-size: .88rem; max-width: 66ch; line-height: 1.55; margin: 0 0 .8rem; }
  .vide { max-width: 62ch; border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem;
          color: var(--gris); line-height: 1.6; }
  .seances { list-style: none; padding: 0; margin: 0; }
  .seances li { display: flex; flex-wrap: wrap; gap: .2rem .7rem; align-items: baseline;
                padding: .6rem 0; border-bottom: 1px solid var(--trait-pale); font-size: .92rem; }
  .seances a { flex: 1; min-width: 14rem; color: var(--ardoise); overflow-wrap: anywhere; }
  .seances time { font-weight: 600; }
  .nature { font-size: .68rem; font-weight: 700; text-transform: uppercase; color: var(--ardoise-fonce);
            background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .45rem; }
  .nature.cc { background: var(--trait-pale); color: var(--encre); }
  .quand { flex-basis: 100%; color: var(--gris); font-size: .8rem; font-variant-numeric: tabular-nums; }
  .clair { color: var(--ardoise-fonce); }
</style>
