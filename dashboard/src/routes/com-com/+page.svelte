<script>
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  const CC_CAC_ID = 1645

  let entity   = null
  let events   = []
  let marches  = []
  let loading  = true
  let error    = ''
  let activeTab = 'presentation'
  let yearFilter = ''

  onMount(async () => {
    loading = true
    try {
      const [e, m] = await Promise.all([
        api.entity(CC_CAC_ID),
        api.marches({ acheteur: 'Communauté de Communes', limit: 200 }).catch(() => []),
      ])
      entity  = e
      events  = Array.isArray(e.events) ? e.events : []
      marches = Array.isArray(m) ? m : []
    } catch(e) { error = e.message }
    finally { loading = false }
  })

  $: delegues = entity?.relations?.filter(r =>
    r.relation_type === 'élu_cc' || r.relation_type === 'délégué_cc'
  ) ?? []

  $: delibs = events.filter(ev =>
    ev.type === 'deliberation' || ev.type === 'délibération' || ev.title?.toLowerCase().includes('délibér')
  )

  $: years = [...new Set(delibs.map(d => d.date?.slice(0,4)).filter(Boolean))].sort().reverse()

  $: delibs_filtered = yearFilter ? delibs.filter(d => d.date?.startsWith(yearFilter)) : delibs

  function fmtDate(d) { return d ? d.slice(0, 10) : '—' }
  function fmtMontant(v) { return v != null ? Math.round(v).toLocaleString('fr-FR') + ' €' : '—' }

  const TABS = [
    { id: 'presentation', label: 'Présentation' },
    { id: 'delegues',     label: 'Délégués Lasalle' },
    { id: 'deliberations',label: 'Délibérations' },
    { id: 'marches',      label: 'Marchés' },
  ]
</script>

<svelte:head><title>CC Causses Aigoual Cévennes Terres Solidaires — Vigie Civique Lasalle</title></svelte:head>

<div class="comcom-page">
  <div class="page-header">
    <h1>Communauté de Communes</h1>
    <span class="subtitle">Causses Aigoual Cévennes Terres Solidaires (CC CAC)</span>
  </div>

  {#if error}<p class="err">{error}</p>{/if}

  <nav class="tabs">
    {#each TABS as t}
      <button class:active={activeTab === t.id} on:click={() => activeTab = t.id}>
        {t.label}
        {#if t.id === 'delegues'}<span class="tc">{delegues.length}</span>{/if}
        {#if t.id === 'deliberations'}<span class="tc">{delibs.length}</span>{/if}
        {#if t.id === 'marches'}<span class="tc">{marches.length}</span>{/if}
      </button>
    {/each}
  </nav>

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else}

    {#if activeTab === 'presentation'}
      <div class="cards-row">
        <div class="info-card">
          <div class="card-title">Présentation</div>
          <p class="card-body">
            La Communauté de Communes Causses Aigoual Cévennes Terres Solidaires (CC CAC) est l'intercommunalité
            de Lasalle. Elle regroupe plusieurs communes du Gard et de la Lozère.
          </p>
          <dl>
            <dt>SIREN</dt><dd>243000809</dd>
            <dt>Siège</dt><dd>Saint-Hippolyte-du-Fort</dd>
            <dt>Délégués Lasalle</dt><dd>{delegues.length} élu(s)</dd>
            <dt>Délibérations</dt><dd>{delibs.length} documentées</dd>
            <dt>Marchés</dt><dd>{marches.length} référencés</dd>
          </dl>
          <a href="/entite/{CC_CAC_ID}" class="card-link">Voir la fiche entité →</a>
        </div>
        <div class="info-card">
          <div class="card-title">Lasalle dans la CC CAC</div>
          <p class="card-body muted">
            Lasalle dispose de {delegues.length} délégué(s) au conseil communautaire.
            Les délibérations documentées couvrent les marchés publics, budgets, projets
            intercommunaux et subventions reçues.
          </p>
        </div>
      </div>

    {:else if activeTab === 'delegues'}
      {#if !delegues.length}
        <p class="muted-center">Aucun délégué documenté.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Nom</th><th>Rôle</th><th>Depuis</th><th>Jusqu'au</th></tr></thead>
          <tbody>
            {#each delegues as r}
              <tr>
                <td>
                  {#if r.from_id !== CC_CAC_ID}
                    <a href="/entite/{r.from_id}" class="ent-link">{r.from_name}</a>
                  {:else}
                    <a href="/entite/{r.to_id}"   class="ent-link">{r.to_name}</a>
                  {/if}
                </td>
                <td><span class="rel-badge">{r.relation_type}</span></td>
                <td class="muted">{fmtDate(r.since)}</td>
                <td class="muted">{r.until ? fmtDate(r.until) : 'en cours'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    {:else if activeTab === 'deliberations'}
      <div class="filter-bar">
        <label>Année :
          <select bind:value={yearFilter}>
            <option value="">Toutes ({delibs.length})</option>
            {#each years as y}
              <option value={y}>{y} ({delibs.filter(d => d.date?.startsWith(y)).length})</option>
            {/each}
          </select>
        </label>
      </div>
      {#if !delibs_filtered.length}
        <p class="muted-center">Aucune délibération.</p>
      {:else}
        <div class="timeline">
          {#each delibs_filtered as d}
            <div class="tl-item">
              <div class="tl-date">{fmtDate(d.date)}</div>
              <div class="tl-body">
                <span class="tl-title">{d.title}</span>
                {#if d.source_url}
                  <a href={d.source_url} target="_blank" rel="noopener" class="tl-src">↗</a>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

    {:else if activeTab === 'marches'}
      {#if !marches.length}
        <p class="muted-center">Aucun marché référencé pour la CC CAC.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Objet</th><th>Titulaire</th><th>Montant</th><th>Date</th><th>Nature</th></tr></thead>
          <tbody>
            {#each marches as m}
              <tr>
                <td class="objet-cell">{m.objet ?? '—'}</td>
                <td>
                  {#if m.titulaire_id}
                    <a href="/entite/{m.titulaire_id}" class="ent-link">{m.titulaire_nom}</a>
                  {:else}
                    <span class="muted">{m.titulaire_nom ?? '—'}</span>
                  {/if}
                </td>
                <td class="montant">{fmtMontant(m.montant)}</td>
                <td class="muted">{fmtDate(m.date_notif)}</td>
                <td class="muted">{m.nature ?? '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}

  {/if}
</div>

<style>
  .comcom-page { padding: 1.2rem; max-width: 1000px; overflow-y: auto; }
  .page-header { margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .subtitle { font-size: .8rem; color: #64748b; }

  .tabs { display: flex; gap: .25rem; border-bottom: 1px solid #334155; margin-bottom: 1rem; flex-wrap: wrap; }
  .tabs button { padding: .35rem .7rem; font-size: .78rem; color: #94a3b8; border-bottom: 2px solid transparent;
    background: none; border-radius: 4px 4px 0 0; display: flex; align-items: center; gap: .3rem; }
  .tabs button.active { color: #60a5fa; border-bottom-color: #60a5fa; }
  .tabs button:hover:not(.active) { color: #e2e8f0; }
  .tc { font-size: .65rem; background: #334155; color: #94a3b8; border-radius: 999px; padding: 1px 4px; }

  .cards-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: .75rem; }
  .info-card { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: .75rem 1rem; }
  .card-title { font-size: .7rem; font-weight: 700; color: #64748b; text-transform: uppercase;
    letter-spacing: .05em; margin-bottom: .5rem; }
  .card-body { font-size: .78rem; color: #94a3b8; line-height: 1.5; margin-bottom: .5rem; }
  .card-link { font-size: .77rem; color: #60a5fa; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: .2rem .75rem; font-size: .77rem; margin-bottom: .5rem; }
  dt { color: #64748b; }
  dd { color: #e2e8f0; }

  .filter-bar { margin-bottom: .6rem; font-size: .77rem; color: #94a3b8; }
  .filter-bar select { background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
    border-radius: 4px; padding: .2rem .4rem; margin-left: .3rem; }

  .timeline { display: flex; flex-direction: column; gap: 0; }
  .tl-item { display: grid; grid-template-columns: 100px 1fr; gap: .5rem;
    padding: .3rem 0; border-bottom: 1px solid #1e293b; font-size: .77rem; }
  .tl-date { color: #64748b; white-space: nowrap; }
  .tl-body { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
  .tl-title { color: #cbd5e1; flex: 1; }
  .tl-src { font-size: .8rem; color: #60a5fa; }

  .data-table { width: 100%; border-collapse: collapse; font-size: .77rem; }
  .data-table th { background: #1e293b; color: #64748b; font-size: .65rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em; padding: .4rem .6rem;
    border-bottom: 1px solid #334155; text-align: left; }
  .data-table td { padding: .35rem .6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }
  .data-table tr:hover td { background: #1e293b; }
  .ent-link { color: #93c5fd; }
  .ent-link:hover { text-decoration: underline; }
  .rel-badge { font-size: .67rem; background: #334155; padding: 1px 5px; border-radius: 3px; color: #94a3b8; }
  .montant { font-weight: 700; color: #fb923c; }
  .muted { color: #64748b; }
  .objet-cell { max-width: 280px; }
  .err { color: #f87171; font-size: .83rem; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; }
</style>
