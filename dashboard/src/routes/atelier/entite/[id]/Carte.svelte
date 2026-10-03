<script>
  import MapEdit from '$lib/components/MapEdit.svelte'

  export let form
  export let entityName = ''
  export let modifiee = false
  // Change après un enregistrement ou une annulation : la carte se recrée sur
  // la position qui vaut alors (MapEdit ne lit ses coordonnées qu'au montage).
  export let version = 0
</script>

<section class="card">
  <h2>Carte</h2>
  <div class="grid2">
    <label class:modifie={modifiee}>
      Latitude
      <input type="number" step="0.000001" bind:value={form.lat} placeholder="44.04..." />
    </label>
    <label class:modifie={modifiee}>
      Longitude
      <input type="number" step="0.000001" bind:value={form.lng} placeholder="3.86..." />
    </label>
  </div>
  {#if form.lat && form.lng}
    <div class="coords-actions">
      <span class="coords-current">{(+form.lat).toFixed(5)}, {(+form.lng).toFixed(5)}</span>
      {#if modifiee}<span class="tag-attente">nouvelle position, à enregistrer</span>{/if}
      <a class="coords-osm-link" target="_blank" rel="noopener"
         href={`https://www.openstreetmap.org/?mlat=${form.lat}&mlon=${form.lng}#map=17/${form.lat}/${form.lng}`}>
        Voir sur OSM ↗
      </a>
    </div>
  {:else}
    <p class="muted coords-hint">Aucune coordonnée. Saisir lat/lng ci-dessus ou cliquer sur la carte.</p>
  {/if}
  {#key version}
    <MapEdit
      lat={form.lat ? +form.lat : null}
      lng={form.lng ? +form.lng : null}
      {entityName}
      on:coords={e => { form.lat = e.detail.lat; form.lng = e.detail.lng }}
    />
  {/key}
</section>

<style>
  .coords-actions { display: flex; align-items: center; gap: .75rem; margin: .5rem 0; font-size: .78rem; flex-wrap: wrap; }
  .coords-current { color: #94a3b8; }
  .coords-osm-link { color: #60a5fa; }
  .coords-hint { font-size: .75rem; margin: .5rem 0; }
</style>
