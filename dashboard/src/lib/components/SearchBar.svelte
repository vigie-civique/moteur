<script>
  import { api } from '$lib/api.js'
  import { searchResults, searchQuery, selectedEntity, activeTab } from '$lib/stores/app.js'

  let timer
  let loading = false

  async function onInput(e) {
    const q = e.target.value.trim()
    searchQuery.set(q)
    clearTimeout(timer)
    if (q.length < 2) { searchResults.set([]); return }
    timer = setTimeout(async () => {
      loading = true
      try {
        const r = await api.search(q)
        searchResults.set(Array.isArray(r) ? r : (r.results || []))
      } catch(_) {}
      loading = false
    }, 300)
  }

  function selectResult(item) {
    selectedEntity.set(item)
    activeTab.set('entity')
    searchResults.set([])
    searchQuery.set('')
  }

  import { TYPE_COLORS } from '$lib/stores/app.js'
</script>

<div class="search-wrap">
  <input
    type="search"
    placeholder="Rechercher une entité, personne, SIREN…"
    value={$searchQuery}
    on:input={onInput}
  />
  {#if $searchResults.length}
    <ul class="results">
      {#each $searchResults as item}
        <li on:click={() => selectResult(item)}>
          <span class="dot" style="background:{TYPE_COLORS[item.type] ?? '#666'}"></span>
          <span class="name">{item.name}</span>
          <span class="type">{item.type}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .search-wrap { position: relative; flex: 1; max-width: 420px; }

  input {
    width: 100%;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: .35rem .75rem;
    font-size: .85rem;
    color: #e2e8f0;
    outline: none;
  }
  input:focus { border-color: #3b82f6; }

  .results {
    position: absolute;
    top: 100%;
    left: 0; right: 0;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    max-height: 280px;
    overflow-y: auto;
    z-index: 9999;
    list-style: none;
    margin-top: 2px;
  }
  li {
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .4rem .75rem;
    cursor: pointer;
    font-size: .82rem;
  }
  li:hover { background: #0f172a; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .type { font-size: .7rem; color: #64748b; flex-shrink: 0; }
</style>
