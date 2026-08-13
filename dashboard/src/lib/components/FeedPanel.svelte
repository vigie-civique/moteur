<script>
  import { feedItems, selectedEntity, activeTab } from '$lib/stores/app.js'
  import { api } from '$lib/api.js'

  let flows = []
  let dvfTx = []
  let activeSection = 'events'

  async function loadFlows() {
    try { const r = await api.flows(); flows = Array.isArray(r) ? r : (r.flows || []) } catch(_) {}
  }
  async function loadDVF() {
    try { const r = await api.dvf('', 30); dvfTx = Array.isArray(r) ? r : (r.transactions || []) } catch(_) {}
  }

  function setSection(s) {
    activeSection = s
    if (s === 'flows' && !flows.length) loadFlows()
    if (s === 'dvf'   && !dvfTx.length) loadDVF()
  }

  function fmtDate(d) { return d ? d.slice(0, 10) : '' }
  function fmtPrice(n) { return n ? Number(n).toLocaleString('fr-FR') + ' €' : 'N/A' }

  const EV_ICONS = {
    deliberation: '📋',
    subvention:   '💰',
    election:     '🗳',
    bail:         '🏠',
  }
</script>

<div class="feed">
  <!-- Tabs -->
  <div class="tabs">
    {#each [['events','Délibérations'],['flows','Flux financiers'],['dvf','Transactions DVF']] as [k, l]}
      <button class:active={activeSection === k} on:click={() => setSection(k)}>{l}</button>
    {/each}
  </div>

  <!-- Événements CM -->
  {#if activeSection === 'events'}
    <ul class="list">
      {#each $feedItems as ev}
        <li>
          <span class="icon">{EV_ICONS[ev.type] ?? '•'}</span>
          <div class="body">
            <div class="title">{ev.title || ev.type}</div>
            <div class="meta">
              {fmtDate(ev.date)}
              {#if ev.source_url}<a href={ev.source_url} target="_blank">CR ↗</a>{/if}
            </div>
          </div>
        </li>
      {:else}
        <li class="empty">Aucun événement chargé.</li>
      {/each}
    </ul>
  {/if}

  <!-- Flux financiers -->
  {#if activeSection === 'flows'}
    <ul class="list">
      {#each flows as f}
        <li>
          <div class="body">
            <div class="title">
              {f.from_name || '?'} → {f.to_name || '?'}
            </div>
            <div class="meta">
              {f.year} · <strong class="amount">{fmtPrice(f.amount)}</strong>
              · {f.type}
              {#if f.description}<span class="desc"> — {f.description}</span>{/if}
            </div>
          </div>
        </li>
      {:else}
        <li class="empty">Cliquez sur l'onglet pour charger.</li>
      {/each}
    </ul>
  {/if}

  <!-- DVF -->
  {#if activeSection === 'dvf'}
    <ul class="list">
      {#each dvfTx as t}
        <li>
          <div class="body">
            <div class="title">{t.nature_mutation} — {fmtPrice(t.price)}</div>
            <div class="meta">
              {fmtDate(t.date)} · {t.nature_bien || ''}
              {t.surface_terrain ? ' · ' + t.surface_terrain + ' m²' : ''}
              {t.price_per_m2 ? ' · ' + Math.round(t.price_per_m2) + ' €/m²' : ''}
            </div>
            {#if t.lieu_dit}<div class="addr">{t.lieu_dit}</div>{/if}
          </div>
        </li>
      {:else}
        <li class="empty">Cliquez sur l'onglet pour charger.</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .feed { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

  .tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .tabs button {
    flex: 1;
    padding: .4rem .5rem;
    font-size: .72rem;
    color: #64748b;
    border-bottom: 2px solid transparent;
    transition: all .15s;
    white-space: nowrap;
  }
  .tabs button.active { color: #60a5fa; border-bottom-color: #3b82f6; }

  .list {
    list-style: none;
    overflow-y: auto;
    flex: 1;
  }
  li {
    display: flex;
    gap: .5rem;
    padding: .55rem .75rem;
    border-bottom: 1px solid #1e293b;
    font-size: .78rem;
  }
  .icon { flex-shrink: 0; font-size: 1rem; }
  .body { flex: 1; min-width: 0; }
  .title { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { color: #64748b; font-size: .72rem; margin-top: 2px; }
  .meta a { color: #60a5fa; }
  .amount { color: #10b981; }
  .desc { color: #475569; }
  .addr { color: #475569; font-size: .7rem; }
  .empty { color: #334155; font-style: italic; }
</style>
