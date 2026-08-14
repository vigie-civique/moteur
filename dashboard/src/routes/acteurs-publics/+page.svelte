<script>
  import { COMMUNE_DE, SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  let entities = []
  let loading  = true
  let error    = ''
  let search   = ''

  const TYPE_FILTER = ['service', 'place', 'association', 'business']
  let typeFilter = 'all'

  onMount(async () => {
    loading = true
    try {
      // Services publics + lieux + associations d'intérêt public
      const all = await api.entities({ limit: 500 })
      entities = Array.isArray(all) ? all.filter(e =>
        e.type === 'service' ||
        (e.type === 'place' && e.osm_category) ||
        (e.type === 'association')
      ) : []
    } catch(e) { error = e.message }
    finally { loading = false }
  })

  $: filtered = entities.filter(e => {
    const matchType = typeFilter === 'all' || e.type === typeFilter
    const q = search.toLowerCase()
    const matchSearch = !q || e.name?.toLowerCase().includes(q)
    return matchType && matchSearch
  })

  $: counts = {
    service:     entities.filter(e => e.type === 'service').length,
    place:       entities.filter(e => e.type === 'place').length,
    association: entities.filter(e => e.type === 'association').length,
  }

  const TYPE_LABELS = { service: 'Service public', place: 'Lieu', association: 'Association' }
  const TYPE_COLORS = { service: '#92400e', place: '#4c1d95', association: '#065f46' }
</script>

<svelte:head><title>Acteurs publics — {SITE_NOM}</title></svelte:head>

<div class="ap-page">
  <div class="page-header">
    <h1>Acteurs publics</h1>
    <span class="subtitle">Services, lieux publics et associations {COMMUNE_DE}</span>
  </div>

  <div class="controls">
    <input bind:value={search} placeholder="Rechercher…" class="search-input" />
    <div class="type-btns">
      <button class:active={typeFilter==='all'} on:click={() => typeFilter='all'}>
        Tous ({entities.length})
      </button>
      {#each ['service','place','association'] as t}
        <button class:active={typeFilter===t} on:click={() => typeFilter=t}
                style="--c:{TYPE_COLORS[t]}">
          {TYPE_LABELS[t]} ({counts[t]})
        </button>
      {/each}
    </div>
  </div>

  {#if error}<p class="err">{error}</p>{/if}

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else if filtered.length === 0}
    <p class="muted-center">Aucun résultat.</p>
  {:else}
    <div class="entity-grid">
      {#each filtered as e}
        <a href="/entite/{e.id}" class="entity-card">
          <div class="card-header">
            <span class="type-dot" style="background:{TYPE_COLORS[e.type] ?? '#334155'}"></span>
            <span class="type-label">{TYPE_LABELS[e.type] ?? e.type}</span>
          </div>
          <div class="card-name">{e.name}</div>
          {#if e.address}
            <div class="card-addr muted">{e.address}</div>
          {/if}
          {#if e.service_category || e.osm_category}
            <div class="card-cat muted">{e.service_category ?? e.osm_category}</div>
          {/if}
        </a>
      {/each}
    </div>
  {/if}
</div>

<style>
  .ap-page { padding: 1.2rem; max-width: 1100px; overflow-y: auto; }
  .page-header { margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .subtitle { font-size: .78rem; color: #64748b; }

  .controls { display: flex; align-items: center; gap: .75rem; margin-bottom: .85rem; flex-wrap: wrap; }
  .search-input { background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
    border-radius: 6px; padding: .3rem .65rem; font-size: .8rem; width: 220px; }
  .search-input:focus { outline: none; border-color: #3b82f6; }
  .type-btns { display: flex; gap: .3rem; flex-wrap: wrap; }
  .type-btns button { background: #1e293b; border: 1px solid #334155; color: #94a3b8;
    border-radius: 5px; padding: .25rem .55rem; font-size: .75rem; cursor: pointer; }
  .type-btns button.active { border-color: var(--c, #3b82f6); color: #e2e8f0; }

  .entity-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap: .5rem; }
  .entity-card { background: #1e293b; border: 1px solid #334155; border-radius: 7px;
    padding: .6rem .75rem; text-decoration: none; display: block; transition: border-color .12s; }
  .entity-card:hover { border-color: #60a5fa; }
  .card-header { display: flex; align-items: center; gap: .35rem; margin-bottom: .3rem; }
  .type-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .type-label { font-size: .65rem; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }
  .card-name { font-size: .82rem; font-weight: 600; color: #e2e8f0; line-height: 1.3; }
  .card-addr, .card-cat { font-size: .71rem; margin-top: .2rem;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .muted { color: #64748b; }

  .err { color: #f87171; font-size: .83rem; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; }
</style>
