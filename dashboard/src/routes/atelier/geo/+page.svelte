<script>
  import { COMMUNE_DE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { authFetch } from '$lib/stores/auth.js'

  let items = []
  let loading = true
  let error = ''
  let filter = 'tofix'   // tofix | all

  const STATUS = {
    missing:   { label: 'Sans coords', color: '#ef4444' },
    imprecise: { label: 'Imprécis',    color: '#f59e0b' },
    ok:        { label: 'OK auto',     color: '#3b82f6' },
    ok_manual: { label: 'Validé',      color: '#22c55e' },
  }

  onMount(load)

  async function load() {
    loading = true; error = ''
    try {
      const res = await authFetch('/atelier/geo-review?limit=150')
      const data = await res.json()
      items = Array.isArray(data) ? data : []
    } catch (e) {
      error = 'Chargement impossible (connecté ?).'
    } finally {
      loading = false
    }
  }

  $: tofix = items.filter(i => i.geo_status === 'missing' || i.geo_status === 'imprecise')
  $: done  = items.filter(i => i.geo_status === 'ok_manual')
  $: shown = filter === 'tofix' ? tofix : items
</script>

<svelte:head><title>Correction géolocalisation — Atelier</title></svelte:head>

<section>
  <header>
    <div>
      <h1>Correction géolocalisation — entités exposées</h1>
      <p class="sub">Top 150 des entités physiques {COMMUNE_DE}, triées par exposition. Objectif : précision &lt;5 m sur fond Ortho/Cadastre IGN.</p>
    </div>
    <div class="stats">
      <span class="pill red">{tofix.length} à corriger</span>
      <span class="pill green">{done.length} validées</span>
    </div>
  </header>

  <div class="bar">
    <button class:active={filter === 'tofix'} on:click={() => filter = 'tofix'}>À corriger ({tofix.length})</button>
    <button class:active={filter === 'all'} on:click={() => filter = 'all'}>Toutes ({items.length})</button>
    <button class="reload" on:click={load}>↺</button>
  </div>

  {#if error}<p class="err">{error}</p>{/if}
  {#if loading}<p>Chargement…</p>{/if}

  <table>
    <thead>
      <tr><th>Statut</th><th>Expo</th><th>Type</th><th>Nom</th><th>Adresse</th><th>Coords actuelles</th><th></th></tr>
    </thead>
    <tbody>
      {#each shown as it (it.id)}
        <tr>
          <td><span class="badge" style="background:{STATUS[it.geo_status].color}">{STATUS[it.geo_status].label}</span></td>
          <td class="num">{it.expo}</td>
          <td class="muted">{it.type}</td>
          <td>{it.name}</td>
          <td class="muted addr">{it.address || '—'}</td>
          <td class="num muted">{it.lat != null ? `${it.lat.toFixed(5)}, ${it.lng.toFixed(5)}` : '—'}</td>
          <td><a class="fix" href={`/atelier/entite/${it.id}`}>Corriger →</a></td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  section { padding: 1.25rem 1.5rem; max-width: 1200px; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  h1 { font-size: 1.2rem; margin: 0 0 .2rem; color: #e2e8f0; }
  .sub { color: #94a3b8; font-size: .85rem; margin: 0; }
  .stats { display: flex; gap: .5rem; }
  .pill { font-size: .8rem; padding: .25rem .7rem; border-radius: 999px; font-weight: 600; }
  .pill.red { background: #7f1d1d; } .pill.green { background: #065f46; }
  .bar { display: flex; gap: .5rem; margin: 1rem 0; }
  .bar button { padding: .3rem .8rem; border-radius: 6px; background: #1e293b; color: #94a3b8; font-size: .8rem; }
  .bar button.active { background: #3b82f6; color: #fff; }
  .bar .reload { margin-left: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #1e293b; }
  th { color: #64748b; font-weight: 600; }
  .num { font-variant-numeric: tabular-nums; }
  .muted { color: #94a3b8; } .addr { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { color: #fff; font-size: .7rem; padding: .12rem .55rem; border-radius: 999px; white-space: nowrap; }
  .fix { color: #60a5fa; font-weight: 600; white-space: nowrap; }
  .err { color: #fca5a5; }
</style>
