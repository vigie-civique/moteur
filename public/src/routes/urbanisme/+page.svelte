<script>
  import { CENTROID_LAT, CENTROID_LNG, COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { euros } from '$lib/data.js'
  import { poserFond } from '$lib/carte/fond.js'
  import Niveau from '$lib/components/Niveau.svelte'

  // Données rendues au build par +page.server.js ; seule la carte Leaflet
  // reste montée côté client.
  export let data
  $: dvf = data.dvf
  $: constat = data.constat
  $: urba = data.urbanisme || {}
  $: statutPlu = urba.statut
  $: documents = urba.documents || []
  $: zonage = urba.zonage || []
  const QUOI = {
    PLU: "plan local d'urbanisme", PLUi: "plan local d'urbanisme intercommunal",
    CC: 'carte communale', POS: "plan d'occupation des sols",
    PSMV: 'plan de sauvegarde et de mise en valeur',
  }
  let mapEl, map, L
  let mapErreur = ''
  let fondAbsent = ''
  let natureFilter = 'all'

  // La carte, elle, reste client-only : Leaflet a besoin du DOM. Son échec
  // éventuel ne doit pas emporter les tableaux, déjà présents dans le HTML.
  onMount(async () => {
    try {
      const pts = dvf.filter((t) => t.lat && t.lng)
      L = (await import('leaflet')).default
      await import('leaflet/dist/leaflet.css')
      // Le centre était écrit en dur sur les coordonnées de Lasalle — 43.99,
      // 3.87 — dans un moteur qui sert trois communes. Invisible tant qu'il y a
      // des mutations, puisque le cadrage sur les points le corrige aussitôt ;
      // une commune sans DVF publiable ouvrait sa page d'urbanisme sur les
      // Cévennes. Le centroïde de l'instance, comme /carte.
      map = L.map(mapEl, { attributionControl: true })
        .setView([CENTROID_LAT, CENTROID_LNG], 13)
      // Fond servi avec le site, jamais chez un tiers : l'IP du lecteur ne part
      // nulle part, et le dossier hors-ligne a une carte. Cf. $lib/carte/fond.js
      const fond = await poserFond(L, map)
      if (!fond.ok) fondAbsent = fond.raison
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

  // Marché immobilier par an : prix médian €/m² du bâti, et volume de mutations.
  //
  // La HAUTEUR porte le prix, pas le nombre : c'est le prix qu'on vient lire sur
  // un graphique intitulé « le marché immobilier ». L'échelle part de zéro —
  // tronquée, elle ferait passer 5 % d'écart pour un doublement.
  //
  // `nBati` est compté à part parce que la médiane ne repose que sur lui : une
  // commune peut enregistrer trente mutations dans l'année dont deux maisons.
  // Sur deux ventes, une « médiane » n'en est pas une, et le graphique
  // annoncerait une flambée de 764 % — c'est le cas réel de Montselgues en 2022.
  $: dvfYears = [...new Set(dvf.map(t => (t.date || '').slice(0, 4)).filter(Boolean))].sort()
  $: dvfByYear = dvfYears.map(y => {
    const inYear = dvf.filter(t => (t.date || '').slice(0, 4) === y)
    const bati = inYear.filter(t => matches(t, /maison|appartement/i) && t.price_per_m2)
    return { year: y, n: inYear.length, nBati: bati.length,
             medM2: median(bati.map(t => t.price_per_m2)) }
  })
  $: dvfM2Max = Math.max(...dvfByYear.map(d => d.medM2 || 0), 1)
  // En dessous, une médiane ne résume rien : elle désigne une vente ou deux.
  const MEDIANE_FRAGILE = 5
  // Au-dessus, elle cesse d'être du bruit d'échantillon. Le paragraphe « ce que
  // ces chiffres ne disent pas » était écrit pour une commune à vingt ventes
  // par an : il affirmait « aucune tendance mesurable » à une ville qui en
  // enregistre quatre cents, où c'est faux.
  const ECHANTILLON_SOLIDE = 30

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

  {#if statutPlu}
    <h2>Ce qui règle la construction</h2>
    {#if statutPlu.rnu}
      <Niveau type="fait" source="Géoportail de l'urbanisme"
              href="https://www.geoportail-urbanisme.gouv.fr/">
        La commune n'a <b>aucun document d'urbanisme local</b> : c'est le règlement
        national d'urbanisme (RNU) qui s'y applique. Les autorisations se
        décident au regard des règles nationales, et la constructibilité y est
        beaucoup plus restreinte qu'avec un plan local.
      </Niveau>
    {:else if documents.length}
      {#each documents as doc}
        <Niveau type="fait" source="Géoportail de l'urbanisme"
                href="https://www.geoportail-urbanisme.gouv.fr/">
          {QUOI[doc.du_type] || doc.du_type}
          {#if doc.portee === 'intercommunal'}porté par l'intercommunalité
            {#if doc.titre}(<i>{doc.titre}</i>){/if}{/if},
          {#if doc.date_appro}approuvé le <b>{new Date(doc.date_appro).toLocaleDateString('fr-FR')}</b>{:else}sans date d'approbation lisible{/if},
          déposé au Géoportail de l'urbanisme — c'est ce dépôt qui le rend opposable.
        </Niveau>
      {/each}
    {:else}
      <Niveau type="fait" source="Géoportail de l'urbanisme"
              href="https://www.geoportail-urbanisme.gouv.fr/">
        <b>Aucun document d'urbanisme n'est déposé au Géoportail</b>, et la commune
        n'est pas pour autant au RNU. Depuis 2020, un plan qui n'y est pas publié
        n'est pas opposable : la question mérite d'être posée à la mairie.
      </Niveau>
    {/if}

    {#if zonage.length}
      <p class="hint">Part du territoire communal couverte par chaque type de zone,
        mesurée sur {statutPlu.aire_km2?.toLocaleString('fr-FR')} km².</p>
      <div class="tiles">
        {#each zonage as z}
          <div class="tile">
            <span class="tlabel">{z.famille || z.typezone} ({z.typezone})</span>
            <span class="tval">{z.part_pct.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %</span>
            <span class="tsub">{(z.aire_m2 / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} km² · {z.zones} zone(s)</span>
          </div>
        {/each}
      </div>
    {:else if !statutPlu.rnu && documents.length}
      <p class="muted">La répartition du territoire par type de zone n'est pas
        publiée ici : le document déposé ne couvre qu'une partie de la commune
        {#if urba.couverture != null}({Math.round(urba.couverture * 100)} % du territoire){/if} —
        le plus souvent parce qu'il est antérieur à une fusion de communes. Une
        part calculée sur ce seul morceau ne dirait pas ce qu'elle prétend.</p>
    {/if}
  {/if}

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
      <b>Ce que ces chiffres ne disent pas.</b>
      {#if constat.maxEchantillon < ECHANTILLON_SOLIDE}
        Cet écart n'est pas un mouvement du marché&nbsp;: avec
        {constat.minEchantillon} à {constat.maxEchantillon} ventes par an, une
        seule maison atypique déplace la médiane de plusieurs centaines d'euros
        au mètre carré. Il n'y a pas de tendance mesurable à lire ici, et la
        courbe ci-dessous ne doit pas être interprétée comme telle.
      {:else}
        Avec {constat.minEchantillon} à {constat.maxEchantillon} ventes par an,
        la médiane annuelle est stable et l'écart ci-dessus se lit&nbsp;: une
        vente atypique ne la déplace plus. Elle ne dit rien, en revanche, de la
        composition du marché — une année où il se vend surtout de petits
        appartements de centre-ville rend un prix au m² plus élevé sans qu'aucun
        bien n'ait renchéri.
      {/if}
      DVF enregistre par ailleurs des transactions sans leur contexte&nbsp;: une
      vente entre proches, un bien à rénover et une maison restaurée y figurent
      au même titre.
    </p>
  {/if}
  {#if mapErreur}<p class="err">La carte n'a pas pu être affichée : {mapErreur}</p>{/if}
  {#if fondAbsent}<p class="err">Le fond de carte n'a pas pu être chargé —
    les mutations ci-dessous restent à leur position exacte. Fond attendu&nbsp;:
    <code>static/carte/fond.pmtiles</code> (<code>scripts/carte_fond.py</code>).</p>{/if}

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
    <p class="hint">Prix médian au m² du bâti (maisons &amp; appartements) et nombre de mutations enregistrées, sur {periode}.</p>
    <div class="scrollx">
      <div class="yrbars">
        {#each dvfByYear as d}
          <div class="ycol" title="{d.year} : {d.medM2 ? Math.round(d.medM2) + ' €/m² médian sur ' + d.nBati + ' vente(s) de bâti' : 'aucune vente de bâti chiffrée'} · {d.n} mutation(s) au total">
            <span class="ym2">{d.medM2 ? Math.round(d.medM2).toLocaleString('fr-FR') + ' €/m²' : '—'}</span>
            <span class="ytrack"><span class="ybar" class:fragile={d.nBati > 0 && d.nBati < MEDIANE_FRAGILE}
                  style="height:{d.medM2 ? Math.max(2, 100 * d.medM2 / dvfM2Max) : 0}%"></span></span>
            <span class="yn" class:fragile={d.nBati > 0 && d.nBati < MEDIANE_FRAGILE}>{d.n}</span>
            <span class="yyear">{d.year}</span>
          </div>
        {/each}
      </div>
    </div>
    <p class="ylegend"><span class="sw"></span> hauteur et valeur du haut = prix médian €/m² du bâti, échelle depuis zéro ·
      nombre du bas = mutations enregistrées dans l'année
      {#if dvfByYear.some(d => d.nBati > 0 && d.nBati < MEDIANE_FRAGILE)}
        · <span class="sw fragile"></span> médiane établie sur moins de {MEDIANE_FRAGILE} ventes de bâti : elle désigne une vente ou deux, pas un marché
      {/if}
    </p>
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

  <details>
    <summary>Transactions {natureFilter !== 'all' ? `— ${natureFilter}` : ''} ({dvfFiltered.length})</summary>
    <p class="muted">Le détail vente par vente sert à vérifier un cas précis, pas
      à lire le marché — les constats ci-dessus s'en chargent. Données brutes et
      complètes&nbsp;: <a href="https://explore.data.gouv.fr/immobilier" target="_blank" rel="noopener">DVF sur data.gouv.fr</a>.</p>
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
  /* En grille, pas en flex-column : une barre en pourcentage placée à côté de
     trois libellés est un élément flexible comme eux, donc `flex-shrink` la
     rabote — les cinq barres finissaient TOUTES à 94 px, quelle que soit leur
     valeur. Le pourcentage ne veut dire quelque chose que dans une piste qui
     lui est réservée. */
  .ycol { flex: 1; min-width: 34px; display: grid; grid-template-rows: auto 1fr auto auto;
          justify-items: center; height: 100%; gap: .15rem; }
  .ytrack { display: flex; align-items: flex-end; width: 100%; height: 100%; justify-content: center; }
  .ym2 { font-size: .66rem; color: var(--ambre); font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ybar { width: 62%; max-width: 38px; background: var(--ambre); border-radius: 4px 4px 0 0; min-height: 2px; }
  .yn { font-size: .72rem; color: var(--gris); font-weight: 700; font-variant-numeric: tabular-nums; }
  .yyear { font-size: .72rem; color: var(--gris); }
  .ylegend { color: var(--gris-clair); font-size: .76rem; margin: .5rem 0 0; display: flex; align-items: center; gap: .4rem; }
  .ylegend .sw { width: 11px; height: 11px; border-radius: 3px; background: var(--ambre); display: inline-block; }
  /* Une médiane sur deux ventes se lit, mais ne se lit pas comme les autres. */
  .ybar.fragile, .ylegend .sw.fragile {
    background: repeating-linear-gradient(45deg, var(--ambre) 0 3px, var(--papier) 3px 6px);
  }
  .yn.fragile { color: var(--gris-clair); }
  .pointer { margin-top: 1.5rem; padding: .7rem .9rem; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; font-size: .9rem; color: #9a3412; }
  .pointer a { color: #c2410c; font-weight: 600; }
  .muted { color: var(--gris-clair); font-size: .85rem; } .err { color: var(--depense); }
  @media (max-width: 720px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
</style>
