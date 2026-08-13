<script>
  import { onMount, onDestroy } from 'svelte'
  let L
  import { api } from '$lib/api.js'
  import {
    activeLayers, bizStatus, showExternal, mapFocus,
    selectedEntity, activeTab, TYPE_COLORS
  } from '$lib/stores/app.js'
  import { timelineYear, timelineMode, timelineRange } from '$lib/stores/timeline.js'
  import TimelineSlider from '$lib/components/TimelineSlider.svelte'

  let mapEl
  let map
  // Cache brut des features par couche (sans filtre)
  let rawFeatures = {}
  // Groupes Leaflet actifs
  let clusterGroups = {}
  let dvfLayer
  // Marker fixe pour la mairie (hors cluster)
  let mairieMarker = null
  // Marker de surbrillance (entité sélectionnée depuis liste)
  let highlightMarker = null
  // Cache DVF brut
  let rawDvf = []

  const LAYER_ORDER = ['businesses', 'associations', 'services', 'places', 'persons']
  const CENTER = [44.045588, 3.854624]
  const ZOOM   = 14

  // Entités clés toujours visibles, non clusterisées
  const PINNED_ENTITIES = [
    { id: 63, lat: 44.045588, lng: 3.854624, label: 'Mairie — Commune de Lasalle' }
  ]

  // ── Icônes ──────────────────────────────────────────────────
  function makeIcon(type, color) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="8" fill="${color}" fill-opacity=".85" stroke="#fff" stroke-width="1.5"/>
    </svg>`
    return L.divIcon({ html: svg, className: '', iconSize: [20,20], iconAnchor: [10,10], popupAnchor: [0,-12] })
  }

  function mairieIcon() {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
      <circle cx="14" cy="14" r="12" fill="#f59e0b" stroke="#fff" stroke-width="2"/>
      <text x="14" y="19" text-anchor="middle" font-size="13" fill="#fff">🏛</text>
    </svg>`
    return L.divIcon({ html: svg, className: '', iconSize: [28,28], iconAnchor: [14,14], popupAnchor: [0,-16] })
  }

  function dvfIcon() {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">
      <rect x="1" y="1" width="12" height="12" rx="2" fill="#f97316" fill-opacity=".8" stroke="#fff" stroke-width="1"/>
    </svg>`
    return L.divIcon({ html: svg, className: '', iconSize: [14,14], iconAnchor: [7,7] })
  }

  function popupHtml(props) {
    const siren = props.siren ? `<br/><small>SIREN ${props.siren}</small>` : ''
    const addr  = props.address ? `<br/><small>${props.address}</small>` : ''
    return `<strong>${props.name}</strong>${siren}${addr}
      <br/><button onclick="window._openEntity(${props.id})">Détail →</button>`
  }

  // ── Filtre temporel ──────────────────────────────────────────
  function entityYear(props) {
    const d = props.creation_date || props.asso_creation_date || ''
    if (isSpuriousDate(d)) return null  // date inconnue → pas de filtre
    return d ? parseInt(d.slice(0, 4)) : null
  }
  function closingYear(props) {
    const d = props.closing_date || ''
    return d ? parseInt(d.slice(0, 4)) : null
  }

  function passesFilter(props, year, mode) {
    if (year === null) return true
    const cy = entityYear(props)
    if (!cy) return true // pas de date → toujours visible
    const cl = closingYear(props)
    if (mode === 'exact') {
      // Existait pendant cette année
      const afterCreate  = cy <= year
      const beforeClose  = !cl || cl >= year
      return afterCreate && beforeClose
    } else {
      // Cumulatif : créé avant ou pendant l'année
      return cy <= year
    }
  }

  function dvfPassesFilter(tx, year, mode) {
    if (year === null) return true
    const y = tx.year ?? parseInt((tx.date || '').slice(0, 4))
    if (!y) return true
    return mode === 'exact' ? y === year : y <= year
  }

  // ── Mise à jour plage temporelle depuis les données ──────────
  // Années parasites SIRENE : 1900 = date inconnue, 25/12 = placeholder mois/jour inconnu
  function isSpuriousDate(dateStr) {
    if (!dateStr) return true
    if (dateStr.startsWith('1900')) return true
    if (dateStr.endsWith('-12-25')) return true
    return false
  }

  function updateRange(features, dvfRows) {
    let min = 2020, max = new Date().getFullYear()
    features.forEach(f => {
      const d = f.properties.creation_date || f.properties.asso_creation_date || ''
      if (isSpuriousDate(d)) return
      const y = parseInt(d.slice(0, 4))
      if (y > 1900) { if (y < min) min = y; if (y > max) max = y }
    })
    dvfRows.forEach(t => {
      const y = t.year ?? parseInt((t.date || '').slice(0, 4))
      if (y && y > 1900) { if (y < min) min = y; if (y > max) max = y }
    })
    timelineRange.set({ min, max })
  }

  // ── Rendu d'une couche (depuis cache) ───────────────────────
  function renderLayer(key, year, mode) {
    if (!map) return
    if (clusterGroups[key]) { map.removeLayer(clusterGroups[key]); delete clusterGroups[key] }
    if (!$activeLayers[key]) return
    const features = rawFeatures[key] || []
    const typeKey = key === 'businesses' ? 'business'
                  : key === 'associations' ? 'association'
                  : key === 'services' ? 'service'
                  : key === 'places' ? 'place'
                  : key === 'persons' ? 'person' : key
    const color = TYPE_COLORS[typeKey] || '#94a3b8'
    const icon  = makeIcon(typeKey, color)
    const group = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 16 })

    features
      .filter(f => passesFilter(f.properties, year, mode))
      .forEach(f => {
        const [lng, lat] = f.geometry.coordinates
        const marker = L.marker([lat, lng], { icon })
        marker.bindPopup(popupHtml(f.properties), { maxWidth: 260 })
        marker.on('click', () => { selectedEntity.set(f.properties); activeTab.set('entity') })
        group.addLayer(marker)
      })
    clusterGroups[key] = group
    map.addLayer(group)
  }

  function renderDVF(year, mode) {
    if (!map) return
    if (dvfLayer) { map.removeLayer(dvfLayer); dvfLayer = null }
    if (!$activeLayers.dvf) return
    dvfLayer = L.layerGroup()
    const icon = dvfIcon()
    rawDvf
      .filter(t => t.lat && t.lng && dvfPassesFilter(t, year, mode))
      .forEach(t => {
        const m = L.marker([t.lat, t.lng], { icon })
        const price = t.price ? `${t.price.toLocaleString('fr-FR')} €` : 'N/A'
        m.bindPopup(`<strong>${t.nature_mutation || 'Mutation'}</strong><br/>
          ${t.date || ''} — ${price}<br/>
          <small>${t.nature_bien || ''} ${t.surface_terrain ? t.surface_terrain+' m²' : ''}</small>`)
        dvfLayer.addLayer(m)
      })
    map.addLayer(dvfLayer)
  }

  function renderAll(year, mode) {
    LAYER_ORDER.forEach(k => renderLayer(k, year, mode))
    renderDVF(year, mode)
  }

  // ── Chargement initial depuis l'API ──────────────────────────
  async function fetchLayer(key) {
    const status = (key === 'businesses') ? $bizStatus : ''
    const in_commune = !$showExternal
    try {
      const data = await api.layer(key, status, in_commune)
      const arr = Array.isArray(data) ? data : (data.features || [])
      rawFeatures[key] = arr
        .filter(e => e.lat && e.lng)
        .map(e => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [e.lng, e.lat] },
          properties: e,
        }))
    } catch(e) { console.warn('layer', key, e); rawFeatures[key] = [] }
  }

  async function fetchDVF() {
    try {
      const data = await api.dvf('', 1000)
      rawDvf = Array.isArray(data) ? data : (data.transactions || [])
    } catch(e) { rawDvf = [] }
  }

  function renderPinned() {
    if (!map) return
    if (mairieMarker) { map.removeLayer(mairieMarker); mairieMarker = null }
    PINNED_ENTITIES.forEach(p => {
      const icon = mairieIcon()
      const m = L.marker([p.lat, p.lng], { icon, zIndexOffset: 1000 })
      m.bindPopup(`<strong>${p.label}</strong><br/><button onclick="window._openEntity(${p.id})">Détail →</button>`, { maxWidth: 220 })
      m.on('click', () => {
        api.entity(p.id).then(e => { selectedEntity.set(e); activeTab.set('entity') })
      })
      m.addTo(map)
      mairieMarker = m
    })
  }

  async function fetchAll() {
    await Promise.all([...LAYER_ORDER.map(fetchLayer), fetchDVF()])
    const allFeatures = Object.values(rawFeatures).flat()
    updateRange(allFeatures, rawDvf)
    renderAll($timelineYear, $timelineMode)
    renderPinned()
  }

  // ── Souscriptions réactives ──────────────────────────────────
  let subs = []

  onMount(async () => {
    const leaflet = await import('leaflet')
    await import('leaflet.markercluster')
    L = leaflet.default
    map = L.map(mapEl, { center: CENTER, zoom: ZOOM, zoomControl: true })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19
    }).addTo(map)

    window._openEntity = (id) => {
      api.entity(id).then(e => { selectedEntity.set(e); activeTab.set('entity') })
    }

    await fetchAll()

    // Timeline → re-render (sans re-fetch)
    let firstTL = true
    subs.push(timelineYear.subscribe(y => {
      if (firstTL) { firstTL = false; return }
      renderAll(y, $timelineMode)
    }))
    subs.push(timelineMode.subscribe(m => renderAll($timelineYear, m)))

    // Toggle couches → re-render depuis cache
    let firstL = true
    subs.push(activeLayers.subscribe(() => {
      if (firstL) { firstL = false; return }
      renderAll($timelineYear, $timelineMode)
    }))

    // Filtre statut entreprise → re-fetch businesses seulement
    let firstS = true
    subs.push(bizStatus.subscribe(async () => {
      if (firstS) { firstS = false; return }
      await fetchLayer('businesses')
      renderLayer('businesses', $timelineYear, $timelineMode)
    }))

    // Toggle hors-commune → re-fetch toutes les couches
    let firstE = true
    subs.push(showExternal.subscribe(async () => {
      if (firstE) { firstE = false; return }
      await Promise.all(LAYER_ORDER.map(fetchLayer))
      renderAll($timelineYear, $timelineMode)
    }))

    // Zoom carte + surbrillance depuis SidePanel
    subs.push(mapFocus.subscribe(f => {
      if (!f || !map) return
      map.setView([f.lat, f.lng], f.zoom ?? 17)
      // Surbrillance : bague pulsante
      if (highlightMarker) { map.removeLayer(highlightMarker); highlightMarker = null }
      const icon = L.divIcon({
        html: '<div class="hl-ring"></div>',
        className: '',
        iconSize: [40, 40],
        iconAnchor: [20, 20],
      })
      highlightMarker = L.marker([f.lat, f.lng], { icon, zIndexOffset: 1500, interactive: false })
      highlightMarker.addTo(map)
      // Disparaît après 4s
      setTimeout(() => {
        if (highlightMarker) { map.removeLayer(highlightMarker); highlightMarker = null }
      }, 4000)
    }))
  })

  onDestroy(() => {
    subs.forEach(u => u())
    if (map) map.remove()
  })
</script>

<div class="map-wrap">
  <div class="map-container" bind:this={mapEl}></div>
  <TimelineSlider />
</div>

<style>
  .map-wrap { position: relative; width: 100%; height: 100%; }
  .map-container { width: 100%; height: 100%; }

  :global(.hl-ring) {
    width: 40px; height: 40px;
    border-radius: 50%;
    border: 3px solid #f59e0b;
    box-shadow: 0 0 0 0 rgba(245, 158, 11, .6);
    animation: hl-pulse 1s ease-out 4;
  }
  @keyframes hl-pulse {
    0%   { box-shadow: 0 0 0 0 rgba(245, 158, 11, .7); }
    70%  { box-shadow: 0 0 0 14px rgba(245, 158, 11, 0); }
    100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
  }

  :global(.leaflet-popup-content button) {
    margin-top: 6px; padding: 3px 10px;
    background: #3b82f6; color: #fff;
    border-radius: 4px; font-size: .78rem; cursor: pointer; border: none;
  }
</style>
