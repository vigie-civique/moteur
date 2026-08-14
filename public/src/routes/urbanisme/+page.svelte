<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { euros } from '$lib/data.js'
  import Niveau from '$lib/components/Niveau.svelte'

  // Données rendues au build par +page.server.js ; seule la carte Leaflet
  // reste montée côté client.
  export let data
  $: dvf = data.dvf
  $: constat = data.constat
  let mapEl, map, L
  let mapErreur = ''
  let natureFilter = 'all'

  // La carte, elle, reste client-only : Leaflet a besoin du DOM. Son échec
  // éventuel ne doit pas emporter les tableaux, déjà présents dans le HTML.
  onMount(async () => {
    try {
      const pts = dvf.filter((t) => t.lat && t.lng)
      L = (await import('leaflet')).default
      await import('leaflet/dist/leaflet.css')
      map = L.map(mapEl, { attributionControl: true }).setView([43.99, 3.87], 13)
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map)
      for (const t of pts) {
        L.circleMarker([t.lat, t.lng], {
          radius: 5, color: '#f97316', weight: 1, fillColor: '#fb923c', fillOpacity: 0.75,
        }).bindPopup(
          `<strong>${t.nature_bien || 'Mutation'}</strong><br>${t.date || ''}<br>` +
          `${t.cadastre_ref || ''} ${t.lieu_dit || ''}<br>` +
          `Prix : ${t.price ? euros(t.price) : '—'}${t.price_per_m2 ? ` (${Math.round(t.price_per_m2)} €/m²)` : ''}`
        ).addTo(map)
      }
      if (pts.length) map.fitBounds(L.latLngBounds(pts.map((t) => [t.lat, t.lng])).pad(0.1))
    } catch (e) { mapErreur = e.message }
  })

  const median = (arr) => {
    const s = arr.filter(n => n != null).sort((a, b) => a - b)
    if (!s.length) return null
    const m = Math.floor(s.length / 2)
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
  }
  const matches = (t, re) => re.test(t.nature_bien || '')
  $: maisons = dvf.filter(t => matches(t, /maison/i))
  $: apparts = dvf.filter(t => matches(t, /appartement/i))
  $: terrains = dvf.filter(t => matches(t, /terrain/i))
  $: years = dvf.map(t => (t.date || '').slice(0, 4)).filter(Boolean).sort()
  $: periode = years.length ? `${years[0]}–${years[years.length - 1]}` : '—'
  $: medMaison = median(maisons.map(t => t.price))
  $: medM2 = median(dvf.filter(t => matches(t, /maison|appartement/i)).map(t => t.price_per_m2))

  // Marché immobilier par an : volume de mutations + prix médian €/m² du bâti
  $: dvfYears = [...new Set(dvf.map(t => (t.date || '').slice(0, 4)).filter(Boolean))].sort()
  $: dvfByYear = dvfYears.map(y => {
    const inYear = dvf.filter(t => (t.date || '').slice(0, 4) === y)
    const bati = inYear.filter(t => matches(t, /maison|appartement/i))
    return { year: y, n: inYear.length, medM2: median(bati.map(t => t.price_per_m2)) }
  })
  $: dvfYrMax = Math.max(...dvfByYear.map(d => d.n), 1)
  $: dvfM2Max = Math.max(...dvfByYear.map(d => d.medM2 || 0), 1)

  // Répartition par nature de bien
  $: byNature = Object.entries(
    dvf.reduce((a, t) => { const k = t.nature_bien || '—'; a[k] = (a[k] || 0) + 1; return a }, {})
  ).sort((a, b) => b[1] - a[1])
  $: natMax = Math.max(...byNature.map(([, n]) => n), 1)

  $: dvfFiltered = (natureFilter === 'all' ? dvf : dvf.filter(t => (t.nature_bien || '—') === natureFilter))
  $: dvfTable = dvfFiltered.slice(0, 200)

  function eurosC(n) {
    if (n == null) return '—'
    const a = Math.abs(n)
    if (a >= 1e6) return (n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€'
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString('fr-FR') + ' k€'
    return euros(n)
  }
</script>

<svelte:head><title>Urbanisme &amp; foncier — {SITE_NOM}</title>
  <meta name="description" content="Transactions foncières (DVF) et marchés publics de travaux {COMMUNE_A}." /></svelte:head>

<section>
  <h1>Urbanisme &amp; transactions foncières</h1>
  <p class="sub">Mutations immobilières (DVF, Cerema) recensées sur la commune. Les <a href="/marches">marchés publics</a> ont leur page dédiée.</p>

  {#if !dvf.length}<p class="muted">Aucune mutation dans ce jeu de données.</p>{/if}

  {#if constat}
    <Niveau type="calcul" base="les ventes de maisons et d'appartements enregistrées dans DVF">
      Sur {constat.annees[0].annee}–{constat.annees[constat.annees.length - 1].annee},
      <b>{constat.ventes}</b> ventes de bâti sont enregistrées, soit
      {constat.minEchantillon} à {constat.maxEchantillon} par an. Le prix médian
      annuel oscille entre <b>{constat.basse.toLocaleString('fr-FR')}</b> et
      <b>{constat.haute.toLocaleString('fr-FR')} €/m²</b>.
    </Niveau>
    <p class="lecture">
      <b>Ce que ces chiffres ne disent pas.</b> Cet écart n'est pas un mouvement
      du marché&nbsp;: avec {constat.minEchantillon} à {constat.maxEchantillon} ventes
      par an, une seule maison atypique déplace la médiane de plusieurs centaines
      d'euros au mètre carré. Il n'y a pas de tendance mesurable à lire ici, et
      la courbe ci-dessous ne doit pas être interprétée comme telle. DVF
      enregistre par ailleurs des transactions sans leur contexte&nbsp;: une vente
      entre proches, un bien à rénover et une maison restaurée y figurent au
      même titre.
    </p>
  {/if}
  {#if mapErreur}<p class="err">La carte n'a pas pu être affichée : {mapErreur}</p>{/if}

  {#if dvf.length}
    <div class="tiles">
      <div class="tile">
        <span class="tlabel">Mutations recensées</span>
        <span class="tval">{dvf.length.toLocaleString('fr-FR')}</span>
        <span class="tsub">{periode}</span>
      </div>
      <div class="tile">
        <span class="tlabel">Ventes de maisons</span>
        <span class="tval">{maisons.length}</span>
        <span class="tsub">prix médian {eurosC(medMaison)}</span>
      </div>
      <div class="tile">
        <span class="tlabel">Prix médian bâti</span>
        <span class="tval">{medM2 ? Math.round(medM2).toLocaleString('fr-FR') + ' €/m²' : '—'}</span>
        <span class="tsub">maisons &amp; appartements</span>
      </div>
      <div class="tile">
        <span class="tlabel">Terrains &amp; appartements</span>
        <span class="tval">{terrains.length} · {apparts.length}</span>
        <span class="tsub">terrains · appartements</span>
      </div>
    </div>
  {/if}

  <div class="map" bind:this={mapEl}></div>

  {#if dvfByYear.length > 1}
    <h2>Le marché immobilier, année par année</h2>
    <p class="hint">Nombre de mutations enregistrées et prix médian au m² du bâti (maisons &amp; appartements), sur {periode}.</p>
    <div class="scrollx">
      <div class="yrbars">
        {#each dvfByYear as d}
          <div class="ycol" title="{d.year} : {d.n} mutation(s){d.medM2 ? `, ${Math.round(d.medM2)} €/m²` : ''}">
            <span class="ym2">{d.medM2 ? Math.round(d.medM2).toLocaleString('fr-FR') + ' €/m²' : '—'}</span>
            <span class="ybar" style="height:{Math.max(6, 100 * d.n / dvfYrMax)}%"></span>
            <span class="yn">{d.n}</span>
            <span class="yyear">{d.year}</span>
          </div>
        {/each}
      </div>
    </div>
    <p class="ylegend"><span class="sw"></span> hauteur = nombre de mutations · valeur du haut = prix médian €/m² du bâti</p>
  {/if}

  {#if byNature.length}
    <h2>Répartition par nature de bien</h2>
    <ul class="bars">
      {#each byNature as [nat, n]}
        <li>
          <button class="blabel" class:active={natureFilter === nat} on:click={() => natureFilter = natureFilter === nat ? 'all' : nat}>{nat}</button>
          <span class="btrack"><span class="bfill" style="width:{100 * n / natMax}%"></span></span>
          <span class="bval">{n}</span>
        </li>
      {/each}
    </ul>
  {/if}

  <details open>
    <summary>Transactions {natureFilter !== 'all' ? `— ${natureFilter}` : ''} ({dvfFiltered.length})</summary>
    <table>
      <thead><tr><th>Date</th><th>Parcelle</th><th>Nature</th><th class="r">Surface</th><th class="r">Prix</th><th class="r">€/m²</th></tr></thead>
      <tbody>
        {#each dvfTable as t (t.id)}
          <tr>
            <td>{t.date || '—'}</td>
            <td>{t.cadastre_ref || ''} {t.lieu_dit || ''}</td>
            <td>{t.nature_bien || t.nature_mutation || ''}</td>
            <td class="r">{t.surface_bati || t.surface_terrain || '—'}</td>
            <td class="r">{t.price ? euros(t.price) : '—'}</td>
            <td class="r">{t.price_per_m2 ? Math.round(t.price_per_m2) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if dvfFiltered.length > 200}<p class="muted">200 premières lignes sur {dvfFiltered.length}.</p>{/if}
  </details>

  <p class="pointer">🏗 Les <a href="/marches">marchés publics</a> (travaux, études, fournitures) ont désormais leur propre page dédiée.</p>
</section>

<style>
  .lecture {
    margin: .5rem 0 1.5rem; padding: .7rem .9rem;
    border-left: 3px solid var(--ambre); background: var(--ambre-pale);
    border-radius: 0 var(--rayon) var(--rayon) 0;
    font-size: .9rem; line-height: 1.55; color: var(--gris);
  }
  .lecture b { color: var(--encre); }

  section { max-width: 1050px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  h1 { margin: 0 0 .25rem; } h2 { color: var(--encre); margin: 1.5rem 0 .5rem; font-size: 1.1rem; }
  .sub { color: var(--gris); margin: 0 0 1rem; }
  .hint { color: var(--gris); font-size: .85rem; margin: 0 0 .75rem; }

  .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; margin-bottom: 1.25rem; }
  .tile { background: #fff; border: 1px solid var(--trait); border-top: 3px solid #f97316; border-radius: 8px; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem; }
  .tlabel { font-size: .72rem; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
  .tval { font-size: 1.35rem; font-weight: 700; color: var(--encre); }
  .tsub { font-size: .78rem; color: var(--gris-clair); }

  .map { height: 50vh; min-height: 360px; border-radius: 10px; border: 1px solid var(--trait); margin-bottom: 1rem; }

  .bars { list-style: none; padding: 0; margin: 0 0 .5rem; display: flex; flex-direction: column; gap: .4rem; }
  .bars li { display: grid; grid-template-columns: minmax(120px, 1fr) 2fr 40px; align-items: center; gap: .6rem; }
  .blabel { text-align: left; font-size: .82rem; color: var(--gris); background: none; border: none; padding: .1rem 0; cursor: pointer; }
  .blabel:hover { color: var(--ambre); } .blabel.active { color: var(--ambre); font-weight: 700; }
  .btrack { background: var(--trait-pale); border-radius: 4px; height: 13px; overflow: hidden; }
  .bfill { display: block; height: 100%; background: var(--ambre); border-radius: 4px; }
  .bval { text-align: right; font-size: .8rem; font-weight: 700; font-variant-numeric: tabular-nums; }

  details { margin: 1rem 0; } summary { cursor: pointer; color: var(--gris); font-weight: 600; font-size: .95rem; padding: .3rem 0; }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--trait); }
  th { color: var(--gris); } .r { text-align: right; font-variant-numeric: tabular-nums; }
  .scrollx { overflow-x: auto; }
  .yrbars { display: flex; align-items: flex-end; gap: .55rem; height: 170px; padding: .5rem 0; border-bottom: 1px solid var(--trait); min-width: 420px; }
  .ycol { flex: 1; min-width: 34px; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: .15rem; }
  .ym2 { font-size: .66rem; color: var(--ambre); font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ybar { width: 62%; max-width: 38px; background: var(--ambre); border-radius: 4px 4px 0 0; min-height: 6px; }
  .yn { font-size: .72rem; color: var(--gris); font-weight: 700; font-variant-numeric: tabular-nums; }
  .yyear { font-size: .72rem; color: var(--gris); }
  .ylegend { color: var(--gris-clair); font-size: .76rem; margin: .5rem 0 0; display: flex; align-items: center; gap: .4rem; }
  .ylegend .sw { width: 11px; height: 11px; border-radius: 3px; background: var(--ambre); display: inline-block; }
  .pointer { margin-top: 1.5rem; padding: .7rem .9rem; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; font-size: .9rem; color: #9a3412; }
  .pointer a { color: #c2410c; font-weight: 600; }
  .muted { color: var(--gris-clair); font-size: .85rem; } .err { color: var(--depense); }
  @media (max-width: 720px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
</style>
