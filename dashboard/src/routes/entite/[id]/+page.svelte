<script>
  import { couleur } from '$lib/theme.js'
  import { lienSur } from '$lib/liens.js'
  import { SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { api } from '$lib/api.js'

  let entity    = null
  let synthesis = null
  let annexe    = []
  let loading   = true
  let error     = ''
  let activeTab = 'apercu'
  let L, mapEl, mapObj

  $: eid = parseInt($page.params.id)

  onMount(async () => {
    await load()
  })

  async function load() {
    loading = true; error = ''
    try {
      const [e, s, ba] = await Promise.all([
        api.entity(eid),
        api.entitySynthesis(eid),
        api.budgetAnnexe(eid).catch(() => []),
      ])
      entity   = e
      synthesis = s
      annexe   = Array.isArray(ba) ? ba : []
    } catch(e) { error = e.message }
    finally { loading = false }
  }

  // Mini-carte Leaflet (montée après que entity soit chargée)
  $: if (entity?.lat && mapEl && !mapObj) initMap()

  async function initMap() {
    if (typeof window === 'undefined') return
    L = (await import('leaflet')).default
    mapObj = L.map(mapEl, { zoomControl: false, attributionControl: true })
    L.tileLayer('https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0' +
      '&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM' +
      '&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png', {
      // CARTO exige désormais une clé : la carte restait grise, marquée
      // « API key required ». Le plan IGN, sans clé, est celui de l'éditeur.
      attribution: '&copy; <a href="https://geoservices.ign.fr/">IGN</a>'
    }).addTo(mapObj)
    mapObj.setView([entity.lat, entity.lng], 15)
    L.circleMarker([entity.lat, entity.lng], { radius: 8, color: couleur('--lien'), fillColor: couleur('--lien'), fillOpacity: .8 })
     .addTo(mapObj)
  }

  const TYPE_LABELS = {
    person: 'Personne', business: 'Entreprise', association: 'Association',
    service: 'Service public', place: 'Lieu',
  }

  function fmtDate(d) { return d ? d.slice(0, 10) : '—' }
  function fmtMontant(v) { return v != null ? Math.round(v).toLocaleString('fr-FR') + ' €' : '—' }

  $: relationsIn  = entity?.relations?.filter(r => r.to_id   === eid) ?? []
  $: relationsOut = entity?.relations?.filter(r => r.from_id === eid) ?? []
  $: flowsIn      = entity?.flows?.filter(f => f.to_id   === eid) ?? []
  $: flowsOut     = entity?.flows?.filter(f => f.from_id === eid) ?? []

  $: annexeSections = [...new Set(annexe.map(r => r.section))]

  $: totalFluxIn  = flowsIn.reduce((s, f) => s + (f.amount ?? 0), 0)
  $: totalFluxOut = flowsOut.reduce((s, f) => s + (f.amount ?? 0), 0)

  const TABS = [
    { id: 'apercu',    label: 'Aperçu' },
    { id: 'relations', label: 'Relations' },
    { id: 'flux',      label: 'Flux financiers' },
    { id: 'events',    label: 'Événements' },
    { id: 'budget',    label: 'Budget' },
    { id: 'ia',        label: 'Synthèse IA' },
  ]
</script>

<svelte:head>
  <title>{entity?.name ?? 'Entité'} — {SITE_NOM}</title>
</svelte:head>

{#if loading}
  <div class="loading">Chargement…</div>
{:else if error}
  <div class="err-page">{error}</div>
{:else if entity}
<div class="entity-page">

  <!-- ── En-tête ── -->
  <header class="ent-header">
    <div class="ent-title">
      <span class="type-badge type-{entity.type}">{TYPE_LABELS[entity.type] ?? entity.type}</span>
      <h1>{entity.name}</h1>
      {#if entity.short_name && entity.short_name !== entity.name}
        <span class="short-name">({entity.short_name})</span>
      {/if}
    </div>
    <div class="ent-meta">
      {#if entity.address}<span class="meta-item">📍 {entity.address}</span>{/if}
      {#if entity.siren}<span class="meta-item">SIREN {entity.siren}</span>{/if}
      {#if entity.rna_id}<span class="meta-item">RNA {entity.rna_id}</span>{/if}
      {#if entity.creation_date || entity.asso_creation_date}
        <span class="meta-item">Créée {entity.creation_date ?? entity.asso_creation_date}</span>
      {/if}
      {#if entity.biz_status || entity.asso_status}
        <span class="meta-item status-{(entity.biz_status ?? entity.asso_status)?.toLowerCase()}">{entity.biz_status ?? entity.asso_status}</span>
      {/if}
    </div>
    {#if entity.lat}
      <div class="mini-map" bind:this={mapEl}></div>
    {/if}
  </header>

  <!-- ── Tabs ── -->
  <nav class="ent-tabs">
    {#each TABS as t}
      {#if t.id !== 'budget' || annexe.length > 0}
        <button class:active={activeTab === t.id} on:click={() => activeTab = t.id}>
          {t.label}
          {#if t.id === 'relations'}<span class="tc">{entity.relations?.length ?? 0}</span>{/if}
          {#if t.id === 'flux'}<span class="tc">{entity.flows?.length ?? 0}</span>{/if}
          {#if t.id === 'events'}<span class="tc">{entity.events?.length ?? 0}</span>{/if}
        </button>
      {/if}
    {/each}
  </nav>

  <div class="tab-body">

    <!-- Aperçu -->
    {#if activeTab === 'apercu'}
      <div class="apercu-grid">
        {#if entity.type === 'person'}
          <div class="info-card">
            <div class="card-title">Identité</div>
            <dl>
              <dt>Prénom</dt><dd>{entity.firstname ?? '—'}</dd>
              <dt>Nom</dt><dd>{entity.lastname ?? '—'}</dd>
              {#if entity.birth_year}<dt>Naissance</dt><dd>{entity.birth_year}</dd>{/if}
            </dl>
          </div>
        {/if}
        {#if entity.type === 'business'}
          <div class="info-card">
            <div class="card-title">Entreprise</div>
            <dl>
              <dt>Forme juridique</dt><dd>{entity.legal_form ?? '—'}</dd>
              <dt>Capital</dt><dd>{entity.capital ? entity.capital.toLocaleString('fr-FR') + ' €' : '—'}</dd>
              <dt>Effectif</dt><dd>{entity.employees_range ?? '—'}</dd>
              <dt>NAF</dt><dd>{entity.naf_label ?? entity.naf_code ?? '—'}</dd>
            </dl>
          </div>
        {/if}
        {#if entity.type === 'association'}
          <div class="info-card">
            <div class="card-title">Association</div>
            <dl>
              <dt>Objet</dt><dd class="obj">{entity.asso_object ?? '—'}</dd>
              <dt>Statut</dt><dd>{entity.asso_status ?? '—'}</dd>
            </dl>
          </div>
        {/if}
        <div class="info-card">
          <div class="card-title">Flux financiers</div>
          <dl>
            <dt>Reçus</dt><dd class="montant-pos">{fmtMontant(totalFluxIn)}</dd>
            <dt>Émis</dt><dd class="montant-neg">{fmtMontant(totalFluxOut)}</dd>
            <dt>Flux total</dt><dd>{flowsIn.length + flowsOut.length} ligne(s)</dd>
          </dl>
        </div>
        <div class="info-card">
          <div class="card-title">Réseau</div>
          <dl>
            <dt>Relations</dt><dd>{entity.relations?.length ?? 0}</dd>
            <dt>Événements</dt><dd>{entity.events?.length ?? 0}</dd>
          </dl>
        </div>
      </div>

    <!-- Relations -->
    {:else if activeTab === 'relations'}
      {#if !entity.relations?.length}
        <p class="empty">Aucune relation documentée.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Type</th><th>De</th><th>Vers</th><th>Depuis</th><th>Jusqu'au</th><th>Conf.</th></tr></thead>
          <tbody>
            {#each entity.relations as r}
              <tr>
                <td><span class="rel-badge">{r.relation_type}</span></td>
                <td>
                  {#if r.from_id === eid}
                    <span class="self-name">{entity.name}</span>
                  {:else}
                    <a href="/entite/{r.from_id}" class="ent-link">{r.from_name}</a>
                  {/if}
                </td>
                <td>
                  {#if r.to_id === eid}
                    <span class="self-name">{entity.name}</span>
                  {:else}
                    <a href="/entite/{r.to_id}" class="ent-link">{r.to_name}</a>
                  {/if}
                </td>
                <td class="muted">{fmtDate(r.since)}</td>
                <td class="muted">{r.until ? fmtDate(r.until) : 'en cours'}</td>
                <td><span class="conf-{r.confidence}">{r.confidence}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    <!-- Flux financiers -->
    {:else if activeTab === 'flux'}
      {#if !entity.flows?.length}
        <p class="empty">Aucun flux financier documenté.</p>
      {:else}
        <div class="flux-summary">
          <span class="flux-kpi pos">Reçus : {fmtMontant(totalFluxIn)}</span>
          <span class="flux-kpi neg">Émis : {fmtMontant(totalFluxOut)}</span>
        </div>
        <table class="data-table">
          <thead><tr><th>Type</th><th>Année</th><th>De</th><th>Vers</th><th>Montant</th><th>Source</th></tr></thead>
          <tbody>
            {#each entity.flows as f}
              <tr class:flow-in={f.to_id === eid} class:flow-out={f.from_id === eid}>
                <td><span class="flux-badge">{f.type}</span></td>
                <td>{f.year ?? '—'}</td>
                <td>
                  {#if f.from_id === eid}<span class="self-name">{entity.name}</span>
                  {:else if f.from_id}<a href="/entite/{f.from_id}" class="ent-link">{f.from_name}</a>
                  {:else}<span class="muted">—</span>{/if}
                </td>
                <td>
                  {#if f.to_id === eid}<span class="self-name">{entity.name}</span>
                  {:else if f.to_id}<a href="/entite/{f.to_id}" class="ent-link">{f.to_name}</a>
                  {:else}<span class="muted">—</span>{/if}
                </td>
                <td class="montant">{fmtMontant(f.amount)}</td>
                <td class="muted source-cell">{f.source ?? '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    <!-- Événements -->
    {:else if activeTab === 'events'}
      {#if !entity.events?.length}
        <p class="empty">Aucun événement documenté.</p>
      {:else}
        <div class="timeline">
          {#each entity.events as ev}
            <div class="tl-item">
              <div class="tl-date">{fmtDate(ev.date)}</div>
              <div class="tl-body">
                <span class="tl-type">{ev.type}</span>
                <span class="tl-title">{ev.title}</span>
                {#if ev.source_url}
                  <a href={lienSur(ev.source_url)} target="_blank" rel="noopener" class="tl-src">↗</a>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

    <!-- Budget annexe -->
    {:else if activeTab === 'budget'}
      {#if !annexe.length}
        <p class="empty">Aucun budget annexe disponible.</p>
      {:else}
        {#each annexeSections as section}
          <h3 class="section-h">{section}</h3>
          <table class="data-table">
            <thead><tr><th>Sens</th><th>Compte</th><th>Libellé</th><th>Montant</th><th>Année</th></tr></thead>
            <tbody>
              {#each annexe.filter(r => r.section === section) as r}
                <tr>
                  <td><span class="sens-{r.sens}">{r.sens}</span></td>
                  <td class="muted">{r.compte ?? '—'}</td>
                  <td>{r.libelle}</td>
                  <td class="montant">{fmtMontant(r.montant)}</td>
                  <td class="muted">{r.year}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/each}
      {/if}

    <!-- IA -->
    {:else if activeTab === 'ia'}
      {#if synthesis}
        <div class="synth-block">
          <div class="synth-header">Synthèse IA — {synthesis.model ?? 'Gemma'}</div>
          <div class="synth-body">{synthesis.content}</div>
          <div class="synth-meta muted">Générée le {fmtDate(synthesis.created_at)}</div>
        </div>
      {:else}
        <div class="ia-empty">
          <p>Aucune synthèse IA disponible pour cette entité.</p>
          <a href="/atelier/ia?q={encodeURIComponent(entity.name)}" class="btn-ia">
            Interroger la recherche IA →
          </a>
        </div>
      {/if}
    {/if}

  </div>
</div>
{/if}

<style>
  .loading, .err-page { color: var(--texte-doux); text-align: center; margin-top: 4rem; font-size: .9rem; }

  .entity-page { max-width: 1000px; padding: 1rem; overflow-y: auto; height: 100%; }

  /* Header */
  .ent-header {
    background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px;
    padding: .9rem 1rem; margin-bottom: .75rem;
    display: grid; grid-template-columns: 1fr auto; gap: .5rem;
  }
  .ent-title { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
  h1 { font-size: 1.15rem; font-weight: 700; color: var(--texte); margin: 0; }
  .short-name { font-size: .8rem; color: var(--texte-doux); }
  .ent-meta { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .35rem; font-size: .75rem; color: var(--texte-doux); grid-column: 1; }
  .meta-item { display: flex; align-items: center; gap: .2rem; }

  .type-badge {
    font-size: .65rem; padding: 2px 7px; border-radius: 999px; font-weight: 700;
    white-space: nowrap;
  }
  .type-person      { background: var(--type-personne); color: var(--danger-texte); }
  .type-business    { background: var(--type-entreprise); color: var(--info); }
  .type-association { background: var(--type-association); color: var(--succes-texte); }
  .type-service     { background: var(--type-service); color: var(--alerte-texte); }
  .type-place       { background: var(--type-lieu); color: var(--sur-accent); }

  .mini-map {
    width: 180px; height: 120px; border-radius: 6px;
    border: 1px solid var(--bordure); grid-row: 1 / span 2; grid-column: 2;
  }

  /* Tabs */
  .ent-tabs {
    display: flex; gap: .2rem; border-bottom: 1px solid var(--bordure);
    margin-bottom: .75rem; flex-wrap: wrap;
  }
  .ent-tabs button {
    padding: .35rem .7rem; font-size: .78rem; color: var(--texte-doux);
    border-bottom: 2px solid transparent; background: none; border-radius: 4px 4px 0 0;
    display: flex; align-items: center; gap: .3rem;
  }
  .ent-tabs button.active { color: var(--lien); border-bottom-color: var(--lien); }
  .ent-tabs button:hover:not(.active) { color: var(--texte); }
  .tc { font-size: .65rem; background: var(--surface-2); color: var(--texte-doux); border-radius: 999px; padding: 1px 4px; }

  /* Aperçu */
  .apercu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap: .6rem; }
  .info-card { background: var(--surface); border: 1px solid var(--bordure); border-radius: 6px; padding: .65rem .8rem; }
  .card-title { font-size: .7rem; font-weight: 700; color: var(--texte-doux); text-transform: uppercase;
    letter-spacing: .05em; margin-bottom: .4rem; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: .15rem .75rem; font-size: .77rem; }
  dt { color: var(--texte-doux); white-space: nowrap; }
  dd { color: var(--texte); }
  dd.obj { color: var(--texte-2); font-size: .72rem; line-height: 1.4; }
  .montant-pos { color: var(--succes); font-weight: 700; }
  .montant-neg { color: var(--danger); font-weight: 700; }

  /* Table commune */
  .data-table { width: 100%; border-collapse: collapse; font-size: .77rem; }
  .data-table th { background: var(--surface); color: var(--texte-doux); font-size: .65rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em; padding: .4rem .6rem;
    border-bottom: 1px solid var(--bordure); text-align: left; }
  .data-table td { padding: .35rem .6rem; border-bottom: 1px solid var(--bordure-douce); color: var(--texte-2); vertical-align: top; }
  .data-table tr:hover td { background: var(--surface); }
  .data-table tr.flow-in td  { border-left: 2px solid var(--succes); }
  .data-table tr.flow-out td { border-left: 2px solid var(--danger); }

  .ent-link { color: var(--info); }
  .ent-link:hover { text-decoration: underline; }
  .self-name { color: var(--texte); font-weight: 600; }
  .muted { color: var(--texte-doux); }
  .montant { font-weight: 700; color: var(--alerte); }
  .source-cell { font-size: .7rem; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .rel-badge { font-size: .67rem; background: var(--surface-2); padding: 1px 5px; border-radius: 3px; color: var(--texte-doux); }
  .flux-badge { font-size: .67rem; background: var(--info-doux); padding: 1px 5px; border-radius: 3px; color: var(--info); }
  .conf-verified  { color: var(--succes); font-size: .72rem; }
  .conf-confirmed { color: var(--info); font-size: .72rem; }
  .conf-probable  { color: var(--alerte); font-size: .72rem; }

  /* Flux summary */
  .flux-summary { display: flex; gap: 1rem; margin-bottom: .5rem; }
  .flux-kpi { font-size: .85rem; font-weight: 700; padding: .25rem .6rem;
    background: var(--surface); border-radius: 5px; }
  .flux-kpi.pos { color: var(--succes); }
  .flux-kpi.neg { color: var(--danger); }

  /* Timeline */
  .timeline { display: flex; flex-direction: column; gap: 0; }
  .tl-item { display: grid; grid-template-columns: 100px 1fr; gap: .5rem;
    padding: .3rem 0; border-bottom: 1px solid var(--bordure-douce); font-size: .77rem; }
  .tl-date { color: var(--texte-doux); white-space: nowrap; padding-top: 1px; }
  .tl-body { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
  .tl-type { font-size: .65rem; background: var(--surface-2); padding: 1px 5px; border-radius: 3px; color: var(--texte-doux); }
  .tl-title { color: var(--texte-2); flex: 1; }
  .tl-src { font-size: .8rem; color: var(--lien); }

  /* Budget annexe */
  .section-h { font-size: .82rem; font-weight: 600; color: var(--alerte); margin: .75rem 0 .35rem; }
  .sens-recette { color: var(--succes); font-size: .7rem; font-weight: 700; }
  .sens-depense { color: var(--danger); font-size: .7rem; font-weight: 700; }

  /* IA */
  .synth-block { background: var(--succes-doux); border: 1px solid var(--succes-bordure); border-radius: 8px; overflow: hidden; }
  .synth-header { background: var(--succes-bordure); color: var(--succes); font-size: .72rem; font-weight: 700;
    padding: .3rem .75rem; text-transform: uppercase; letter-spacing: .05em; }
  .synth-body { padding: .75rem; font-size: .82rem; color: var(--succes-texte); line-height: 1.6; white-space: pre-wrap; }
  .synth-meta { padding: .3rem .75rem .5rem; font-size: .7rem; }
  .ia-empty { text-align: center; margin-top: 2rem; }
  .ia-empty p { color: var(--texte-doux); margin-bottom: 1rem; }
  .btn-ia { background: var(--accent-fort); color: var(--sur-accent); border-radius: 6px; padding: .4rem .85rem; font-size: .8rem; }
  .btn-ia:hover { background: var(--bouton); }

  .empty { color: var(--texte-doux); text-align: center; margin-top: 2rem; font-size: .85rem; }

  .status-active, .status-actif { color: var(--succes); }
  .status-closed, .status-fermé, .status-radiée { color: var(--danger); }
</style>
