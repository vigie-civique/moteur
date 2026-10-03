<script>
  import { COMMUNE } from '$lib/instance.js'
  import { onMount, onDestroy } from 'svelte'
  import * as d3 from 'd3'
  import { api } from '$lib/api.js'
  import { couleur, themeEffectif } from '$lib/theme.js'

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
    setTimeout(dessiner, 50)
  })

  function dessiner() {
    drawDebtChart()
    drawEpargneChart()
    drawFonctChart()
  }

  // Les couleurs des graphiques sont lues au dessin : un changement de thème
  // les redessine (sauf au premier passage, avant les données).
  let premierTheme = true
  const arreterTheme = themeEffectif.subscribe(() => {
    if (premierTheme) { premierTheme = false; return }
    requestAnimationFrame(dessiner)
  })
  onDestroy(arreterTheme)

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
      .selectAll('text').attr('fill', couleur('--texte-doux')).attr('font-size', 10)

    svg.append('g')
      .call(d3.axisLeft(y).ticks(4).tickFormat(fmt))
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', couleur('--bordure-douce')).attr('x2', w))
      .selectAll('text').attr('fill', couleur('--texte-doux')).attr('font-size', 10)

    // Ligne zéro si données négatives
    if (yMin < 0) {
      svg.append('line')
        .attr('x1', 0).attr('x2', w)
        .attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', couleur('--bordure')).attr('stroke-dasharray', '4,2')
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
        .attr('stroke', couleur(colors[i] || '--serie-bleu'))
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
        .attr('fill', couleur(colors[i] || '--serie-bleu'))
        .append('title')
        .text(d => `${d.year} : ${fmtEur(d.montant)}`)
    })
  }

  function drawDebtChart() {
    drawChart(chartDebtEl,
      [{ data: byAgregat('Encours de dette') }],
      ['--serie-rouge'],
      'Encours dette'
    )
  }

  function drawEpargneChart() {
    drawChart(chartEpargneEl,
      [
        { data: byAgregat('Epargne brute') },
        { data: byAgregat('Epargne nette') },
      ],
      ['--serie-vert', '--serie-cyan'],
      'Épargne'
    )
  }

  function drawFonctChart() {
    drawChart(chartFonctEl,
      [
        { data: byAgregat('Recettes de fonctionnement') },
        { data: byAgregat('Dépenses de fonctionnement') },
      ],
      ['--serie-bleu', '--serie-ambre'],
      'Fonctionnement'
    )
  }
</script>

<svelte:head>
  <title>Finances — {COMMUNE}</title>
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
        { label: 'Recettes fonct.',   agg: 'Recettes de fonctionnement',  color: 'var(--serie-bleu)' },
        { label: 'Dépenses fonct.',   agg: 'Dépenses de fonctionnement',  color: 'var(--serie-ambre)' },
        { label: 'Épargne brute',     agg: 'Epargne brute',               color: 'var(--serie-vert)' },
        { label: 'Encours dette',     agg: 'Encours de dette',             color: 'var(--serie-rouge)' },
        { label: 'Annuité dette',     agg: 'Annuité de la dette',          color: 'var(--serie-orange)' },
        { label: 'Frais de personnel',agg: 'Frais de personnel',           color: 'var(--serie-violet)' },
        { label: 'DGF',               agg: 'Dotation globale de fonctionnement', color: 'var(--serie-cyan)' },
        { label: 'Impôts locaux',     agg: 'Impôts locaux',               color: 'var(--serie-lime)' },
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
          <span class="legend"><span class="dot" style="background:var(--serie-rouge)"></span>Dette</span>
        </div>
        <div bind:this={chartDebtEl} class="chart-area"></div>
      </div>

      <div class="chart-block">
        <div class="chart-title">
          Épargne 2017–{lastYear}
          <span class="legend">
            <span class="dot" style="background:var(--serie-vert)"></span>Brute
            <span class="dot" style="background:var(--serie-cyan)"></span>Nette
          </span>
        </div>
        <div bind:this={chartEpargneEl} class="chart-area"></div>
      </div>

      <div class="chart-block">
        <div class="chart-title">
          Fonctionnement 2017–{lastYear}
          <span class="legend">
            <span class="dot" style="background:var(--serie-bleu)"></span>Recettes
            <span class="dot" style="background:var(--serie-ambre)"></span>Dépenses
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
    background: var(--surface); border-bottom: 1px solid var(--bordure);
    flex-shrink: 0; flex-wrap: wrap;
  }
  h1 { font-size: 1rem; font-weight: 700; }

  .tabs { display: flex; gap: 2px; }
  .tabs button {
    padding: .25rem .75rem; border-radius: 6px;
    font-size: .8rem; background: var(--fond); color: var(--texte-doux);
    border: 1px solid var(--bordure);
  }
  .tabs button.active { background: var(--accent-fort); color: var(--sur-accent); border-color: var(--accent-fort); }
  .tabs button:hover:not(.active) { color: var(--texte); }

  .badge {
    margin-left: auto; font-size: .72rem; color: var(--texte-doux);
    background: var(--fond); padding: 2px 8px; border-radius: 999px;
  }

  /* ── KPIs ── */
  .kpis {
    display: flex; flex-wrap: wrap; gap: .75rem;
    padding: .75rem 1.25rem; flex-shrink: 0;
    background: var(--fond); border-bottom: 1px solid var(--bordure-douce);
  }
  .kpi {
    background: var(--surface); border: 1px solid var(--bordure);
    border-radius: 8px; padding: .5rem .9rem;
    min-width: 110px;
  }
  .kpi-val { font-size: 1.05rem; font-weight: 700; }
  .kpi-sub { font-size: .7rem; color: var(--texte-doux); margin-top: 2px; }
  .kpi-hab { font-size: .68rem; color: var(--texte-doux); }

  /* ── Graphiques ── */
  .charts {
    display: flex; flex-wrap: wrap; gap: .75rem;
    padding: .75rem 1.25rem; flex-shrink: 0;
    background: var(--fond); border-bottom: 1px solid var(--bordure-douce);
  }
  .chart-block {
    background: var(--surface); border: 1px solid var(--bordure);
    border-radius: 8px; padding: .6rem .8rem;
    flex: 1; min-width: 280px;
  }
  .chart-title {
    font-size: .75rem; color: var(--texte-doux); margin-bottom: .4rem;
    display: flex; align-items: center; gap: .5rem;
  }
  .legend { display: flex; align-items: center; gap: .35rem; margin-left: auto; font-size: .7rem; color: var(--texte-doux); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
  .chart-area { width: 100%; }

  /* ── Tableau ── */
  .table-wrap {
    flex: 1; overflow: auto; padding: .75rem 1.25rem;
  }
  table { width: 100%; border-collapse: collapse; font-size: .75rem; }
  th {
    text-align: right; padding: .3rem .6rem;
    color: var(--texte-doux); font-weight: 600; border-bottom: 1px solid var(--bordure);
    white-space: nowrap;
  }
  th:first-child { text-align: left; }
  td { padding: .25rem .6rem; border-bottom: 1px solid var(--bordure-douce); color: var(--texte-2); }
  .agg-name { color: var(--texte-doux); white-space: nowrap; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .num.neg { color: var(--danger); }
  tr:hover td { background: var(--surface); }

  /* ── Flux ── */
  .toolbar-sub {
    display: flex; align-items: center; gap: 1rem;
    padding: .5rem 1.25rem; background: var(--fond);
    border-bottom: 1px solid var(--bordure-douce); flex-shrink: 0;
  }
  select {
    background: var(--surface); border: 1px solid var(--bordure);
    border-radius: 6px; color: var(--texte);
    font-size: .8rem; padding: .3rem .6rem;
  }
  .total { color: var(--succes); font-size: .82rem; font-weight: 600; margin-left: auto; }

  .list {
    flex: 1; overflow-y: auto; padding: 1rem 1.25rem;
    display: flex; flex-direction: column; gap: .5rem;
  }
  .flow-card {
    background: var(--surface); border: 1px solid var(--bordure);
    border-radius: 8px; padding: .6rem 1rem;
  }
  .flow-head { display: flex; gap: .5rem; align-items: center; margin-bottom: .25rem; }
  .year { color: var(--texte-doux); font-size: .78rem; }
  .ftype {
    background: var(--fond); padding: 1px 8px; border-radius: 999px;
    font-size: .7rem; color: var(--alerte);
  }
  .amount { color: var(--succes); font-weight: 700; font-size: .88rem; margin-left: auto; }
  .flow-parties { display: flex; gap: .4rem; align-items: center; font-size: .82rem; }
  .from { color: var(--texte-doux); }
  .arrow { color: var(--texte-doux); }
  .to { color: var(--texte); font-weight: 500; }
  .desc { font-size: .75rem; color: var(--texte-doux); margin-top: .2rem; font-style: italic; }

  .hint { color: var(--texte-doux); padding: 2rem; text-align: center; }
</style>
