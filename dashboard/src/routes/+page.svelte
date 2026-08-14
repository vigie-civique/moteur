<script>
  import { SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { feedItems, selectedEntity, mapFocus } from '$lib/stores/app.js'
  import SearchBar    from '$lib/components/SearchBar.svelte'
  import LayerControl from '$lib/components/LayerControl.svelte'
  import MapView      from '$lib/components/MapView.svelte'
  import SidePanel    from '$lib/components/SidePanel.svelte'

  onMount(async () => {
    try {
      const ev = await api.events('', 30)
      feedItems.set(Array.isArray(ev) ? ev : (ev.events || []))
    } catch(e) {}
  })

  // Auto-zoom carte quand une entité est sélectionnée (depuis recherche, graphe, etc.)
  let prevId = null
  selectedEntity.subscribe(e => {
    if (!e || e.id === prevId) return
    prevId = e.id
    if (e.lat && e.lng) {
      mapFocus.set({ lat: e.lat, lng: e.lng, zoom: 17 })
    }
  })
</script>

<svelte:head>
  <title>Carte — {SITE_NOM}</title>
</svelte:head>

<div class="page-carte">
  <div class="left">
    <div class="search-row">
      <SearchBar />
    </div>
    <LayerControl />
    <div class="map-area">
      <MapView />
    </div>
  </div>
  <SidePanel />
</div>

<style>
  .page-carte {
    display: flex;
    flex: 1;
    overflow: hidden;
    width: 100%;
  }
  .left {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .search-row {
    padding: .35rem 1rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .map-area {
    flex: 1;
    position: relative;
    overflow: hidden;
  }
</style>
