<script>
  import SourceAbsente from '$lib/components/SourceAbsente.svelte'
  import { COMMUNE, COMMUNE_DE, EPCI_COURT, SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { CENTROID_LAT, CENTROID_LNG } from '$lib/instance.js'
  import { poserFond } from '$lib/carte/fond.js'
  import Icon from '$lib/components/Icon.svelte'
  import { loadJSON, TYPE_LABELS } from '$lib/data.js'

  // La carte occupait la page d'accueil jusqu'au 11/08/2026 : 1 135 points en
  // quatre couleurs accueillaient le visiteur sans lui dire ce qu'est ce site.
  // Elle devient une destination à part entière ; l'accueil explique et oriente.
  // Dénominateur lu au build (cf. +page.server.js) ; la carte elle-même reste
  // montée côté client.
  export let data

  let mapEl, map, L
  let error = ''
  let loading = true

  const TYPE_COLORS = {
    business: '#9a6b12', association: '#2c6e4f', service: '#14556b',
    place: '#6c5b8f', person: '#a4453a', property: '#5c6b72',
  }
  // Calques cartographiables (les personnes restent masquées : règle de publication).
  const LAYERS = [
    { key: 'businesses',   type: 'business',    label: 'Entreprises' },
    { key: 'associations', type: 'association', label: 'Associations' },
    { key: 'services',     type: 'service',     label: 'Services publics' },
    { key: 'places',       type: 'place',       label: 'Lieux' },
  ]
  let groups = {}             // key -> L.layerGroup
  let counts = {}             // key -> nb features affichées
  let sources = {}            // key -> FeatureCollection complète
  let visible = { businesses: true, associations: true, services: true, places: true }
  // Une carte sans fond reste utile : les repères sont là, et leur position
  // aussi. Le dire vaut mieux que de laisser croire à une carte cassée.
  let fondAbsent = ''

  // La carte couvre les quinze communes de l'intercommunalité : sans ce choix,
  // un habitant qui cherche « les associations d'ici » en voit trois fois trop
  // et ne peut pas les distinguer. Par défaut la commune, comme l'annuaire.
  let portee = 'commune'
  const PORTEE_DE = (p) =>
    p === 'C1' ? 'commune' : p === 'C2' ? 'intercommunalite' : 'territoire'
  const retenu = (feat) =>
    portee === 'tout' || PORTEE_DE(feat.properties?.perimetre) === portee

  function toggle(key) {
    if (!map || !groups[key]) return
    visible[key] = !visible[key]
    if (visible[key]) groups[key].addTo(map)
    else map.removeLayer(groups[key])
  }

  // Une carte s'ouvre sur ce qu'elle a à montrer. Sans ce recadrage, elle
  // s'ouvrait sur un centre fixe et il fallait chercher ses propres repères.
  function cadrerSurLesReperes() {
    if (!map || !L) return
    const pts = []
    for (const fc of Object.values(sources)) {
      for (const f of (fc?.features || [])) {
        const c = f.geometry?.coordinates
        if (c && c.length === 2 && retenu(f)) pts.push([c[1], c[0]])
      }
    }
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.08))
  }

  function dessiner() {
    if (!map || !L) return
    for (const layer of LAYERS) {
      if (groups[layer.key]) map.removeLayer(groups[layer.key])
      const fc = sources[layer.key]
      if (!fc) continue
      const gardees = (fc.features || []).filter(retenu)
      counts[layer.key] = gardees.length
      groups[layer.key] = L.geoJSON({ type: 'FeatureCollection', features: gardees }, {
        pointToLayer: (feat, latlng) => L.circleMarker(latlng, {
          radius: 5, color: '#fff', weight: 1.5,
          fillColor: TYPE_COLORS[feat.properties?.type] || '#5c6b72', fillOpacity: 0.9,
        }),
        onEachFeature: (feat, lyr) => {
          const p = feat.properties || {}
          lyr.bindPopup(
            `<strong>${p.name || '?'}</strong><br><span style="color:#5c6b72">${TYPE_LABELS[p.type] || p.type || ''}</span>` +
            (p.id ? `<br><a href="/entite/${p.id}">Voir la fiche →</a>` : '')
          )
        },
      })
      if (visible[layer.key]) groups[layer.key].addTo(map)
    }
    counts = { ...counts }
  }

  // Redessiner au changement de périmètre — jamais au premier rendu, où la
  // carte n'est pas encore montée.
  $: if (map && portee) dessiner()

  $: comptePortee = Object.values(sources).reduce((a, fc) => {
    for (const f of fc.features || []) {
      const p = PORTEE_DE(f.properties?.perimetre)
      a[p] = (a[p] || 0) + 1
    }
    return a
  }, {})

  onMount(async () => {
    try {
      L = (await import('leaflet')).default
      await import('leaflet/dist/leaflet.css')

      // Le centre vient de l'instance. Il était écrit en dur — 44.0456, 3.8546,
      // soit la commune d'origine du moteur : toute autre instance ouvrait sa
      // carte à des centaines de kilomètres de ses propres repères, et le
      // lecteur voyait une carte vide. Le recadrage sur les points, plus bas,
      // est le vrai remède ; ce centre ne sert plus qu'avant leur chargement.
      map = L.map(mapEl, { attributionControl: true, zoomControl: true })
        .setView([CENTROID_LAT, CENTROID_LNG], 14)
      const fond = await poserFond(L, map)
      if (!fond.ok) fondAbsent = fond.raison

      for (const layer of LAYERS) {
        try { sources[layer.key] = await loadJSON(`layers/${layer.key}.geojson`) }
        catch { continue }
      }
      sources = { ...sources }
      dessiner()
      cadrerSurLesReperes()
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })
</script>

<svelte:head><title>La carte des acteurs — {SITE_NOM}</title>
  <meta name="description" content="Carte des entreprises, associations, services publics et lieux {COMMUNE_DE}, à partir des données publiques." /></svelte:head>

<div class="carte">
  <div class="map" bind:this={mapEl}></div>

  <!-- La carte ne porte que les acteurs localisés : le retour vers l'annuaire
       complet doit rester visible, sinon elle passe pour l'inventaire entier. -->
  <a class="vers-annuaire" href="/acteurs-publics">
    <Icon name="fleche" size={15} />Annuaire complet
  </a>

  {#if data.source && data.source.etat !== 'servie'}
    <SourceAbsente etat={data.source.etat} sources={data.source.sources}
                   dernier={data.source.dernier} quoi="Les lieux de la carte" />
  {/if}
  {#if data.surCarte && data.total}
    <p class="perimetre">
      <b>{data.surCarte.toLocaleString('fr-FR')}</b> des
      {data.total.toLocaleString('fr-FR')} acteurs recensés
      <span class="pourquoi">
        Seuls apparaissent ici les acteurs disposant d'une localisation publique
        suffisamment fiable.
        {#if data.sansLocalisation}{data.sansLocalisation} n'ont aucune adresse exploitable ;{/if}
        {#if data.domicileMasque}{data.domicileMasque} sont des entrepreneurs individuels dont l'adresse déclarée est le domicile — elle n'est pas cartographiée ;{/if}
        {#if data.personneMasquee}{data.personneMasquee} sont des personnes physiques, jamais localisées.{/if}
      </span>
    </p>
  {/if}

  {#if error}<div class="toast err">Erreur de chargement : {error}</div>{/if}
  {#if fondAbsent}<p class="sans-fond">Le fond de carte n'a pas pu être chargé —
    les repères ci-dessous restent à leur position exacte. Fond attendu&nbsp;:
    <code>static/carte/fond.pmtiles</code> (<code>scripts/carte_fond.py</code>).</p>{/if}
  {#if loading}<div class="toast">Chargement de la carte…</div>{/if}

  <div class="portee-carte">
    {#each [['commune', COMMUNE], ['intercommunalite', EPCI_COURT], ['tout', 'Tout']] as [cle, label]}
      <button class:on={portee === cle} on:click={() => (portee = cle)}
              aria-pressed={portee === cle}>
        {label}{#if comptePortee[cle]} <em>{comptePortee[cle]}</em>{/if}
      </button>
    {/each}
  </div>

  <div class="legende">
    {#each LAYERS as layer}
      <button class="chip" class:off={!visible[layer.key]} on:click={() => toggle(layer.key)}
              aria-pressed={visible[layer.key]}>
        <span class="dot" style="background:{TYPE_COLORS[layer.type]}"></span>
        {layer.label}{#if counts[layer.key]} <em>{counts[layer.key]}</em>{/if}
      </button>
    {/each}
  </div>
</div>

<style>
  /* Le choix de périmètre est au-dessus de la légende des types : « où » se
     décide avant « quoi ». */
  .portee-carte {
    position: absolute; left: 1rem; bottom: 4.2rem; z-index: 600;
    display: flex; gap: .35rem; flex-wrap: wrap;
  }
  .portee-carte button {
    padding: .3rem .65rem; border: 1px solid var(--trait); border-radius: 999px;
    background: rgba(255,255,255,.94); color: var(--gris);
    font-size: .8rem; cursor: pointer; box-shadow: var(--ombre);
  }
  .portee-carte button.on { background: var(--encre); color: #fff; border-color: var(--encre); }
  .portee-carte em { font-style: normal; opacity: .7; }

  .carte { position: relative; height: calc(100dvh - 58px); min-height: 480px; }
  .map { position: absolute; inset: 0; }

  .toast {
    position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 600;
    background: var(--blanc); padding: .45rem .9rem; border-radius: 999px;
    font-size: .85rem; box-shadow: var(--ombre);
  }
  .toast.err { color: var(--depense); }
  .sans-fond { margin: .5rem 0; padding: .6rem .8rem; border-left: 3px solid var(--ambre);
               background: var(--papier); font-size: .85rem; color: var(--gris); }
  .sans-fond code { font-size: .8rem; }

  .vers-annuaire {
    position: absolute; top: 1rem; right: 1rem; z-index: 600;
    display: inline-flex; align-items: center; gap: .4rem;
    padding: .4rem .7rem; background: rgba(255,255,255,.94);
    border: 1px solid var(--trait); border-radius: var(--rayon);
    font-size: .85rem; box-shadow: var(--ombre);
  }
  .vers-annuaire:hover { border-color: var(--ardoise); text-decoration: none; }
  /* La flèche pointe vers la gauche : c'est un retour vers la liste. */
  .vers-annuaire :global(.icon) { transform: rotate(180deg); }

  /* Le dénominateur se lit au même endroit que le chiffre : une note renvoyée
     en bas de page ou dans /methode n'est jamais lue avant l'interprétation. */
  .perimetre {
    position: absolute; top: 1rem; left: 1rem; z-index: 600; margin: 0;
    max-width: 20rem; padding: .45rem .75rem;
    background: rgba(255,255,255,.94); border: 1px solid var(--trait);
    border-radius: var(--rayon); box-shadow: var(--ombre);
    font-size: .82rem; color: var(--gris); line-height: 1.4;
  }
  .perimetre b { color: var(--encre); }
  .pourquoi { display: block; margin-top: .25rem; font-size: .74rem; color: var(--gris-clair); }
  @media (max-width: 680px) { .perimetre { max-width: calc(100% - 2rem); } }

  .legende {
    position: absolute; bottom: 1rem; left: 50%; transform: translateX(-50%); z-index: 600;
    display: flex; gap: .4rem; flex-wrap: wrap; justify-content: center; max-width: calc(100% - 2rem);
  }
  .chip {
    display: inline-flex; align-items: center; gap: .4rem; cursor: pointer;
    background: rgba(255,255,255,.94); border: 1px solid var(--trait);
    border-radius: 999px; padding: .35rem .7rem;
    font: inherit; font-size: .78rem; color: var(--encre);
    box-shadow: var(--ombre); transition: opacity .12s, border-color .12s;
  }
  .chip:hover { border-color: var(--ardoise); }
  .chip.off { opacity: .45; }
  .chip .dot { width: 9px; height: 9px; border-radius: 50%; }
  .chip em { font-style: normal; color: var(--gris-clair); font-size: .72rem; font-family: var(--data); }

  @media (max-width: 720px) {
    .carte { height: auto; }
    .map { position: relative; height: 68vh; }
    .legende { position: static; transform: none; margin: .75rem 1rem; justify-content: flex-start; }
  }
</style>
