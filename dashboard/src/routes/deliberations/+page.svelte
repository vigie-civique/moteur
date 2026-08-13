<script>
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  let events = []
  let filter = ''
  let query = ''
  let searchTimer
  let loading = true

  const CATEGORIES = [
    '', 'subvention', 'budget', 'ressources_humaines', 'travaux',
    'cession_patrimoine', 'bail_loyer', 'urbanisme', 'marche_public',
    'convention', 'remuneration', 'fiscalite', 'environnement',
    'sante', 'petite_enfance', 'cantine', 'information'
  ]
  const CIVIC_TYPES = new Set([
    'conseil_municipal',
    'deliberation',
    'délibérations_cc',
    'pv_cc',
    'marché_public',
    'election',
  ])

  onMount(async () => {
    try {
      const d = await api.events('', 500)
      events = Array.isArray(d) ? d : (d.events || [])
    } catch(e) { console.warn(e) }
    loading = false
  })

  async function onSearchInput() {
    clearTimeout(searchTimer)
    const q = query.trim()
    if (q.length < 2) {
      loading = true
      try {
        const d = await api.events('', 500)
        events = Array.isArray(d) ? d : (d.events || [])
      } catch(e) { console.warn(e) }
      loading = false
      return
    }
    searchTimer = setTimeout(async () => {
      loading = true
      try {
        const d = await api.eventSearch(q, 200, true)
        events = Array.isArray(d) ? d : (d.events || [])
      } catch(e) { console.warn(e) }
      loading = false
    }, 250)
  }

  $: civicEvents = events.filter(e => CIVIC_TYPES.has(e.type))

  $: filtered = filter
    ? civicEvents.filter(e => {
        try { return meta(e)?.categorie === filter } catch { return false }
      })
    : civicEvents

  function fmtDate(d) { return d ? d.slice(0, 10) : '' }

  function meta(ev) {
    if (!ev?.metadata) return {}
    if (typeof ev.metadata === 'string') {
      try { return JSON.parse(ev.metadata) } catch { return {} }
    }
    return ev.metadata
  }

  function extractVote(meta) {
    if (!meta) return null
    const p = meta.vote_pour ?? meta.pour
    const c = meta.vote_contre ?? meta.contre
    const a = meta.vote_abstention ?? meta.abstention
    if (p == null && c == null) return null
    return `${p ?? '?'} pour / ${c ?? 0} contre / ${a ?? 0} abst.`
  }

  function extractMontant(meta) {
    if (!meta) return null
    const m = meta.montant ?? meta.amount
    return m ? Number(m).toLocaleString('fr-FR') + ' EUR' : null
  }

  function pdfUrl(ev) {
    const m = meta(ev)
    if (m.pdf_url || m.pdf_urls?.[0]?.url) return m.pdf_url || m.pdf_urls[0].url
    return ev.source_url?.toLowerCase().includes('.pdf') ? ev.source_url : ''
  }

  function pageUrl(ev) {
    const m = meta(ev)
    if (m.page_url) return m.page_url
    return ev.source_url?.toLowerCase().includes('.pdf') ? '' : (ev.source_url || '')
  }

  function snippet(ev) {
    return ev.snippet || ev.content || ''
  }
</script>

<svelte:head>
  <title>Deliberations — Lasalle</title>
</svelte:head>

<div class="page">
  <div class="toolbar">
    <h1>Deliberations du conseil municipal</h1>
    <input
      type="search"
      bind:value={query}
      on:input={onSearchInput}
      placeholder="Rechercher dans les CR PDF..."
    />
    <select bind:value={filter}>
      <option value="">Toutes les categories</option>
      {#each CATEGORIES.filter(c => c) as c}
        <option value={c}>{c.replace(/_/g, ' ')}</option>
      {/each}
    </select>
    <span class="count">{filtered.length} deliberation{filtered.length > 1 ? 's' : ''}</span>
  </div>

  {#if loading}
    <p class="hint">Chargement...</p>
  {:else}
    <div class="list">
      {#each filtered as ev}
        <article class="delib">
          <div class="delib-head">
            <span class="date">{fmtDate(ev.date)}</span>
            {#if meta(ev)?.categorie}
              <span class="cat">{meta(ev).categorie.replace(/_/g, ' ')}</span>
            {/if}
            {#if extractMontant(meta(ev))}
              <span class="montant">{extractMontant(meta(ev))}</span>
            {/if}
          </div>
          <h2>{ev.title || 'Sans titre'}</h2>
          {#if extractVote(meta(ev))}
            <div class="vote">{extractVote(meta(ev))}</div>
          {/if}
          {#if query.trim().length >= 2 && snippet(ev)}
            <p class="snippet">{@html snippet(ev)}</p>
          {/if}
          <div class="links">
            {#if pdfUrl(ev)}
              <a href={pdfUrl(ev)} target="_blank" rel="noopener">PDF</a>
            {/if}
            {#if pageUrl(ev)}
              <a href={pageUrl(ev)} target="_blank" rel="noopener">Page mairie</a>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .page {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    width: 100%;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: .75rem 1.5rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  h1 { font-size: 1rem; font-weight: 700; }
  input,
  select {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #e2e8f0;
    font-size: .8rem;
    padding: .3rem .6rem;
  }
  input {
    width: min(360px, 100%);
  }
  .count { color: #64748b; font-size: .8rem; margin-left: auto; }

  .list {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }
  .delib {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: .75rem 1rem;
  }
  .delib-head {
    display: flex;
    gap: .5rem;
    align-items: center;
    margin-bottom: .35rem;
    flex-wrap: wrap;
  }
  .date { color: #64748b; font-size: .78rem; }
  .cat {
    background: #0f172a;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: .7rem;
    color: #94a3b8;
  }
  .montant {
    color: #10b981;
    font-weight: 600;
    font-size: .8rem;
  }
  h2 { font-size: .88rem; font-weight: 600; line-height: 1.35; }
  .vote { font-size: .78rem; color: #f59e0b; margin-top: .25rem; }
  .snippet {
    margin-top: .4rem;
    color: #94a3b8;
    font-size: .78rem;
    line-height: 1.45;
  }
  :global(mark) {
    background: #f59e0b;
    color: #0f172a;
    border-radius: 3px;
    padding: 0 2px;
  }
  .links {
    display: flex;
    gap: .6rem;
    flex-wrap: wrap;
    margin-top: .25rem;
  }
  a { font-size: .75rem; display: inline-block; }
  .hint { color: #475569; padding: 2rem; text-align: center; }
</style>
