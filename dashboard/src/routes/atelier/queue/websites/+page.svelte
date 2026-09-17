<script>
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'

  // Qui réserve, c'est le compte connecté : l'API ne lit plus le nom envoyé.
  $: me = $currentUser?.email || ''
  $: admin = $currentUser?.role === 'admin'
  let avis = ''         // ce qu'une action n'a pas pu faire — à la place d'un alert() bloquant

  let candidates   = []
  let loading      = true
  let error        = ''
  let statusFilter = 'candidate'
  let saving       = {}
  let claiming     = {}  // {id: true} pendant le claim

  onMount(() => load())

  async function load() {
    loading = true; error = ''
    try {
      const res = await authFetch(`/atelier/queue/websites?status=${statusFilter}&limit=200`)
      if (!res.ok) throw new Error(res.status)
      candidates = await res.json()
    } catch(e) { error = e.message }
    finally { loading = false }
  }

  // Le détail d'une erreur de l'API : un objet { message, par, … } ou une chaîne.
  async function motif(res, defaut) {
    const d = (await res.json().catch(() => ({}))).detail
    return (typeof d === 'object' ? d?.message : d) || defaut
  }

  async function setStatus(id, status) {
    saving = { ...saving, [id]: true }
    avis = ''
    try {
      const res = await authFetch(`/atelier/websites/${id}`, {
        method: 'PATCH', body: JSON.stringify({ status })
      })
      if (res.ok) candidates = candidates.filter(c => c.id !== id)
      else {
        avis = await motif(res, `Échec de l'enregistrement (${res.status}).`)
        if (res.status === 409) await load()
      }
    } finally {
      const s = { ...saving }; delete s[id]; saving = s
    }
  }

  async function claimItem(id) {
    claiming = { ...claiming, [id]: true }
    try {
      avis = ''
      const res = await authFetch(`/atelier/queue/${id}/claim`, {
        method: 'POST',
        body: JSON.stringify({ table: 'entity_websites' }),
      })
      if (res.ok) {
        const r = await res.json()
        candidates = candidates.map(c =>
          c.id === id ? { ...c, reservation: { par: r.locked_by, expire_dans_min: r.expires_in_min } } : c
        )
      } else {
        avis = await motif(res, `Réservation impossible (${res.status}).`)
        if (res.status === 409) await load()
      }
    } finally {
      const cl = { ...claiming }; delete cl[id]; claiming = cl
    }
  }

  async function liberer(id) {
    avis = ''
    const res = await authFetch(`/atelier/queue/${id}/claim?table=entity_websites`, { method: 'DELETE' })
    if (res.ok) candidates = candidates.map(c => c.id === id ? { ...c, reservation: null } : c)
    else avis = await motif(res, `Libération impossible (${res.status}).`)
  }

  function scoreColor(s) {
    if (!s) return '#64748b'
    if (s >= 0.7) return '#22c55e'
    if (s >= 0.5) return '#f59e0b'
    return '#f87171'
  }

  $: typeGroups = candidates.reduce((acc, c) => {
    acc[c.entity_type] = (acc[c.entity_type] || [])
    acc[c.entity_type].push(c)
    return acc
  }, {})
</script>

<svelte:head><title>Queue — Websites candidats</title></svelte:head>

<div class="queue-page">
  <div class="queue-header">
    <h1>Websites candidats</h1>
    <div class="queue-controls">
      <select bind:value={statusFilter} on:change={load}>
        <option value="candidate">candidate</option>
        <option value="validated">validated</option>
        <option value="rejected">rejected</option>
      </select>
      <button class="btn-reload" on:click={load}>↺ Recharger</button>
      <span class="count-info">{candidates.length} URL{candidates.length !== 1 ? 's' : ''}</span>
    </div>
  </div>

  {#if error}<p class="err-msg">{error}</p>{/if}
  {#if avis}<p class="avis" role="status">{avis}</p>{/if}
  {#if loading}<p class="muted-center">Chargement…</p>
  {:else if candidates.length === 0}
    <p class="muted-center">Aucune URL avec le statut "{statusFilter}".</p>
  {:else}
    <div class="candidate-list">
      {#each candidates as c (c.id)}
        <div class="candidate-row" class:low-score={c.score < 0.5}>
          <div class="cand-entity">
            <a href="/atelier/entite/{c.entity_id}" class="entity-link">{c.entity_name}</a>
            <span class="type-badge type-{c.entity_type}">{c.entity_type}</span>
          </div>
          <a href={c.url} target="_blank" rel="noopener" class="cand-url">{c.url}</a>
          <span class="cand-score" style="color:{scoreColor(c.score)}">
            {c.score != null ? c.score.toFixed(2) : '—'}
          </span>
          <span class="cand-source muted">{c.found_by}</span>
          {#if c.reservation}
            <span class="cand-lock" title="Réservé encore {c.reservation.expire_dans_min} min">
              🔒 {c.reservation.par === me ? 'vous' : c.reservation.par}
              {#if c.reservation.par === me || admin}
                <button class="btn-liberer" on:click={() => liberer(c.id)}>Libérer</button>
              {/if}
            </span>
          {:else}
            <button class="btn-claim" on:click={() => claimItem(c.id)}
                    disabled={claiming[c.id]}>→ Prendre</button>
          {/if}
          <div class="cand-actions">
            {#if statusFilter !== 'validated'}
              <button class="btn-validate" on:click={() => setStatus(c.id,'validated')}
                      disabled={saving[c.id] || (c.reservation && c.reservation.par !== me)}>✓ Valider</button>
            {/if}
            {#if statusFilter !== 'rejected'}
              <button class="btn-reject"   on:click={() => setStatus(c.id,'rejected')}
                      disabled={saving[c.id] || (c.reservation && c.reservation.par !== me)}>✕ Rejeter</button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .queue-page { padding: 1.2rem; max-width: 1100px; }
  .queue-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .queue-controls { display: flex; align-items: center; gap: .5rem; margin-left: auto; }
  .queue-controls select { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; border-radius: 5px; padding: .3rem .5rem; font-size: .8rem; }
  .btn-reload { background: #1e293b; border: 1px solid #334155; color: #94a3b8; border-radius: 5px; padding: .3rem .6rem; font-size: .78rem; cursor: pointer; }
  .btn-reload:hover { border-color: #60a5fa; color: #60a5fa; }
  .count-info { font-size: .78rem; color: #64748b; }

  .candidate-list { display: flex; flex-direction: column; gap: .3rem; }
  .candidate-row {
    display: grid;
    grid-template-columns: 220px 1fr 48px 80px auto;
    align-items: center;
    gap: .6rem;
    padding: .45rem .75rem;
    background: #1e293b;
    border-radius: 6px;
    border: 1px solid #334155;
    font-size: .78rem;
  }
  .candidate-row.low-score { opacity: .65; }
  .cand-entity { display: flex; align-items: center; gap: .35rem; min-width: 0; }
  .entity-link { color: #93c5fd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .entity-link:hover { text-decoration: underline; }
  .type-badge { font-size: .62rem; padding: 1px 5px; border-radius: 3px; color: #fff; font-weight: 600; white-space: nowrap; flex-shrink: 0; }
  .type-association { background: #065f46; }
  .type-business    { background: #1d4ed8; }
  .type-place       { background: #4c1d95; }
  .type-service     { background: #92400e; }
  .type-person      { background: #7f1d1d; }

  .cand-url { color: #60a5fa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cand-url:hover { text-decoration: underline; }
  .cand-score { font-weight: 700; text-align: center; font-size: .8rem; }
  .cand-source { white-space: nowrap; }
  .muted { color: #64748b; }
  .cand-actions { display: flex; gap: .3rem; }

  .btn-validate { background: #14532d; border: 1px solid #166534; color: #4ade80; border-radius: 4px; padding: .25rem .55rem; font-size: .72rem; font-weight: 600; cursor: pointer; }
  .btn-validate:hover:not(:disabled) { background: #166534; }
  .btn-reject   { background: #450a0a; border: 1px solid #7f1d1d; color: #f87171; border-radius: 4px; padding: .25rem .55rem; font-size: .72rem; font-weight: 600; cursor: pointer; }
  .btn-reject:hover:not(:disabled)   { background: #7f1d1d; }
  button:disabled { opacity: .45; cursor: default; }

  .err-msg { color: #f87171; font-size: .83rem; }
  .avis { margin: 0 0 .6rem; padding: .5rem .75rem; background: #3b2506; border: 1px solid #b45309;
          border-radius: 6px; color: #fde68a; font-size: .82rem; }
  .cand-lock { display: flex; align-items: center; gap: .35rem; color: #fbbf24; white-space: nowrap; }
  .btn-liberer { border: 1px solid #b45309; border-radius: 4px; padding: .1rem .4rem;
                 font-size: .68rem; color: #fde68a; cursor: pointer; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; }
</style>
