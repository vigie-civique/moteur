<script>
  import { COMMUNE_DE, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
  import { TYPE_LABELS } from '$lib/data.js'

  // Rendu au build par +page.server.js.
  export let data
  $: all = data.all
  let q = '', typeFilter = 'all'
  // Par défaut on ne montre que les acteurs cités quelque part (délibération,
  // flux, marché, mandat). Sans ça la page affiche les ~2 700 fiches du
  // répertoire SIRENE, dont l'écrasante majorité n'est documentée nulle part.
  let scope = 'cites'
  const TYPES = ['service', 'association', 'business', 'place']

  const cite = (e) => (e.citations || 0) > 0
  $: cites = all.filter(cite)
  $: scoped = scope === 'cites' ? cites : all
  $: counts = scoped.reduce((a, e) => { a[e.type] = (a[e.type] || 0) + 1; return a }, {})
  $: filtered = scoped
    .filter(e => typeFilter === 'all' || e.type === typeFilter)
    .filter(e => !q || (e.name || '').toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.citations || 0) - (a.citations || 0) || (a.name || '').localeCompare(b.name || ''))
</script>

<svelte:head><title>Acteurs publics — {SITE_NOM}</title>
  <meta name="description" content="Annuaire des services publics, associations et lieux {COMMUNE_DE} et des institutions qui décident pour elle." /></svelte:head>

<section>
  <header class="tete">
    <div>
      <h1 class="avec-icone"><Icon name="acteurs" size={26} />Qui agit&nbsp;?</h1>
      <p class="sub">Services, associations, entreprises et lieux d'intérêt public recensés sur la commune.</p>
    </div>
    <!-- La carte est une vue de cet annuaire : elle ne porte que les acteurs
         dont on connaît la position. Le passage doit se faire dans les deux sens. -->
    <a class="vers-carte" href="/carte">
      <Icon name="acteurs" size={15} />Voir sur la carte<Icon name="fleche" size={15} />
    </a>
  </header>

  {#if all.length}
    <div class="scope">
      <button class:on={scope === 'cites'} on:click={() => scope = 'cites'}>Cités dans un acte <b>{cites.length}</b></button>
      <button class:on={scope === 'tous'} on:click={() => scope = 'tous'}>Tout le répertoire <b>{all.length}</b></button>
    </div>
    <p class="scope-hint">
      {#if scope === 'cites'}
        Acteurs nommés dans au moins une délibération, un flux financier, un marché ou un mandat.
      {:else}
        Répertoire complet, entreprises SIRENE comprises — la plupart n'apparaissent dans aucun acte public.
      {/if}
    </p>

    <div class="chips">
      <button class:on={typeFilter === 'all'} on:click={() => typeFilter = 'all'}>Tout <b>{scoped.length}</b></button>
      {#each TYPES as t}
        <button class="{t}" class:on={typeFilter === t} on:click={() => typeFilter = t}>{TYPE_LABELS[t]} <b>{counts[t] || 0}</b></button>
      {/each}
    </div>
  {/if}

  <div class="filters">
    <input placeholder="Rechercher…" bind:value={q} />
    <span class="count">{filtered.length} résultat{filtered.length > 1 ? 's' : ''}</span>
  </div>

  {#if !all.length}<p class="err">Aucun acteur dans ce jeu de données.</p>{/if}

  <ul class="grid">
    {#each filtered as e (e.id)}
      <li>
        <a href="/entite/{e.id}">
          <span class="badge {e.type}">{TYPE_LABELS[e.type]}</span>
          <strong>{e.name}</strong>
          {#if e.citations}
            <span class="cit">{e.citations} acte{e.citations > 1 ? 's' : ''} public{e.citations > 1 ? 's' : ''}</span>
          {/if}
        </a>
      </li>
    {/each}
  </ul>
</section>

<style>
  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; }
  h1 { color: var(--encre); margin: 0 0 .25rem; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
  .sub { color: var(--gris); margin: 0 0 1rem; }
  .tete { display: flex; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  .vers-carte {
    margin-left: auto; display: inline-flex; align-items: center; gap: .4rem;
    padding: .4rem .7rem; border: 1px solid var(--trait); border-radius: var(--rayon);
    background: var(--blanc); font-size: .85rem; white-space: nowrap;
  }
  .vers-carte:hover { border-color: var(--ardoise); text-decoration: none; }
  .scope { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .4rem; }
  .scope button { padding: .4rem .8rem; border: 1px solid var(--trait); border-radius: 6px; background: #fff; color: var(--gris); font-size: .85rem; cursor: pointer; }
  .scope button b { font-weight: 700; color: var(--encre); }
  .scope button.on { border-color: var(--encre); background: var(--encre); color: #fff; }
  .scope button.on b { color: #fff; }
  .scope-hint { color: var(--gris); font-size: .8rem; margin: 0 0 .9rem; max-width: 70ch; }
  .cit { font-size: .72rem; color: var(--gris); }
  .chips { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }
  .chips button { padding: .35rem .75rem; border: 1px solid var(--trait); border-radius: 99px; background: #fff; color: var(--gris); font-size: .85rem; cursor: pointer; }
  .chips button b { font-weight: 700; color: var(--encre); }
  .chips button.on { border-color: var(--ardoise); background: var(--ardoise-pale); color: var(--ardoise-fonce); }
  .chips button.on b { color: var(--ardoise-fonce); }
  .filters { display: flex; gap: .75rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
  input { padding: .5rem .7rem; border: 1px solid var(--trait); border-radius: 6px; font-size: .95rem; flex: 1; min-width: 200px; }
  .count { color: var(--gris); font-size: .85rem; }
  .grid { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .6rem; }
  .grid a { display: flex; flex-direction: column; gap: .35rem; padding: .75rem; background: #fff; border: 1px solid var(--trait); border-radius: 8px; color: var(--encre); }
  .grid a:hover { border-color: var(--ardoise); text-decoration: none; }
  .badge { align-self: flex-start; font-size: .7rem; padding: .1rem .5rem; border-radius: 99px; color: #fff; }
  .badge.service { background: var(--ardoise); } .badge.association { background: var(--recette); }
  .badge.business { background: var(--ambre); } .badge.place { background: var(--ardoise); }
  .err { color: var(--depense); }
</style>
