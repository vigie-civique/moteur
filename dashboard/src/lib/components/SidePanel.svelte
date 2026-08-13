<script>
  import { activeTab, selectedEntity, stats, mapFocus } from '$lib/stores/app.js'
  import EntityCard   from './EntityCard.svelte'
  import AIPanel      from './AIPanel.svelte'
  import FeedPanel    from './FeedPanel.svelte'
  import ReviewPanel  from './ReviewPanel.svelte'
  import { api }      from '$lib/api.js'

  const TABS = [
    { key: 'sources', label: 'Sources' },
    { key: 'entity',  label: 'Entité'  },
    { key: 'reseau',  label: 'Réseau'  },
    { key: 'liens',   label: 'Liens'   },
    { key: 'ia',      label: 'IA'      },
  ]

  // Badge nombre de candidats en attente sur l'onglet Liens
  let pendingCount = 0
  async function loadPendingCount() {
    try {
      const d = await api.candidates('pending')
      pendingCount = d?.stats?.pending ?? 0
    } catch { /* silently ignore */ }
  }
  loadPendingCount()

  // Sources cards data
  const SOURCES = [
    { key: 'sirene',   label: 'SIRENE',        color: '#3b82f6', desc: 'Entreprises & dirigeants', available: true  },
    { key: 'rna',      label: 'RNA / JO',       color: '#10b981', desc: 'Associations',             available: true  },
    { key: 'dvf',      label: 'DVF',            color: '#f97316', desc: 'Transactions immobilières', available: true },
    { key: 'cm',       label: 'Conseil munic.', color: '#8b5cf6', desc: 'Délibérations CM',          available: true  },
    { key: 'osm',      label: 'OSM / POI',      color: '#f59e0b', desc: 'Lieux OpenStreetMap',       available: true  },
    { key: 'profiles', label: 'Profils',        color: '#ef4444', desc: 'Élus & entourage',          available: true  },
    { key: 'presse',   label: 'Presse',         color: '#06b6d4', desc: 'Objectif Gard, Le Grillon', available: false },
    { key: 'insee',    label: 'INSEE',          color: '#64748b', desc: 'Démographie, revenus',       available: false },
  ]

  // ── État liste source ──────────────────────────────────────────
  let selectedSource = null   // null = grille, string = liste ouverte
  let sourceItems    = []
  let sourceLoading  = false
  let sourceTotal    = 0

  function isSpurious(d) {
    return !d || d.startsWith('1900') || d.endsWith('-12-25') || d.endsWith('-01-01')
  }

  function sortByDate(a, b) {
    if (isSpurious(a) && isSpurious(b)) return 0
    if (isSpurious(a)) return 1
    if (isSpurious(b)) return -1
    return b < a ? -1 : b > a ? 1 : 0  // DESC
  }

  async function openSource(key) {
    if (!SOURCES.find(s => s.key === key)?.available) return
    selectedSource = key
    sourceLoading  = true
    sourceItems    = []

    try {
      switch (key) {
        case 'sirene': {
          const d = await api.entities({ type: 'business', limit: 2000 })
          sourceItems = (Array.isArray(d) ? d : (d.entities || [])).sort((a, b) =>
            sortByDate(a.creation_date, b.creation_date))
          break
        }
        case 'rna': {
          const d = await api.entities({ type: 'association', limit: 1000 })
          sourceItems = (Array.isArray(d) ? d : (d.entities || [])).sort((a, b) =>
            a.name.localeCompare(b.name, 'fr', { sensitivity: 'base' }))
          break
        }
        case 'dvf': {
          const d = await api.dvf('', 1000)
          sourceItems = Array.isArray(d) ? d : (d.transactions || [])
          break
        }
        case 'cm': {
          const d = await api.events('', 500)
          sourceItems = Array.isArray(d) ? d : (d.events || [])
          break
        }
        case 'osm': {
          const d = await api.entities({ type: 'place', limit: 500 })
          sourceItems = (Array.isArray(d) ? d : (d.entities || [])).sort((a, b) =>
            a.name.localeCompare(b.name, 'fr', { sensitivity: 'base' }))
          break
        }
        case 'profiles': {
          const d = await api.entities({ type: 'person', limit: 1000 })
          sourceItems = (Array.isArray(d) ? d : (d.entities || [])).sort((a, b) => {
            const la = (a.lastname || a.name).toUpperCase()
            const lb = (b.lastname || b.name).toUpperCase()
            return la.localeCompare(lb, 'fr', { sensitivity: 'base' })
          })
          break
        }
      }
    } catch(e) { console.warn('source', key, e) }

    sourceTotal   = sourceItems.length
    sourceLoading = false
  }

  function focusItem(item) {
    // Entités (SIRENE, RNA, OSM, Profils)
    if (item.id) {
      selectedEntity.set(item)
      activeTab.set('entity')
      if (item.lat && item.lng) mapFocus.set({ lat: item.lat, lng: item.lng, zoom: 17 })
    }
    // DVF : zoom uniquement
    else if (item.lat && item.lng) {
      mapFocus.set({ lat: item.lat, lng: item.lng, zoom: 17 })
    }
  }

  function formatDate(d) {
    if (!d) return '—'
    return d.slice(0, 10)
  }

  function formatPrice(n) {
    if (!n) return '—'
    return Number(n).toLocaleString('fr-FR') + ' €'
  }

  function currentSource() {
    return SOURCES.find(s => s.key === selectedSource)
  }

  // ── Réseau ────────────────────────────────────────────────────
  let graphData = null
  async function loadNetwork() {
    if ($selectedEntity?.id) {
      graphData = await api.graph($selectedEntity.id, 2)
    }
  }
  $: if ($activeTab === 'reseau' && $selectedEntity?.id) loadNetwork()
</script>

<aside class="side-panel">
  <!-- Onglets -->
  <nav class="tabs">
    {#each TABS as t}
      <button class:active={$activeTab === t.key} on:click={() => activeTab.set(t.key)}>
        {t.label}
        {#if t.key === 'entity' && $selectedEntity}
          <span class="dot-red"></span>
        {/if}
        {#if t.key === 'liens' && pendingCount > 0}
          <span class="dot-orange">{pendingCount}</span>
        {/if}
      </button>
    {/each}
  </nav>

  <div class="tab-content">
    <!-- ── Sources ─────────────────────────── -->
    {#if $activeTab === 'sources'}
      {#if !selectedSource}
        <!-- Grille des sources -->
        <div class="sources-grid">
          {#each SOURCES as s}
            <button
              class="source-card"
              class:unavailable={!s.available}
              style="border-left: 3px solid {s.color}"
              on:click={() => openSource(s.key)}
              disabled={!s.available}
              title={s.available ? `Ouvrir ${s.label}` : 'Données non encore collectées'}
            >
              <div class="src-label">{s.label}</div>
              <div class="src-desc">{s.desc}{s.available ? '' : ' — à venir'}</div>
            </button>
          {/each}
        </div>

        {#if $stats}
          <div class="stats-box">
            <div class="stat"><span>{$stats.entities ?? 0}</span><small>entités</small></div>
            <div class="stat"><span>{$stats.relations ?? 0}</span><small>relations</small></div>
            <div class="stat"><span>{$stats.events ?? 0}</span><small>événements CM</small></div>
            <div class="stat"><span>{$stats.dvf_transactions ?? 0}</span><small>DVF</small></div>
          </div>
        {/if}

        <FeedPanel />

      {:else}
        <!-- Liste d'une source -->
        <div class="list-header">
          <button class="back-btn" on:click={() => selectedSource = null}>← Retour</button>
          <span class="list-title" style="color: {currentSource()?.color}">
            {currentSource()?.label}
          </span>
          {#if !sourceLoading}
            <span class="list-count">{sourceTotal}</span>
          {/if}
        </div>

        {#if sourceLoading}
          <p class="hint">Chargement…</p>
        {:else if sourceItems.length === 0}
          <p class="hint">Aucune donnée disponible.</p>
        {:else}
          <div class="source-list">

            <!-- SIRENE -->
            {#if selectedSource === 'sirene'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => focusItem(item)}>
                  <div class="li-main">
                    <span class="li-name">{item.name}</span>
                    <span class="li-date" class:spurious={isSpurious(item.creation_date)}>
                      {isSpurious(item.creation_date) ? '?' : formatDate(item.creation_date)}
                    </span>
                  </div>
                  <div class="li-sub">
                    <span class="li-badge" class:active={item.biz_status === 'A'} class:closed={item.biz_status === 'F'}>
                      {item.biz_status === 'A' ? 'Active' : item.biz_status === 'F' ? 'Fermée' : '—'}
                    </span>
                    {#if item.naf_label}<span class="li-muted">{item.naf_label}</span>{/if}
                  </div>
                </button>
              {/each}

            <!-- RNA -->
            {:else if selectedSource === 'rna'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => focusItem(item)}>
                  <div class="li-main">
                    <span class="li-name">{item.name}</span>
                    <span class="li-date" class:spurious={isSpurious(item.asso_creation_date)}>
                      {isSpurious(item.asso_creation_date) ? '?' : formatDate(item.asso_creation_date)}
                    </span>
                  </div>
                  {#if item.asso_object}
                    <div class="li-sub"><span class="li-muted">{item.asso_object.slice(0, 60)}</span></div>
                  {/if}
                </button>
              {/each}

            <!-- DVF -->
            {:else if selectedSource === 'dvf'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => focusItem(item)}>
                  <div class="li-main">
                    <span class="li-name">{item.lieu_dit || item.nature_bien || 'Mutation'}</span>
                    <span class="li-date">{formatDate(item.date)}</span>
                  </div>
                  <div class="li-sub">
                    <span class="li-price">{formatPrice(item.price)}</span>
                    {#if item.nature_bien}<span class="li-muted">{item.nature_bien}</span>{/if}
                    {#if item.surface_terrain}<span class="li-muted">{item.surface_terrain} m²</span>{/if}
                  </div>
                </button>
              {/each}

            <!-- CM -->
            {:else if selectedSource === 'cm'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => item.source_url && window.open(item.source_url, '_blank')}>
                  <div class="li-main">
                    <span class="li-name">{item.title}</span>
                    <span class="li-date">{formatDate(item.date)}</span>
                  </div>
                  <div class="li-sub">
                    <span class="li-muted">{item.type}</span>
                    {#if item.source_url}<span class="li-link">→ CR</span>{/if}
                  </div>
                </button>
              {/each}

            <!-- OSM / POI -->
            {:else if selectedSource === 'osm'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => focusItem(item)}>
                  <div class="li-main">
                    <span class="li-name">{item.name}</span>
                    {#if item.osm_value}<span class="li-badge-neutral">{item.osm_value}</span>{/if}
                  </div>
                  {#if item.address}
                    <div class="li-sub"><span class="li-muted">{item.address}</span></div>
                  {/if}
                </button>
              {/each}

            <!-- Profils -->
            {:else if selectedSource === 'profiles'}
              {#each sourceItems as item}
                <button class="list-item" on:click={() => focusItem(item)}>
                  <div class="li-main">
                    <span class="li-name">
                      {item.lastname ? `${item.lastname}${item.firstname ? ', ' + item.firstname : ''}` : item.name}
                    </span>
                  </div>
                  {#if item.address}
                    <div class="li-sub"><span class="li-muted">{item.address}</span></div>
                  {/if}
                </button>
              {/each}
            {/if}

          </div>
        {/if}
      {/if}
    {/if}

    <!-- ── Entité ───────────────────────────── -->
    {#if $activeTab === 'entity'}
      <EntityCard entity={$selectedEntity} />
    {/if}

    <!-- ── Réseau ──────────────────────────── -->
    {#if $activeTab === 'reseau'}
      {#if !$selectedEntity}
        <p class="hint">Sélectionnez une entité pour voir son réseau.</p>
      {:else if graphData}
        <div class="network-summary">
          <p><strong>{graphData.nodes?.length ?? 0}</strong> nœuds, <strong>{graphData.edges?.length ?? 0}</strong> liens (profondeur 2)</p>
          {#if graphData.edges?.length}
            <ul class="edge-list">
              {#each graphData.edges.slice(0, 30) as e}
                {@const src = graphData.nodes?.find(n => n.id === e.from_id)}
                {@const tgt = graphData.nodes?.find(n => n.id === e.to_id)}
                <li>
                  <span class="en">{src?.name ?? e.from_id}</span>
                  <span class="rt">{e.relation_type}</span>
                  <span class="en">{tgt?.name ?? e.to_id}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {:else}
        <p class="hint">Chargement réseau…</p>
      {/if}
    {/if}

    <!-- ── Liens à valider ─────────────────── -->
    {#if $activeTab === 'liens'}
      <ReviewPanel />
    {/if}

    <!-- ── IA ──────────────────────────────── -->
    {#if $activeTab === 'ia'}
      <AIPanel />
    {/if}
  </div>
</aside>

<style>
  .side-panel {
    width: 340px;
    min-width: 280px;
    background: #1e293b;
    border-left: 1px solid #334155;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    flex-shrink: 0;
  }

  .tabs {
    display: flex;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .tabs button {
    flex: 1;
    padding: .5rem .25rem;
    font-size: .78rem;
    color: #64748b;
    border-bottom: 2px solid transparent;
    transition: all .15s;
    position: relative;
  }
  .tabs button.active { color: #e2e8f0; border-bottom-color: #3b82f6; }
  .dot-red {
    position: absolute;
    top: 4px; right: 4px;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #ef4444;
  }
  .dot-orange {
    position: absolute;
    top: 2px; right: 2px;
    min-width: 14px;
    padding: 0 3px;
    height: 14px;
    border-radius: 999px;
    background: #f59e0b;
    color: #000;
    font-size: .6rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .tab-content {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  /* Sources — grille */
  .sources-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: .5rem;
    padding: .75rem;
  }
  .source-card {
    background: #0f172a;
    border-radius: 6px;
    padding: .5rem .75rem;
    text-align: left;
    cursor: pointer;
    transition: background .15s;
    width: 100%;
  }
  .source-card:hover:not(:disabled) { background: #1e293b; }
  .source-card.unavailable { opacity: .4; cursor: not-allowed; }
  .src-label { font-size: .78rem; font-weight: 600; color: #e2e8f0; }
  .src-desc  { font-size: .68rem; color: #475569; margin-top: 2px; }

  /* Sources — liste */
  .list-header {
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .5rem .75rem;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .back-btn {
    font-size: .75rem;
    color: #60a5fa;
    padding: .2rem .5rem;
    border: 1px solid #334155;
    border-radius: 4px;
    cursor: pointer;
    background: transparent;
    flex-shrink: 0;
  }
  .back-btn:hover { background: #1e293b; }
  .list-title { font-size: .82rem; font-weight: 600; flex: 1; }
  .list-count {
    font-size: .7rem; color: #475569;
    background: #0f172a; border-radius: 999px;
    padding: .1rem .45rem;
  }

  .source-list { overflow-y: auto; flex: 1; }

  .list-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: .45rem .75rem;
    border-bottom: 1px solid #0f172a;
    cursor: pointer;
    background: transparent;
    transition: background .1s;
  }
  .list-item:hover { background: #1e293b; }

  .li-main {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: .5rem;
  }
  .li-name {
    font-size: .78rem;
    color: #cbd5e1;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .li-date { font-size: .7rem; color: #475569; flex-shrink: 0; }
  .li-date.spurious { color: #dc2626; }

  .li-sub {
    display: flex;
    gap: .4rem;
    margin-top: .2rem;
    flex-wrap: wrap;
    align-items: center;
  }
  .li-muted { font-size: .68rem; color: #475569; }
  .li-price { font-size: .72rem; color: #10b981; font-weight: 600; }
  .li-link  { font-size: .68rem; color: #60a5fa; }

  .li-badge {
    font-size: .65rem; font-weight: 700;
    padding: .05rem .3rem;
    border-radius: 3px;
  }
  .li-badge.active { background: #0d2e1f; color: #34d399; }
  .li-badge.closed { background: #2d0f0f; color: #f87171; }
  .li-badge-neutral {
    font-size: .65rem; color: #94a3b8;
    background: #1e293b; border-radius: 3px;
    padding: .05rem .3rem; flex-shrink: 0;
  }

  .stats-box {
    display: flex;
    justify-content: space-around;
    padding: .5rem 1rem;
    border-top: 1px solid #334155;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .stat { text-align: center; }
  .stat span { font-size: 1.1rem; font-weight: 700; color: #60a5fa; }
  .stat small { display: block; font-size: .65rem; color: #64748b; }

  /* Réseau */
  .network-summary { padding: .75rem; font-size: .82rem; }
  .edge-list { list-style: none; margin-top: .5rem; }
  .edge-list li {
    display: flex;
    gap: .4rem;
    padding: .2rem 0;
    border-bottom: 1px solid #1e293b;
    font-size: .75rem;
    flex-wrap: wrap;
  }
  .en { color: #cbd5e1; }
  .rt { color: #f59e0b; font-style: italic; }

  .hint { color: #475569; font-size: .82rem; padding: 1rem; }
</style>
