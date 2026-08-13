<script>
  import { onMount } from 'svelte'
  import * as d3 from 'd3'
  import { api } from '$lib/api.js'

  // ── Données ────────────────────────────────────────────────────────────────
  let flows    = []
  let ofgl     = []
  let loading  = true

  let filterYear = ''
  let filterType = ''
  let activeTab  = 'flux'   // 'budget' | 'flux'

  // ── Graphiques ─────────────────────────────────────────────────────────────
  let chartDebtEl, chartEpargneEl, chartFonctEl

  const AGREGATS_FONCT = [
    'Recettes de fonctionnement',
    'Dépenses de fonctionnement',
  ]
  const AGREGATS_DETTE = ['Encours de dette']
  const AGREGATS_EPARGNE = ['Epargne brute', 'Epargne nette']
  const AGREGATS_FISCALITE = ['Impôts locaux', 'Dotation globale de fonctionnement', 'Concours de l\'Etat']
  const AGREGATS_PERSONNEL = ['Frais de personnel']

  // ── Utilitaires ────────────────────────────────────────────────────────────
  function fmtEur(n) {
    if (n == null) return '—'
    return Math.abs(n) >= 1e6
      ? (n / 1e6).toFixed(2) + ' M€'
      : Math.round(n).toLocaleString('fr-FR') + ' €'
  }
  function fmtK(n) {
    return n == null ? '—' : Math.round(n / 1000).toLocaleString('fr-FR') + ' K€'
  }

  // ── Données OFGL par agrégat ───────────────────────────────────────────────
  function byAgregat(name) {
    return ofgl
      .filter(r => r.agregat === name)
      .sort((a, b) => a.year - b.year)
  }

  // ── Dernière année disponible ──────────────────────────────────────────────
  $: lastYear = ofgl.length ? Math.max(...ofgl.map(r => r.year)) : null
  $: lastYearData = ofgl.filter(r => r.year === lastYear)
  $: getAgg = (name) => lastYearData.find(r => r.agregat === name)

  // ── Chargement ─────────────────────────────────────────────────────────────
  onMount(async () => {
    const [flowsRes, ofglRes] = await Promise.all([
      api.flows().catch(() => []),
      api.ofgl().catch(() => []),
    ])
    flows = Array.isArray(flowsRes) ? flowsRes : []
    ofgl  = Array.isArray(ofglRes)  ? ofglRes  : []
    if (flows.some(f => f.year === 2026)) filterYear = '2026'
    loading = false
    // Attendre le DOM puis dessiner
    setTimeout(() => {
      drawDebtChart()
      drawEpargneChart()
      drawFonctChart()
    }, 50)
  })

  // ── Flux filtrés ───────────────────────────────────────────────────────────
  $: years      = [...new Set(flows.map(f => f.year).filter(Boolean))].sort((a, b) => b - a)
  $: types      = [...new Set(flows.map(f => f.type).filter(Boolean))].sort()
  $: localLastYear = years.length ? years[0] : null
  $: filtered   = flows.filter(f => {
    if (filterYear && f.year !== Number(filterYear)) return false
    if (filterType && f.type !== filterType) return false
    return true
  })
  $: totalAmount = filtered.reduce((s, f) => s + (f.amount || 0), 0)

  // ── Graphique dette ────────────────────────────────────────────────────────
  function drawChart(el, seriesData, colors, yLabel, fmt = fmtK) {
    if (!el || !seriesData.length) return
    const W = el.clientWidth || 420
    const H = 180
    const margin = { top: 10, right: 20, bottom: 30, left: 62 }
    const w = W - margin.left - margin.right
    const h = H - margin.top  - margin.bottom

    d3.select(el).selectAll('*').remove()
    const svg = d3.select(el)
      .append('svg').attr('width', W).attr('height', H)
      .append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    const allYears = [...new Set(seriesData.flatMap(s => s.data.map(d => d.year)))].sort()
    const x = d3.scalePoint().domain(allYears).range([0, w]).padding(.3)
    const allVals = seriesData.flatMap(s => s.data.map(d => d.montant || 0))
    const yMin = Math.min(0, d3.min(allVals))
    const yMax = d3.max(allVals) * 1.1
    const y = d3.scaleLinear().domain([yMin, yMax]).range([h, 0])

    // Axes
    svg.append('g').attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).tickSize(0).tickPadding(8))
      .call(g => g.select('.domain').remove())
      .selectAll('text').attr('fill', '#64748b').attr('font-size', 10)

    svg.append('g')
      .call(d3.axisLeft(y).ticks(4).tickFormat(fmt))
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', '#1e293b').attr('x2', w))
      .selectAll('text').attr('fill', '#64748b').attr('font-size', 10)

    // Ligne zéro si données négatives
    if (yMin < 0) {
      svg.append('line')
        .attr('x1', 0).attr('x2', w)
        .attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', '#334155').attr('stroke-dasharray', '4,2')
    }

    // Séries
    seriesData.forEach((serie, i) => {
      const line = d3.line()
        .x(d => x(d.year))
        .y(d => y(d.montant || 0))
        .curve(d3.curveMonotoneX)

      svg.append('path')
        .datum(serie.data)
        .attr('fill', 'none')
        .attr('stroke', colors[i] || '#3b82f6')
        .attr('stroke-width', 2)
        .attr('d', line)

      // Points
      svg.selectAll(`.dot-${i}`)
        .data(serie.data)
        .join('circle')
        .attr('class', `dot-${i}`)
        .attr('cx', d => x(d.year))
        .attr('cy', d => y(d.montant || 0))
        .attr('r', 4)
        .attr('fill', colors[i] || '#3b82f6')
        .append('title')
        .text(d => `${d.year} : ${fmtEur(d.montant)}`)
    })
  }

  function drawDebtChart() {
    drawChart(chartDebtEl,
      [{ data: byAgregat('Encours de dette') }],
      ['#ef4444'],
      'Encours dette'
    )
  }

  function drawEpargneChart() {
    drawChart(chartEpargneEl,
      [
        { data: byAgregat('Epargne brute') },
        { data: byAgregat('Epargne nette') },
      ],
      ['#10b981', '#34d399'],
      'Épargne'
    )
  }

  function drawFonctChart() {
    drawChart(chartFonctEl,
      [
        { data: byAgregat('Recettes de fonctionnement') },
        { data: byAgregat('Dépenses de fonctionnement') },
      ],
      ['#3b82f6', '#f59e0b'],
      'Fonctionnement'
    )
  }
</script>

<svelte:head>
  <title>Finances — Lasalle</title>
</svelte:head>

<div class="page">
  <div class="toolbar">
    <h1>Finances</h1>
    <div class="tabs">
      <button class:active={activeTab==='flux'}   on:click={() => activeTab='flux'}>Flux locaux</button>
      <button class:active={activeTab==='budget'} on:click={() => activeTab='budget'}>Budget OFGL</button>
    </div>
    {#if activeTab === 'flux' && localLastYear}
      <span class="badge">Flux locaux jusqu’à {localLastYear}</span>
    {:else if lastYear}
      <span class="badge">OFGL jusqu’à {lastYear}</span>
    {/if}
  </div>

  {#if loading}
    <p class="hint">Chargement…</p>

  {:else if activeTab === 'budget'}
    <!-- ── KPIs ── -->
    <div class="kpis">
      {#each [
        { label: 'Recettes fonct.',   agg: 'Recettes de fonctionnement',  color: '#3b82f6' },
        { label: 'Dépenses fonct.',   agg: 'Dépenses de fonctionnement',  color: '#f59e0b' },
        { label: 'Épargne brute',     agg: 'Epargne brute',               color: '#10b981' },
        { label: 'Encours dette',     agg: 'Encours de dette',             color: '#ef4444' },
        { label: 'Annuité dette',     agg: 'Annuité de la dette',          color: '#f97316' },
        { label: 'Frais de personnel',agg: 'Frais de personnel',           color: '#8b5cf6' },
        { label: 'DGF',               agg: 'Dotation globale de fonctionnement', color: '#06b6d4' },
        { label: 'Impôts locaux',     agg: 'Impôts locaux',               color: '#84cc16' },
      ] as k}
        {@const r = getAgg(k.agg)}
        <div class="kpi">
          <div class="kpi-val" style="color:{k.color}">{fmtEur(r?.montant)}</div>
          <div class="kpi-sub">{k.label}</div>
          {#if r?.euros_par_habitant}
            <div class="kpi-hab">{Math.round(r.euros_par_habitant)} €/hab</div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- ── Graphiques ── -->
    <div class="charts">
      <div class="chart-block">
        <div class="chart-title">
          Encours de dette 2017–{lastYear}
          <span class="legend"><span class="dot" style="background:#ef4444"></span>Dette</span>
        </div>
        <div bind:this={chartDebtEl} class="chart-area"></div>
      </div>

      <div class="chart-block">
        <div class="chart-title">
          Épargne 2017–{lastYear}
          <span class="legend">
            <span class="dot" style="background:#10b981"></span>Brute
            <span class="dot" style="background:#34d399"></span>Nette
          </span>
        </div>
        <div bind:this={chartEpargneEl} class="chart-area"></div>
      </div>

      <div class="chart-block">
        <div class="chart-title">
          Fonctionnement 2017–{lastYear}
          <span class="legend">
            <span class="dot" style="background:#3b82f6"></span>Recettes
            <span class="dot" style="background:#f59e0b"></span>Dépenses
          </span>
        </div>
        <div bind:this={chartFonctEl} class="chart-area"></div>
      </div>
    </div>

    <!-- ── Tableau complet OFGL ── -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Agrégat</th>
            {#each [...new Set(ofgl.map(r => r.year))].sort() as y}
              <th>{y}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each [...new Set(ofgl.map(r => r.agregat))].sort() as agg}
            <tr>
              <td class="agg-name">{agg}</td>
              {#each [...new Set(ofgl.map(r => r.year))].sort() as y}
                {@const r = ofgl.find(o => o.year === y && o.agregat === agg)}
                <td class="num" class:neg={r?.montant < 0}>{r ? fmtK(r.montant) : '—'}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

  {:else}
    <!-- ── Onglet flux locaux ── -->
    <div class="toolbar-sub">
      <select bind:value={filterYear}>
        <option value="">Toutes les années</option>
        {#each years as y}<option value={y}>{y}</option>{/each}
      </select>
      <select bind:value={filterType}>
        <option value="">Tous les types</option>
        {#each types as t}<option value={t}>{t}</option>{/each}
      </select>
      <span class="total">{filtered.length} flux — {fmtEur(totalAmount)}</span>
    </div>

    <div class="list">
      {#each filtered as f}
        <div class="flow-card">
          <div class="flow-head">
            <span class="year">{f.year}</span>
            <span class="ftype">{f.type}</span>
            <span class="amount">{fmtEur(f.amount)}</span>
          </div>
          <div class="flow-parties">
            <span class="from">{f.from_name || '?'}</span>
            <span class="arrow">→</span>
            <span class="to">{f.to_name || '?'}</span>
          </div>
          {#if f.description}
            <p class="desc">{f.description}</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .page { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  .toolbar {
    display: flex; align-items: center; gap: 1rem;
    padding: .6rem 1.25rem;
    background: #1e293b; border-bottom: 1px solid #334155;
    flex-shrink: 0; flex-wrap: wrap;
  }
  h1 { font-size: 1rem; font-weight: 700; }

  .tabs { display: flex; gap: 2px; }
  .tabs button {
    padding: .25rem .75rem; border-radius: 6px;
    font-size: .8rem; background: #0f172a; color: #64748b;
    border: 1px solid #334155;
  }
  .tabs button.active { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
  .tabs button:hover:not(.active) { color: #e2e8f0; }

  .badge {
    margin-left: auto; font-size: .72rem; color: #475569;
    background: #0f172a; padding: 2px 8px; border-radius: 999px;
  }

  /* ── KPIs ── */
  .kpis {
    display: flex; flex-wrap: wrap; gap: .75rem;
    padding: .75rem 1.25rem; flex-shrink: 0;
    background: #0f172a; border-bottom: 1px solid #1e293b;
  }
  .kpi {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 8px; padding: .5rem .9rem;
    min-width: 110px;
  }
  .kpi-val { font-size: 1.05rem; font-weight: 700; }
  .kpi-sub { font-size: .7rem; color: #64748b; margin-top: 2px; }
  .kpi-hab { font-size: .68rem; color: #475569; }

  /* ── Graphiques ── */
  .charts {
    display: flex; flex-wrap: wrap; gap: .75rem;
    padding: .75rem 1.25rem; flex-shrink: 0;
    background: #0f172a; border-bottom: 1px solid #1e293b;
  }
  .chart-block {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 8px; padding: .6rem .8rem;
    flex: 1; min-width: 280px;
  }
  .chart-title {
    font-size: .75rem; color: #94a3b8; margin-bottom: .4rem;
    display: flex; align-items: center; gap: .5rem;
  }
  .legend { display: flex; align-items: center; gap: .35rem; margin-left: auto; font-size: .7rem; color: #64748b; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
  .chart-area { width: 100%; }

  /* ── Tableau ── */
  .table-wrap {
    flex: 1; overflow: auto; padding: .75rem 1.25rem;
  }
  table { width: 100%; border-collapse: collapse; font-size: .75rem; }
  th {
    text-align: right; padding: .3rem .6rem;
    color: #64748b; font-weight: 600; border-bottom: 1px solid #334155;
    white-space: nowrap;
  }
  th:first-child { text-align: left; }
  td { padding: .25rem .6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }
  .agg-name { color: #94a3b8; white-space: nowrap; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .num.neg { color: #f87171; }
  tr:hover td { background: #1e293b; }

  /* ── Flux ── */
  .toolbar-sub {
    display: flex; align-items: center; gap: 1rem;
    padding: .5rem 1.25rem; background: #0f172a;
    border-bottom: 1px solid #1e293b; flex-shrink: 0;
  }
  select {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 6px; color: #e2e8f0;
    font-size: .8rem; padding: .3rem .6rem;
  }
  .total { color: #10b981; font-size: .82rem; font-weight: 600; margin-left: auto; }

  .list {
    flex: 1; overflow-y: auto; padding: 1rem 1.25rem;
    display: flex; flex-direction: column; gap: .5rem;
  }
  .flow-card {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 8px; padding: .6rem 1rem;
  }
  .flow-head { display: flex; gap: .5rem; align-items: center; margin-bottom: .25rem; }
  .year { color: #64748b; font-size: .78rem; }
  .ftype {
    background: #0f172a; padding: 1px 8px; border-radius: 999px;
    font-size: .7rem; color: #f59e0b;
  }
  .amount { color: #10b981; font-weight: 700; font-size: .88rem; margin-left: auto; }
  .flow-parties { display: flex; gap: .4rem; align-items: center; font-size: .82rem; }
  .from { color: #94a3b8; }
  .arrow { color: #475569; }
  .to { color: #e2e8f0; font-weight: 500; }
  .desc { font-size: .75rem; color: #475569; margin-top: .2rem; font-style: italic; }

  .hint { color: #475569; padding: 2rem; text-align: center; }
</style>
