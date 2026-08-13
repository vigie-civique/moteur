<script>
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  let dvf      = []
  let marches  = []
  let loading  = true
  let error    = ''
  let activeTab = 'dvf'
  let L, mapEl, mapObj

  onMount(async () => {
    loading = true
    try {
      const [d, m] = await Promise.all([
        api.dvf().catch(() => []),
        api.marches({ limit: 200 }).catch(() => []),
      ])
      dvf     = Array.isArray(d) ? d : []
      marches = Array.isArray(m) ? m : []
    } catch(e) { error = e.message }
    finally { loading = false }
    if (activeTab === 'carte') initMap()
  })

  $: if (activeTab === 'carte' && mapEl && !mapObj && dvf.length) initMap()

  async function initMap() {
    if (typeof window === 'undefined' || !mapEl) return
    L = (await import('leaflet')).default
    mapObj = L.map(mapEl, { attributionControl: true })
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).addTo(mapObj)
    const pts = dvf.filter(t => t.lat && t.lng)
    if (!pts.length) { mapObj.setView([43.99, 3.87], 13); return }
    const bounds = L.latLngBounds(pts.map(t => [t.lat, t.lng]))
    mapObj.fitBounds(bounds, { padding: [30, 30] })
    pts.forEach(t => {
      const color = t.price > 100000 ? '#f87171' : t.price > 50000 ? '#fb923c' : '#4ade80'
      L.circleMarker([t.lat, t.lng], { radius: 6, color, fillColor: color, fillOpacity: .7 })
        .bindPopup(`<b>${t.nature_bien}</b><br>${t.lieu_dit ?? ''}<br>${t.price?.toLocaleString('fr-FR') ?? '?'} €<br>${t.date}`)
        .addTo(mapObj)
    })
  }

  function fmtDate(d) { return d ? d.slice(0, 10) : '—' }
  function fmtEur(v) { return v != null ? Math.round(v).toLocaleString('fr-FR') + ' €' : '—' }

  $: totalDvf   = dvf.reduce((s, t) => s + (t.price ?? 0), 0)
  $: totalMarch = marches.reduce((s, m) => s + (m.montant ?? 0), 0)
  $: avgDvf     = dvf.length ? totalDvf / dvf.length : 0

  const TABS = [
    { id: 'dvf',    label: 'Transactions DVF' },
    { id: 'carte',  label: 'Carte' },
    { id: 'marches',label: 'Marchés publics' },
  ]
</script>

<svelte:head><title>Urbanisme & foncier — Vigie Civique Lasalle</title></svelte:head>

<div class="urb-page">
  <div class="page-header">
    <h1>Urbanisme & foncier</h1>
    <span class="subtitle">Transactions immobilières (DVF) et marchés publics locaux</span>
  </div>

  <div class="kpi-row">
    <div class="kpi"><div class="kpi-v">{dvf.length}</div><div class="kpi-l">Transactions DVF</div></div>
    <div class="kpi"><div class="kpi-v">{fmtEur(totalDvf)}</div><div class="kpi-l">Volume total</div></div>
    <div class="kpi"><div class="kpi-v">{fmtEur(avgDvf)}</div><div class="kpi-l">Prix moyen</div></div>
    <div class="kpi"><div class="kpi-v">{marches.length}</div><div class="kpi-l">Marchés publics</div></div>
    <div class="kpi"><div class="kpi-v">{fmtEur(totalMarch)}</div><div class="kpi-l">Volume marchés</div></div>
  </div>

  <nav class="tabs">
    {#each TABS as t}
      <button class:active={activeTab === t.id} on:click={() => activeTab = t.id}>
        {t.label}
      </button>
    {/each}
  </nav>

  {#if error}<p class="err">{error}</p>{/if}

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else}

    {#if activeTab === 'dvf'}
      {#if !dvf.length}
        <p class="muted-center">Aucune transaction.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Date</th><th>Nature</th><th>Lieu-dit</th><th>Réf. cadastre</th><th>Surface terrain</th><th>Surface bâti</th><th>Prix</th><th>€/m²</th></tr></thead>
          <tbody>
            {#each dvf as t}
              <tr class:highlight={t.cadastre_ref === 'AD0180'}>
                <td class="muted">{fmtDate(t.date)}</td>
                <td>{t.nature_bien ?? '—'}</td>
                <td class="muted">{t.lieu_dit ?? '—'}</td>
                <td class="ref-cell" class:ref-notable={t.section === 'AD' && t.numero === '0180'}>{t.cadastre_ref ?? '—'}</td>
                <td class="muted">{t.surface_terrain ? t.surface_terrain.toLocaleString('fr-FR') + ' m²' : '—'}</td>
                <td class="muted">{t.surface_bati ? t.surface_bati.toLocaleString('fr-FR') + ' m²' : '—'}</td>
                <td class="montant">{fmtEur(t.price)}</td>
                <td class="muted">{t.price_per_m2 ? t.price_per_m2.toFixed(0) + ' €/m²' : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    {:else if activeTab === 'carte'}
      <div class="map-container" bind:this={mapEl}></div>
      <p class="map-legend muted">
        <span class="dot green"></span> &lt;50 k€
        <span class="dot orange"></span> 50–100 k€
        <span class="dot red"></span> &gt;100 k€
      </p>

    {:else if activeTab === 'marches'}
      {#if !marches.length}
        <p class="muted-center">Aucun marché.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Acheteur</th><th>Objet</th><th>Titulaire</th><th>Montant</th><th>Date</th></tr></thead>
          <tbody>
            {#each marches as m}
              <tr>
                <td class="muted small">{m.acheteur_nom ?? '—'}</td>
                <td class="objet-cell">{m.objet ?? '—'}</td>
                <td>
                  {#if m.titulaire_id}
                    <a href="/entite/{m.titulaire_id}" class="ent-link">{m.titulaire_nom}</a>
                  {:else}
                    <span class="muted">{m.titulaire_nom ?? '—'}</span>
                  {/if}
                </td>
                <td class="montant">{fmtEur(m.montant)}</td>
                <td class="muted">{fmtDate(m.date_notif)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}

  {/if}
</div>

<style>
  .urb-page { padding: 1.2rem; max-width: 1100px; overflow-y: auto; }
  .page-header { margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .subtitle { font-size: .78rem; color: #64748b; }

  .kpi-row { display: flex; gap: .5rem; margin-bottom: .8rem; flex-wrap: wrap; }
  .kpi { background: #1e293b; border: 1px solid #334155; border-radius: 6px;
    padding: .4rem .7rem; min-width: 110px; }
  .kpi-v { font-size: .95rem; font-weight: 700; color: #e2e8f0; }
  .kpi-l { font-size: .65rem; color: #64748b; margin-top: 1px; }

  .tabs { display: flex; gap: .25rem; border-bottom: 1px solid #334155; margin-bottom: .75rem; }
  .tabs button { padding: .35rem .7rem; font-size: .78rem; color: #94a3b8;
    border-bottom: 2px solid transparent; background: none; border-radius: 4px 4px 0 0; }
  .tabs button.active { color: #60a5fa; border-bottom-color: #60a5fa; }
  .tabs button:hover:not(.active) { color: #e2e8f0; }

  .map-container { width: 100%; height: 500px; border-radius: 8px; border: 1px solid #334155; }
  .map-legend { display: flex; align-items: center; gap: .6rem; font-size: .73rem; margin-top: .4rem; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
  .dot.green  { background: #4ade80; }
  .dot.orange { background: #fb923c; }
  .dot.red    { background: #f87171; }

  .data-table { width: 100%; border-collapse: collapse; font-size: .77rem; }
  .data-table th { background: #1e293b; color: #64748b; font-size: .65rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em; padding: .4rem .6rem;
    border-bottom: 1px solid #334155; text-align: left; }
  .data-table td { padding: .35rem .6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }
  .data-table tr:hover td { background: #1e293b; }
  .data-table tr.highlight td { background: #1a0800; }

  .ref-notable { color: #f59e0b; font-weight: 700; }
  .ent-link { color: #93c5fd; }
  .ent-link:hover { text-decoration: underline; }
  .montant { font-weight: 700; color: #fb923c; }
  .muted { color: #64748b; }
  .small { font-size: .72rem; }
  .objet-cell { max-width: 280px; }
  .err { color: #f87171; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; }
</style>
