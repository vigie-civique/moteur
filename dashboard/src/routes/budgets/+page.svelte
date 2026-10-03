<script>
  import { SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import * as d3 from 'd3'
  import { api } from '$lib/api.js'

  let ofgl    = []
  let budget  = []
  let annexe  = []
  let loading = true
  let error   = ''
  let activeTab = 'principal'
  let selectedYear = ''

  let chartFonctEl, chartDetteEl

  onMount(async () => {
    loading = true
    try {
      const [o, b, ba] = await Promise.all([
        api.ofgl(),
        api.budget(),
        api.budgetAnnexe(),
      ])
      ofgl   = Array.isArray(o) ? o : []
      budget = Array.isArray(b) ? b : []
      annexe = Array.isArray(ba) ? ba : []
    } catch(e) { error = e.message }
    finally { loading = false }
  })

  // ── OFGL helpers ─────────────────────────────────────────────────────────────
  $: years      = [...new Set(ofgl.map(r => r.year))].sort().reverse()
  $: lastYear   = years[0] ?? null
  $: yearData   = ofgl.filter(r => r.year === (selectedYear ? +selectedYear : lastYear))
  $: getAgg     = (name) => yearData.find(r => r.agregat === name)
  $: fmtEur     = (n) => n == null ? '—' : Math.abs(n) >= 1e6
      ? (n / 1e6).toFixed(2) + ' M€'
      : Math.round(n).toLocaleString('fr-FR') + ' €'

  const KPIS = [
    { label: 'Recettes fonct.', key: 'Recettes de fonctionnement', color: 'var(--succes)' },
    { label: 'Dépenses fonct.', key: 'Dépenses de fonctionnement', color: 'var(--danger)' },
    { label: 'Épargne brute',   key: 'Epargne brute',              color: 'var(--lien)' },
    { label: 'Dette',           key: 'Encours de dette',           color: 'var(--alerte)' },
    { label: 'DGF',             key: 'Dotation globale de fonctionnement', color: 'var(--info)' },
    { label: 'Impôts locaux',   key: 'Impôts locaux',              color: 'var(--succes)' },
  ]

  // ── Budget principal ──────────────────────────────────────────────────────────
  $: budgetYears = [...new Set(budget.map(r => r.year))].sort().reverse()
  $: budgetYear  = selectedYear || (budgetYears[0] ?? '')
  $: budgetFiltered = budget.filter(r => r.year === +budgetYear)
  $: budgetSections = [...new Set(budgetFiltered.map(r => r.section))].sort()

  // ── Budget annexe ─────────────────────────────────────────────────────────────
  $: annexeEntities = [...new Map(annexe.map(r => [r.entity_id, { id: r.entity_id, name: r.entity_name }])).values()]

  $: selectedEntity = annexeEntities[0]?.id ?? null
  let selEntity = null
  $: annexeFiltered = annexe.filter(r => r.entity_id === (selEntity ?? annexeEntities[0]?.id))
  $: annexeSections = [...new Set(annexeFiltered.map(r => r.section))]
</script>

<svelte:head><title>Budgets — {SITE_NOM}</title></svelte:head>

<div class="budgets-page">
  <div class="page-header">
    <h1>Finances publiques</h1>
    <span class="subtitle">Budget communal, budgets annexes et données OFGL comparatives</span>
  </div>

  <nav class="tabs">
    {#each [
      { id:'principal',  label:'Budget principal' },
      { id:'annexes',    label:`Budgets annexes (${annexeEntities.length})` },
      { id:'ofgl',       label:'OFGL comparatif' },
    ] as t}
      <button class:active={activeTab === t.id} on:click={() => activeTab = t.id}>{t.label}</button>
    {/each}
  </nav>

  {#if error}<p class="err">{error}</p>{/if}

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else}

    <!-- Budget principal -->
    {#if activeTab === 'principal'}
      <div class="filter-bar">
        <label>Année :
          <select bind:value={selectedYear}>
            {#each budgetYears as y}
              <option value={y}>{y}</option>
            {/each}
          </select>
        </label>
      </div>

      {#if !budgetFiltered.length}
        <p class="muted-center">Aucune donnée pour {budgetYear}.</p>
      {:else}
        {#each budgetSections as section}
          <h3 class="section-h">{section}</h3>
          <table class="data-table">
            <thead><tr><th>Sens</th><th>Compte</th><th>Libellé</th><th>Montant</th></tr></thead>
            <tbody>
              {#each budgetFiltered.filter(r => r.section === section) as r}
                <tr>
                  <td><span class="sens-{r.sens}">{r.sens}</span></td>
                  <td class="muted">{r.compte ?? '—'}</td>
                  <td>{r.libelle ?? '—'}</td>
                  <td class="montant">{r.montant != null ? Math.round(r.montant).toLocaleString('fr-FR') + ' €' : '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/each}
      {/if}

    <!-- Budgets annexes -->
    {:else if activeTab === 'annexes'}
      {#if !annexeEntities.length}
        <p class="muted-center">Aucun budget annexe disponible.</p>
      {:else}
        <div class="filter-bar">
          <label>Entité :
            <select bind:value={selEntity}>
              {#each annexeEntities as ae}
                <option value={ae.id}>{ae.name}</option>
              {/each}
            </select>
          </label>
          {#if selEntity}<a href="/entite/{selEntity}" class="ent-link-sm">Voir la fiche →</a>{/if}
        </div>
        {#each annexeSections as section}
          <h3 class="section-h">{section}</h3>
          <table class="data-table">
            <thead><tr><th>Sens</th><th>Compte</th><th>Libellé</th><th>Montant</th><th>Année</th></tr></thead>
            <tbody>
              {#each annexeFiltered.filter(r => r.section === section) as r}
                <tr>
                  <td><span class="sens-{r.sens}">{r.sens}</span></td>
                  <td class="muted">{r.compte ?? '—'}</td>
                  <td>{r.libelle}</td>
                  <td class="montant">{r.montant != null ? Math.round(r.montant).toLocaleString('fr-FR') + ' €' : '—'}</td>
                  <td class="muted">{r.year}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/each}
      {/if}

    <!-- OFGL comparatif -->
    {:else if activeTab === 'ofgl'}
      <div class="filter-bar">
        <label>Année :
          <select bind:value={selectedYear}>
            <option value="">Dernière ({lastYear})</option>
            {#each years as y}
              <option value={y}>{y}</option>
            {/each}
          </select>
        </label>
      </div>

      <div class="kpi-grid">
        {#each KPIS as k}
          {@const val = getAgg(k.key)}
          <div class="kpi-card">
            <div class="kpi-label">{k.label}</div>
            <div class="kpi-val" style="color:{k.color}">{fmtEur(val?.valeur ?? val?.value)}</div>
            {#if val?.strate}
              <div class="kpi-strate muted">Strate : {fmtEur(val.strate)}</div>
            {/if}
          </div>
        {/each}
      </div>

      <h3 class="section-h" style="margin-top:1rem">Données brutes</h3>
      <table class="data-table">
        <thead><tr><th>Agrégat</th><th>Valeur</th><th>Strate</th><th>Année</th></tr></thead>
        <tbody>
          {#each yearData as r}
            <tr>
              <td>{r.agregat}</td>
              <td class="montant">{fmtEur(r.valeur ?? r.value)}</td>
              <td class="muted">{r.strate ? fmtEur(r.strate) : '—'}</td>
              <td class="muted">{r.year}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

  {/if}
</div>

<style>
  .budgets-page { padding: 1.2rem; max-width: 1000px; overflow-y: auto; }
  .page-header { margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: var(--texte); margin: 0; }
  .subtitle { font-size: .78rem; color: var(--texte-doux); }

  .tabs { display: flex; gap: .25rem; border-bottom: 1px solid var(--bordure); margin-bottom: .85rem; flex-wrap: wrap; }
  .tabs button { padding: .35rem .7rem; font-size: .78rem; color: var(--texte-doux);
    border-bottom: 2px solid transparent; background: none; border-radius: 4px 4px 0 0; }
  .tabs button.active { color: var(--lien); border-bottom-color: var(--lien); }
  .tabs button:hover:not(.active) { color: var(--texte); }

  .filter-bar { display: flex; align-items: center; gap: .75rem; margin-bottom: .6rem; font-size: .77rem; color: var(--texte-doux); }
  .filter-bar select { background: var(--surface); border: 1px solid var(--bordure); color: var(--texte);
    border-radius: 4px; padding: .2rem .4rem; }
  .ent-link-sm { font-size: .75rem; color: var(--lien); }

  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap: .5rem; }
  .kpi-card { background: var(--surface); border: 1px solid var(--bordure); border-radius: 6px; padding: .5rem .75rem; }
  .kpi-label { font-size: .68rem; color: var(--texte-doux); text-transform: uppercase; letter-spacing: .04em; margin-bottom: .2rem; }
  .kpi-val   { font-size: .95rem; font-weight: 700; }
  .kpi-strate { font-size: .68rem; margin-top: .2rem; }

  .section-h { font-size: .82rem; font-weight: 600; color: var(--alerte); margin: .75rem 0 .4rem; }

  .data-table { width: 100%; border-collapse: collapse; font-size: .77rem; }
  .data-table th { background: var(--surface); color: var(--texte-doux); font-size: .65rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em; padding: .4rem .6rem;
    border-bottom: 1px solid var(--bordure); text-align: left; }
  .data-table td { padding: .35rem .6rem; border-bottom: 1px solid var(--bordure-douce); color: var(--texte-2); }
  .data-table tr:hover td { background: var(--surface); }

  .montant { font-weight: 700; color: var(--alerte); }
  .muted { color: var(--texte-doux); }
  .sens-recette { color: var(--succes); font-size: .7rem; font-weight: 700; }
  .sens-depense { color: var(--danger); font-size: .7rem; font-weight: 700; }

  .err { color: var(--danger); }
  .muted-center { color: var(--texte-doux); text-align: center; margin-top: 2rem; }
</style>
