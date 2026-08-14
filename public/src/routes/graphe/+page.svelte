<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
  // Graphe public « qui est lié à qui » — relations déjà filtrées à l'export
  // (build_public_snapshot.py : confidence publique, allowlist, pas de marqueurs privés).
  // Modèle LittleSis / SF Government Graph.
  import { onMount, onDestroy } from 'svelte'
  import * as d3 from 'd3'
  import { TYPE_LABELS } from '$lib/data.js'

  const TYPE_COLORS = {
    person: '#ef4444', business: '#f59e0b', association: '#10b981',
    service: '#3b82f6', place: '#8b5cf6', property: '#64748b',
  }
  // Regroupements lisibles pour le citoyen.
  const GROUPS = {
    all:        null,
    mandats:    ['élu_cm', 'élu_cc', 'adjoint', 'candidat'],
    subventions:['subventionné'],
    commissions:['membre_commission'],
  }
  const FILTERS = [
    { key: 'all',         label: 'Tout' },
    { key: 'mandats',     label: 'Mandats & candidatures' },
    { key: 'subventions', label: 'Subventions' },
    { key: 'commissions', label: 'Commissions' },
  ]

  // Données rendues au build par +page.server.js ; seul le rendu D3 (calcul de
  // forces, mise en page) reste côté client — c'est de l'interactif, pas de la
  // donnée.
  export let data
  $: allRels = data.relations
  $: entType = new Map(data.entType)

  let wrapEl, svgEl, sim, ro
  let filter = 'all'
  let nodeCount = 0, edgeCount = 0
  let error = ''
  let lastNodes = [], lastEdges = []

  const nodeRadius = d => Math.max(6, Math.min(26, 5 + (d.degree || 1) * 1.6))

  function inferType(id, name) {
    if (entType.has(id)) return entType.get(id)
    if (/commune|communaut|mairie|conseil/i.test(name || '')) return 'service'
    return 'person'
  }

  // BUG-4 : un mandat clos (until passé) ne doit pas apparaître comme lien actuel.
  const TODAY = new Date().toISOString().slice(0, 10)
  const isActive = r => !r.until || r.until > TODAY

  function build() {
    const allow = GROUPS[filter]
    let rels = allRels.filter(isActive)
    if (allow) rels = rels.filter(r => allow.includes(r.relation_type))
    const map = new Map()
    const edges = []
    const add = (id, name) => {
      if (!map.has(id)) map.set(id, { id, name: name || `#${id}`, type: inferType(id, name), degree: 0 })
    }
    for (const r of rels) {
      add(r.from_id, r.from_name); add(r.to_id, r.to_name)
      map.get(r.from_id).degree++; map.get(r.to_id).degree++
      edges.push({ source: r.from_id, target: r.to_id, relation_type: r.relation_type })
    }
    const nodes = [...map.values()]
    nodeCount = nodes.length; edgeCount = edges.length
    lastNodes = nodes; lastEdges = edges
    draw(nodes, edges)
  }

  function draw(nodes, edges) {
    if (sim) { sim.stop(); sim = null }
    const W = wrapEl?.clientWidth, H = wrapEl?.clientHeight
    if (!W || !H) { requestAnimationFrame(() => draw(nodes, edges)); return }  // fix BUG-2

    const svg = d3.select(svgEl)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`)
    const g = svg.append('g')
    svg.call(d3.zoom().scaleExtent([.1, 6]).on('zoom', e => g.attr('transform', e.transform)))

    const link = g.append('g').selectAll('line').data(edges).join('line')
      .attr('stroke', '#cbd5e1').attr('stroke-width', 1.1)

    const node = g.append('g').selectAll('g').data(nodes).join('g')
      .attr('cursor', 'grab')
      .call(d3.drag()
        .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag',  (ev, d) => { d.fx = ev.x; d.fy = ev.y })
        .on('end',   (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

    node.append('circle')
      .attr('r', nodeRadius)
      .attr('fill', d => TYPE_COLORS[d.type] || '#64748b')
      .attr('stroke', '#fff').attr('stroke-width', 1.5)

    // Tous les nœuds sont nommés. La version précédente masquait le libellé des
    // nœuds de degré < 3 dès que le graphe dépassait 60 nœuds : sur le graphe
    // réel (200 nœuds, dont 129 de degré 1 ou 2), c'était 64 % de points
    // anonymes — un nuage illisible où l'information était justement le nom.
    // Le désencombrement passe désormais par la taille et l'opacité, pas par la
    // disparition : les nœuds périphériques restent lisibles au zoom, et le
    // survol remet leur libellé au premier plan.
    node.append('text')
      .attr('dy', d => nodeRadius(d) + 10)
      .attr('text-anchor', 'middle')
      .attr('font-size', d => (d.degree || 1) >= 3 ? 9.5 : 8)
      .attr('fill', '#475569')
      .attr('fill-opacity', d => (d.degree || 1) >= 3 ? 1 : .62)
      .attr('paint-order', 'stroke')          // halo blanc : lisible sur les liens
      .attr('stroke', '#fff').attr('stroke-width', 2.6).attr('stroke-linejoin', 'round')
      .attr('pointer-events', 'none')
      .text(d => d.name.length > 22 ? d.name.slice(0, 20) + '…' : d.name)

    node
      .on('mouseenter', function (_, d) {
        d3.select(this).raise().select('text')
          .attr('fill-opacity', 1).attr('font-size', 11).attr('font-weight', 600)
          .text(d.name)                        // nom entier, sans troncature
      })
      .on('mouseleave', function (_, d) {
        d3.select(this).select('text')
          .attr('fill-opacity', (d.degree || 1) >= 3 ? 1 : .62)
          .attr('font-size', (d.degree || 1) >= 3 ? 9.5 : 8)
          .attr('font-weight', null)
          .text(d.name.length > 22 ? d.name.slice(0, 20) + '…' : d.name)
      })

    node.append('title').text(d => `${d.name}\n${TYPE_LABELS[d.type] || d.type} — ${d.degree} relation(s)`)

    sim = d3.forceSimulation(nodes)
      .alphaDecay(0.025)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(70))
      .force('charge', d3.forceManyBody().strength(-260).distanceMax(320))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(d => nodeRadius(d) + 13))   // place pour le libellé
      .on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        node.attr('transform', d => `translate(${d.x},${d.y})`)
      })
  }

  function setFilter(k) { filter = k; build() }

  onMount(() => {
    build()
    let rt
    ro = new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => lastNodes.length && draw(lastNodes, lastEdges), 150) })
    if (wrapEl) ro.observe(wrapEl)
  })

  onDestroy(() => { if (sim) sim.stop(); if (ro) ro.disconnect() })

  const LEGEND = ['person', 'association', 'business', 'service', 'place']
</script>

<svelte:head>
  <title>Graphe des relations — {SITE_NOM}</title>
  <meta name="description" content="Qui est lié à qui {COMMUNE_A} : élus, associations, entreprises, subventions et commissions — relations vérifiées." />
</svelte:head>

<div class="head">
  <div>
    <h1 class="avec-icone"><Icon name="graphe" size={26} />Qui est lié à qui&nbsp;?</h1>
    <p>Le réseau des acteurs locaux à partir des <strong>relations vérifiées</strong> :
       mandats, subventions, commissions. Glissez les nœuds, zoomez à la molette.</p>
  </div>
</div>

<div class="controls">
  <div class="filters">
    {#each FILTERS as f}
      <button class:on={filter === f.key} on:click={() => setFilter(f.key)}>{f.label}</button>
    {/each}
  </div>
  <div class="legend">
    {#each LEGEND as t}
      <span class="lg"><i style="background:{TYPE_COLORS[t]}"></i>{TYPE_LABELS[t]}</span>
    {/each}
    {#if nodeCount}<span class="count">{nodeCount} acteurs · {edgeCount} liens</span>{/if}
  </div>
</div>

<div class="graph-wrap" bind:this={wrapEl}>
  <svg bind:this={svgEl} class="graph-svg"></svg>
  {#if error}<div class="empty">{error}</div>{/if}
</div>

<style>
  .head { max-width: 1100px; margin: 0 auto; padding: 1.5rem 1.5rem .5rem; }
  .head h1 { font-size: 1.6rem; margin: 0 0 .3rem; color: var(--encre); }
  .head p { color: var(--gris); margin: 0; max-width: 70ch; font-size: .92rem; }

  .controls { max-width: 1100px; margin: 0 auto; padding: .5rem 1.5rem; display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: center; }
  .filters { display: flex; gap: .35rem; flex-wrap: wrap; }
  .filters button { padding: .3rem .8rem; border-radius: 999px; background: var(--trait-pale); color: var(--gris); font-size: .82rem; border: 1px solid var(--trait); }
  .filters button.on { background: var(--ardoise); color: #fff; border-color: var(--ardoise); }
  .legend { display: flex; gap: .8rem; align-items: center; flex-wrap: wrap; font-size: .78rem; color: var(--gris); }
  .lg { display: flex; align-items: center; gap: .3rem; }
  .lg i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
  .count { color: var(--gris-clair); }

  .graph-wrap { max-width: 1100px; margin: .5rem auto 2rem; height: calc(100vh - 280px); min-height: 460px;
    background: var(--papier); border: 1px solid var(--trait); border-radius: 12px; position: relative; overflow: hidden; }
  .graph-svg { width: 100%; height: 100%; display: block; }
  .empty { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: var(--gris-clair); font-size: .9rem; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
