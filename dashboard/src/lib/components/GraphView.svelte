<script>
  import { onMount, onDestroy } from 'svelte'
  import * as d3 from 'd3'
  import { api } from '$lib/api.js'
  import { selectedEntity, activeTab, graphDepth, minRelations, TYPE_COLORS } from '$lib/stores/app.js'

  let wrapEl   // div parent — source des dimensions réelles
  let svgEl
  let sim
  let loading = false
  let error = ''
  let nodeCount = 0
  let edgeCount = 0
  let lastNodes = []   // cache pour redessiner au resize
  let lastEdges = []
  let ro               // ResizeObserver du conteneur

  const nodeRadius = d => Math.max(6, Math.min(22, 5 + (d.degree || 1) * 1.8))

  async function loadGraph() {
    if (sim) { sim.stop(); sim = null }
    loading = true
    error = ''
    const eid = $selectedEntity?.id ?? null
    let data
    try {
      data = await api.graph(eid, $graphDepth, $minRelations, eid ? 120 : 180)
    } catch(e) {
      error = 'Impossible de charger le graphe.'
      nodeCount = 0
      edgeCount = 0
      loading = false
      return
    }
    loading = false

    const nodes = data.nodes || []
    // D3 forceLink a besoin de source/target (on mappe depuis from_id/to_id)
    const edges = (data.links || data.edges || []).map(e => ({ ...e, source: e.from_id, target: e.to_id }))
    nodeCount = nodes.length
    edgeCount = edges.length

    if (!nodes.length) { lastNodes = []; lastEdges = []; return }
    lastNodes = nodes
    lastEdges = edges
    drawGraph(nodes, edges)
  }

  function drawGraph(nodes, edges) {
    // Dimensions réelles du conteneur. Si le flex n'est pas encore mis en page
    // (onMount avant calcul du layout), clientWidth/Height = 0 → réessai au frame suivant.
    const W = wrapEl?.clientWidth
    const H = wrapEl?.clientHeight
    if (!W || !H) {
      requestAnimationFrame(() => drawGraph(nodes, edges))
      return
    }

    const svg = d3.select(svgEl)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`)

    const g = svg.append('g')

    svg.call(
      d3.zoom().scaleExtent([.05, 6])
        .on('zoom', e => g.attr('transform', e.transform))
    )

    // Marqueur flèche
    svg.append('defs').append('marker')
      .attr('id', 'arr')
      .attr('viewBox', '0 -4 8 8').attr('refX', 20).attr('refY', 0)
      .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#475569')

    // Arêtes
    const link = g.append('g').attr('class', 'links')
      .selectAll('line').data(edges).join('line')
      .attr('stroke', '#334155').attr('stroke-width', 1.2)
      .attr('marker-end', 'url(#arr)')

    // Étiquettes des relations
    const linkLabel = g.append('g').attr('class', 'link-labels')
      .selectAll('text').data(edges).join('text')
      .attr('font-size', 7).attr('fill', '#475569')
      .attr('text-anchor', 'middle').attr('pointer-events', 'none')
      .text(e => e.relation_type || '')

    const large = nodes.length > 300

    // Nœuds
    const node = g.append('g').attr('class', 'nodes')
      .selectAll('g').data(nodes).join('g')
      .attr('cursor', 'pointer')
      .call(
        d3.drag()
          .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y })
          .on('drag',  (ev, d) => { d.fx = ev.x; d.fy = ev.y })
          .on('end',   (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
      )
      .on('click', (ev, d) => {
        ev.stopPropagation()
        selectedEntity.set(d)
        activeTab.set('entity')
      })

    node.append('circle')
      .attr('r', nodeRadius)
      .attr('fill', d => TYPE_COLORS[d.type] || '#64748b')
      .attr('stroke', d => d.id === $selectedEntity?.id ? '#fff' : '#0f172a')
      .attr('stroke-width', d => d.id === $selectedEntity?.id ? 2.5 : 1.5)

    // Labels : toujours visibles en vue focalisée, seulement pour nœuds importants en vue globale
    node.append('text')
      .attr('dy', d => nodeRadius(d) + 9)
      .attr('text-anchor', 'middle')
      .attr('font-size', 9).attr('fill', '#94a3b8')
      .attr('pointer-events', 'none')
      .attr('display', d => large && (d.degree || 1) < 5 ? 'none' : null)
      .text(d => d.name?.length > 24 ? d.name.slice(0, 22) + '…' : d.name)

    node.append('title')
      .text(d => `${d.name}\n${d.type} — ${d.degree} relation(s)`)

    // Simulation — charge plus forte pour grands graphes
    const chargeStrength = large ? -600 : -250
    const linkDistance   = large ? 40  : 90

    sim = d3.forceSimulation(nodes)
      .alphaDecay(large ? 0.01 : 0.028)
      .force('link',    d3.forceLink(edges).id(d => d.id).distance(linkDistance))
      .force('charge',  d3.forceManyBody().strength(chargeStrength).distanceMax(300))
      .force('center',  d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(d => nodeRadius(d) + (large ? 2 : 5)))
      .on('tick', () => {
        link
          .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        linkLabel
          .attr('x', d => (d.source.x + d.target.x) / 2)
          .attr('y', d => (d.source.y + d.target.y) / 2)
        node.attr('transform', d => `translate(${d.x},${d.y})`)
      })
  }

  let subs = []
  let prevEntityId = null

  onMount(() => {
    loadGraph()

    // Recharger si l'entité sélectionnée change (depuis la carte)
    subs.push(selectedEntity.subscribe(e => {
      const id = e?.id ?? null
      if (id !== prevEntityId) {
        prevEntityId = id
        loadGraph()
      }
    }))

    // Redessiner quand le conteneur change de taille (resize fenêtre / settle flex)
    let rt
    ro = new ResizeObserver(() => {
      clearTimeout(rt)
      rt = setTimeout(() => { if (lastNodes.length) drawGraph(lastNodes, lastEdges) }, 150)
    })
    if (wrapEl) ro.observe(wrapEl)
  })

  onDestroy(() => {
    if (sim) sim.stop()
    if (ro) ro.disconnect()
    subs.forEach(u => u())
  })
</script>

<div class="graph-wrap" bind:this={wrapEl}>
  <div class="toolbar">
    <label>Profondeur
      <select bind:value={$graphDepth} on:change={loadGraph}>
        <option value={1}>1</option>
        <option value={2}>2</option>
        <option value={3}>3</option>
      </select>
    </label>
    <label>Min relations
      <select bind:value={$minRelations} on:change={loadGraph}>
        {#each [1,2,3,5,10] as v}<option value={v}>{v}</option>{/each}
      </select>
    </label>

    <button on:click={loadGraph}>↺ Recharger</button>

    {#if $selectedEntity}
      <span class="entity-badge">{$selectedEntity.name}</span>
      <button on:click={() => { selectedEntity.set(null) }}>✕ Vue globale</button>
    {/if}

    {#if loading}
      <span class="spin">Chargement…</span>
    {:else if nodeCount}
      <span class="count">{nodeCount} nœuds · {edgeCount} liens</span>
    {/if}
  </div>

  <svg bind:this={svgEl} class="graph-svg"></svg>

  {#if error}
    <div class="empty">{error}</div>
  {:else if !loading && nodeCount === 0}
    <div class="empty">Aucun nœud — augmentez la profondeur ou réduisez le filtre min-relations.</div>
  {/if}
</div>

<style>
  .graph-wrap {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background: #0f172a;
    position: relative;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: .6rem;
    padding: .4rem .75rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    font-size: .78rem;
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .toolbar label { display: flex; align-items: center; gap: .35rem; color: #94a3b8; }
  .toolbar select {
    background: #0f172a; border: 1px solid #334155;
    border-radius: 4px; color: #e2e8f0;
    padding: 1px 6px; font-size: .78rem;
  }
  .toolbar button {
    padding: .2rem .6rem; background: #334155;
    border-radius: 4px; font-size: .78rem;
  }
  .toolbar button:hover { background: #475569; }

  .entity-badge {
    background: #1d4ed8; color: #bfdbfe;
    padding: 1px 8px; border-radius: 999px;
    font-size: .72rem; max-width: 200px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .count { color: #475569; font-size: .72rem; margin-left: auto; }
  .spin  { color: #60a5fa; font-size: .78rem; }

  .graph-svg { flex: 1; min-height: 0; }

  .empty {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    color: #334155; font-size: .85rem;
    text-align: center;
  }
</style>
