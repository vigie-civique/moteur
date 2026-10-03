<script>
  import { api } from '$lib/api.js'
  import { TYPE_COLORS } from '$lib/stores/app.js'

  const CONF_LABELS  = { probable: 'probable', hypothesis: 'hypothèse' }
  const CONF_COLORS  = { probable: 'var(--alerte)',  hypothesis: 'var(--texte-doux)' }
  const STATUS_TABS  = [
    { key: 'pending',  label: 'En attente' },
    { key: 'accepted', label: 'Validés'    },
    { key: 'rejected', label: 'Rejetés'    },
    { key: 'ignored',  label: 'Ignorés'    },
  ]

  let status      = 'pending'
  let filterSignal = ''
  let data        = null
  let loading     = false
  let noteMap     = {}   // cid → note text

  async function load() {
    loading = true
    try {
      data = await api.candidates(status, filterSignal)
    } finally {
      loading = false
    }
  }

  async function review(cid, action) {
    await api.reviewCandidate(cid, action, noteMap[cid] || '')
    await load()
  }

  $: status, filterSignal, load()

  $: stats   = data?.stats   ?? {}
  $: signals = data?.signal_labels ?? {}
  $: items   = data?.candidates ?? []

  function pending()  { return stats.pending  ?? 0 }
  function accepted() { return stats.accepted ?? 0 }
</script>

<div class="review-panel">
  <!-- Stats globales -->
  <div class="stats-bar">
    <span class="stat-item s-pending">{stats.pending ?? 0} en attente</span>
    <span class="stat-item s-ok">{stats.accepted ?? 0} validés</span>
    <span class="stat-item s-ko">{stats.rejected ?? 0} rejetés</span>
    <span class="stat-item s-ign">{stats.ignored ?? 0} ignorés</span>
  </div>

  <!-- Filtres -->
  <div class="filters">
    <div class="tab-row">
      {#each STATUS_TABS as t}
        <button class="tab-btn" class:active={status === t.key}
                on:click={() => status = t.key}>
          {t.label}
        </button>
      {/each}
    </div>
    <select class="sig-filter" bind:value={filterSignal}>
      <option value=''>Tous les signaux</option>
      {#each Object.entries(signals) as [key, label]}
        <option value={key}>{label}</option>
      {/each}
    </select>
  </div>

  <!-- Liste -->
  {#if loading}
    <p class="hint">Chargement…</p>
  {:else if !items.length}
    <p class="hint">Aucun candidat dans cette catégorie.</p>
  {:else}
    <div class="list">
      {#each items as c (c.id)}
        <div class="card">
          <!-- Score + type de signal -->
          <div class="card-head">
            <span class="score" style="--s:{c.score}%">{c.score}</span>
            <span class="sig-badge">{signals[c.signal] ?? c.signal}</span>
            <span class="conf-badge"
                  style="color:{CONF_COLORS[c.confidence]}">
              {CONF_LABELS[c.confidence]}
            </span>
          </div>

          <!-- Entités -->
          <div class="entities">
            <span class="ent" style="border-color:{TYPE_COLORS[c.from_type] ?? 'var(--serie-gris)'}">
              {c.from_name}
            </span>
            <span class="rel-type">{c.relation_type}</span>
            <span class="ent" style="border-color:{TYPE_COLORS[c.to_type] ?? 'var(--serie-gris)'}">
              {c.to_name}
            </span>
          </div>

          <!-- Détail du signal -->
          <p class="detail">{c.signal_detail}</p>

          <!-- Actions (seulement en attente) -->
          {#if c.review_status === 'pending'}
            <div class="actions">
              <input type="text" placeholder="Note (optionnel)"
                     bind:value={noteMap[c.id]} class="note-input" />
              <button class="btn-ok" on:click={() => review(c.id, 'accept')}>✓ Valider</button>
              <button class="btn-ko" on:click={() => review(c.id, 'reject')}>✗ Rejeter</button>
              <button class="btn-ign" on:click={() => review(c.id, 'ignore')}>— Ignorer</button>
            </div>
          {:else}
            <p class="reviewed">
              {c.review_status} {c.reviewed_at ? `· ${c.reviewed_at.slice(0,10)}` : ''}
              {#if c.review_note} · <em>{c.review_note}</em>{/if}
            </p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .review-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .stats-bar {
    display: flex;
    gap: .5rem;
    padding: .5rem .75rem;
    border-bottom: 1px solid var(--bordure);
    flex-shrink: 0;
    flex-wrap: wrap;
    font-size: .7rem;
  }
  .stat-item { padding: 1px 6px; border-radius: 999px; }
  .s-pending { background:var(--info-doux); color:var(--lien); }
  .s-ok      { background:var(--succes-bordure); color:var(--succes-texte); }
  .s-ko      { background:var(--danger-doux); color:var(--danger); }
  .s-ign     { background:var(--surface); color:var(--texte-doux); }

  .filters {
    padding: .4rem .75rem;
    border-bottom: 1px solid var(--bordure);
    display: flex;
    flex-direction: column;
    gap: .35rem;
    flex-shrink: 0;
  }
  .tab-row { display: flex; gap: .25rem; }
  .tab-btn {
    padding: .15rem .5rem;
    border-radius: 4px;
    font-size: .72rem;
    color: var(--texte-doux);
    background: var(--fond);
    border: 1px solid var(--bordure);
  }
  .tab-btn.active { background: var(--accent-fort); color: var(--sur-accent); border-color: var(--accent-fort); }
  .sig-filter {
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 4px;
    color: var(--texte);
    font-size: .72rem;
    padding: 2px 6px;
  }

  .list {
    flex: 1;
    overflow-y: auto;
    padding: .5rem .75rem;
    display: flex;
    flex-direction: column;
    gap: .5rem;
  }

  .card {
    background: var(--fond);
    border: 1px solid var(--bordure-douce);
    border-radius: 6px;
    padding: .55rem .65rem;
    display: flex;
    flex-direction: column;
    gap: .3rem;
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: .4rem;
    flex-wrap: wrap;
  }
  .score {
    min-width: 28px;
    text-align: center;
    font-size: .75rem;
    font-weight: 700;
    padding: 1px 5px;
    border-radius: 4px;
    /* Dégradé rouge → vert selon le score */
    background: color-mix(in srgb,
      var(--succes) calc(var(--s)),
      var(--danger) calc(100% - var(--s)));
    color: var(--sur-vif);
  }
  .sig-badge {
    font-size: .68rem;
    background: var(--surface);
    color: var(--texte-doux);
    padding: 1px 6px;
    border-radius: 999px;
  }
  .conf-badge { font-size: .68rem; font-style: italic; }

  .entities {
    display: flex;
    align-items: center;
    gap: .35rem;
    flex-wrap: wrap;
  }
  .ent {
    font-size: .73rem;
    color: var(--texte);
    padding: 1px 6px;
    border-radius: 4px;
    border-left: 3px solid;
    background: var(--surface);
    max-width: 130px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .rel-type {
    font-size: .68rem;
    color: var(--alerte);
    font-style: italic;
    white-space: nowrap;
  }

  .detail {
    font-size: .68rem;
    color: var(--texte-doux);
    line-height: 1.3;
  }

  .actions {
    display: flex;
    gap: .3rem;
    flex-wrap: wrap;
    align-items: center;
    margin-top: .1rem;
  }
  .note-input {
    flex: 1;
    min-width: 80px;
    background: var(--surface);
    border: 1px solid var(--bordure);
    border-radius: 4px;
    color: var(--texte);
    font-size: .68rem;
    padding: 2px 6px;
  }
  .btn-ok, .btn-ko, .btn-ign {
    font-size: .7rem;
    padding: .2rem .5rem;
    border-radius: 4px;
    white-space: nowrap;
  }
  .btn-ok  { background: var(--succes-bordure); color: var(--succes-texte); }
  .btn-ko  { background: var(--danger-doux); color: var(--danger-texte); }
  .btn-ign { background: var(--surface); color: var(--texte-doux); }
  .btn-ok:hover  { background: var(--succes-bordure); }
  .btn-ko:hover  { background: var(--danger-bordure); }
  .btn-ign:hover { background: var(--surface-2); }

  .reviewed {
    font-size: .68rem;
    color: var(--texte-doux);
    font-style: italic;
  }

  .hint { color: var(--texte-doux); font-size: .82rem; padding: .75rem; }
</style>
