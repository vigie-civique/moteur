<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'

  export let lat = null
  export let lng = null
  export let entityName = ''

  const dispatch = createEventDispatcher()

  let mapEl
  let map
  let marker
  let L
  let curLat = lat
  let curLng = lng

  const CENTER = [44.045588, 3.854624]

  // Fonds IGN Géoplateforme (WMTS PM = XYZ web-mercator)
  const IGN = (layer, fmt) =>
    `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
    `&LAYER=${layer}&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=${fmt}`
  const IGN_ATTR = '&copy; <a href="https://geoservices.ign.fr/">IGN</a>'

  onMount(async () => {
    L = (await import('leaflet')).default
    await import('leaflet/dist/leaflet.css')

    const initLat = lat ?? CENTER[0]
    const initLng = lng ?? CENTER[1]

    map = L.map(mapEl, { maxZoom: 21 }).setView([initLat, initLng], lat ? 18 : 14)

    // ── Fonds de carte ──────────────────────────────────────────────────────
    const ortho = L.tileLayer(IGN('ORTHOIMAGERY.ORTHOPHOTOS', 'image/jpeg'), {
      maxZoom: 21, maxNativeZoom: 19, attribution: IGN_ATTR + ' — Ortho',
    })
    const plan = L.tileLayer(IGN('GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2', 'image/png'), {
      maxZoom: 21, maxNativeZoom: 19, attribution: IGN_ATTR + ' — Plan IGN',
    })
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap',
    })
    ortho.addTo(map)  // ortho par défaut = on voit les bâtiments → placement <5 m

    // ── Surcouche cadastre (WMS, transparent) ───────────────────────────────
    const cadastre = L.tileLayer.wms('https://data.geopf.fr/wms-r/wms', {
      layers: 'CADASTRALPARCELS.PARCELLAIRE_EXPRESS',
      format: 'image/png', transparent: true, maxZoom: 21,
      attribution: IGN_ATTR + ' — Cadastre',
    }).addTo(map)

    L.control.layers(
      { 'Ortho IGN': ortho, 'Plan IGN': plan, 'OSM': osm },
      { 'Cadastre (parcelles)': cadastre },
      { collapsed: false },
    ).addTo(map)

    if (lat && lng) _placeMarker(lat, lng)

    map.on('click', e => _set(e.latlng.lat, e.latlng.lng))
  })

  onDestroy(() => { if (map) map.remove() })

  function _placeMarker(la, ln) {
    if (marker) {
      marker.setLatLng([la, ln])
    } else {
      marker = L.marker([la, ln], { draggable: true }).addTo(map)
      marker.bindPopup(entityName || 'Entité')
      marker.on('dragend', e => {
        const { lat: la2, lng: ln2 } = e.target.getLatLng()
        _set(la2, ln2)
      })
    }
  }

  function _set(la, ln) {
    curLat = la; curLng = ln
    _placeMarker(la, ln)
    dispatch('coords', { lat: la, lng: ln })
  }

  export function setCenter(la, ln) {
    if (map) map.setView([la, ln], 18)
    _set(la, ln)
  }
</script>

<div class="map-edit-wrap">
  <div bind:this={mapEl} class="map-el"></div>
  <div class="map-foot">
    <span class="hint">Fond <b>Ortho IGN</b> par défaut : zoome sur le toit, clique/glisse le marqueur (précision &lt;5 m).</span>
    {#if curLat != null}
      <span class="coords">lat {curLat.toFixed(6)} · lng {curLng.toFixed(6)} <em>(Lambert 93 calculé à l'enregistrement)</em></span>
    {/if}
  </div>
</div>

<style>
  .map-edit-wrap { display: flex; flex-direction: column; gap: .3rem; }
  .map-el { height: 440px; border-radius: 6px; border: 1px solid #334155; }
  .map-foot { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .hint { font-size: .72rem; color: #64748b; }
  .coords { font-size: .72rem; color: #93c5fd; font-variant-numeric: tabular-nums; }
  .coords em { color: #64748b; font-style: normal; }
</style>
