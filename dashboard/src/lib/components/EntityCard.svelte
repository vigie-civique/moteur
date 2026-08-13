<script>
  import { api } from '$lib/api.js'
  import { entityDetail, selectedEntity, activeTab, TYPE_COLORS, TYPE_LABELS } from '$lib/stores/app.js'
  import { onMount } from 'svelte'

  export let entity = null

  let detail    = null
  let loading   = false
  let error     = null
  let synthesis = null

  $: if (entity?.id) { loadDetail(entity.id); loadSynthesis(entity.id) }

  async function loadSynthesis(id) {
    synthesis = null
    const s = await api.entitySynthesis(id)
    if (s?.resume) synthesis = s
  }

  async function loadDetail(id) {
    loading = true; detail = null; error = null
    try {
      detail = await api.entity(id)
      entityDetail.set(detail)
    } catch(e) { error = e.message }
    loading = false
  }

  function formatPrice(n) {
    if (!n) return 'N/A'
    return Number(n).toLocaleString('fr-FR') + ' €'
  }

  function focusGraph(id) {
    api.entity(id).then(e => { selectedEntity.set(e); activeTab.set('entity') })
  }

  function parseTags(raw) {
    if (!raw) return {}
    try { return typeof raw === 'string' ? JSON.parse(raw) : raw } catch { return {} }
  }
</script>

{#if !entity}
  <p class="empty">Cliquez sur une entité pour voir le détail.</p>
{:else}
  <div class="card">
    <!-- En-tête -->
    <div class="card-header" style="border-left: 3px solid {TYPE_COLORS[entity.type] ?? '#64748b'}">
      <span class="type-badge">{TYPE_LABELS[entity.type] ?? entity.type}</span>
      <h2>{entity.name}</h2>
      {#if entity.address}<p class="addr">{entity.address}</p>{/if}
    </div>

    {#if loading}
      <p class="loading">Chargement…</p>
    {:else if error}
      <p class="err">{error}</p>
    {:else if detail}
      <!-- Données métier -->
      <section>
        {#if detail.siren}
          <div class="row"><span>SIREN</span><span>{detail.siren}</span></div>
        {/if}
        {#if detail.naf_code}
          <div class="row"><span>NAF</span><span>{detail.naf_code} — {detail.naf_label || ''}</span></div>
        {/if}
        {#if detail.biz_status}
          <div class="row">
            <span>Statut</span>
            <span class:active={detail.biz_status === 'A'} class:closed={detail.biz_status !== 'A'}>
              {detail.biz_status === 'A' ? 'Active' : 'Fermée'}
            </span>
          </div>
        {/if}
        {#if detail.legal_form_code}
          <div class="row"><span>Forme juridique</span><span>{detail.legal_form_code}</span></div>
        {/if}
        {#if detail.creation_date}
          <div class="row"><span>Création</span><span>{detail.creation_date}</span></div>
        {/if}
        {#if detail.employees_range}
          <div class="row"><span>Effectif</span><span>{detail.employees_range}</span></div>
        {/if}
        {#if detail.rna_id}
          <div class="row"><span>RNA</span><span>{detail.rna_id}</span></div>
        {/if}
        {#if detail.firstname || detail.lastname}
          <div class="row"><span>Personne</span><span>{detail.firstname} {detail.lastname}</span></div>
        {/if}
        {#if detail.birth_year}
          <div class="row"><span>Naissance</span><span>{detail.birth_year}</span></div>
        {/if}
        {#if detail.osm_category}
          <div class="row"><span>OSM</span><span>{detail.osm_category} / {detail.osm_value}</span></div>
        {/if}
      </section>

      <!-- Contact (tags OSM) -->
      {#if detail.tags}
        {@const tags = parseTags(detail.tags)}
        {#if tags.phone || tags.website || tags.email || tags['contact:phone'] || tags['contact:website'] || tags['contact:email']}
          <section>
            <h3>Contact</h3>
            {#if tags.phone || tags['contact:phone']}
              {@const tel = tags.phone || tags['contact:phone']}
              <div class="row"><span>Tél.</span><a href="tel:{tel}" class="contact-link">{tel}</a></div>
            {/if}
            {#if tags.website || tags['contact:website']}
              {@const url = tags.website || tags['contact:website']}
              <div class="row"><span>Site</span><a href={url} target="_blank" rel="noopener" class="contact-link">{url.replace(/^https?:\/\//, '')}</a></div>
            {/if}
            {#if tags.email || tags['contact:email']}
              {@const mail = tags.email || tags['contact:email']}
              <div class="row"><span>Email</span><a href="mailto:{mail}" class="contact-link">{mail}</a></div>
            {/if}
          </section>
        {/if}
      {/if}

      <!-- Synthèse IA -->
      {#if synthesis}
        <section class="synthesis">
          <h3>
            Synthèse IA
            <span class="niveau niveau-{synthesis.niveau_interet}">{synthesis.niveau_interet}</span>
          </h3>
          <p class="resume">{synthesis.resume}</p>
          {#if synthesis.points_attention?.length}
            <ul class="points">
              {#each synthesis.points_attention as pt}
                <li>{pt}</li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      <!-- Relations sortantes -->
      {#if detail.relations_out?.length}
        <section>
          <h3>Relations →</h3>
          <ul class="rel-list">
            {#each detail.relations_out as r}
              <li on:click={() => focusGraph(r.target_id)}>
                <span class="rel-type">{r.relation_type}</span>
                <span class="rel-name">{r.target_name}</span>
                <span class="rel-kind">{r.target_type}</span>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <!-- Relations entrantes -->
      {#if detail.relations_in?.length}
        <section>
          <h3>← Relations entrantes</h3>
          <ul class="rel-list">
            {#each detail.relations_in as r}
              <li on:click={() => focusGraph(r.source_id)}>
                <span class="rel-type">{r.relation_type}</span>
                <span class="rel-name">{r.source_name}</span>
                <span class="rel-kind">{r.source_type}</span>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <!-- Flux financiers -->
      {#if detail.flows?.length}
        <section>
          <h3>Flux financiers</h3>
          <ul class="flow-list">
            {#each detail.flows as f}
              <li>
                <span class="flow-year">{f.year}</span>
                <span class="flow-type">{f.type}</span>
                <span class="flow-amount">{formatPrice(f.amount)}</span>
                {#if f.description}<span class="flow-desc">{f.description}</span>{/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <!-- Événements -->
      {#if detail.events?.length}
        <section>
          <h3>Événements</h3>
          <ul class="ev-list">
            {#each detail.events as ev}
              <li>
                <span class="ev-date">{ev.date?.slice(0,10)}</span>
                <span class="ev-role">{ev.role}</span>
                {#if ev.source_url}
                  <a href={ev.source_url} target="_blank">{ev.title}</a>
                {:else}
                  <span>{ev.title}</span>
                {/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .empty { color: #475569; font-size: .85rem; padding: 1rem; }
  .loading { color: #60a5fa; font-size: .82rem; padding: .5rem 0; }
  .err { color: #ef4444; font-size: .82rem; }

  .card { overflow-y: auto; height: 100%; }
  .card-header {
    padding: .75rem 1rem;
    background: #1e293b;
    margin-bottom: .5rem;
  }
  .type-badge {
    font-size: .68rem;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: #64748b;
    display: block;
    margin-bottom: .25rem;
  }
  h2 { font-size: .95rem; font-weight: 600; }
  .addr { font-size: .78rem; color: #64748b; margin-top: .25rem; }

  section { padding: .5rem 1rem; border-bottom: 1px solid #1e293b; }
  h3 { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: #475569; margin-bottom: .35rem; }

  .row {
    display: flex;
    justify-content: space-between;
    gap: .5rem;
    font-size: .78rem;
    padding: .15rem 0;
  }
  .row span:first-child { color: #64748b; flex-shrink: 0; }
  .row span:last-child  { text-align: right; }
  .active { color: #10b981; font-weight: 600; }
  .closed { color: #ef4444; }

  .rel-list, .flow-list, .ev-list { list-style: none; }
  .rel-list li, .ev-list li {
    display: flex;
    gap: .5rem;
    align-items: baseline;
    font-size: .78rem;
    padding: .2rem 0;
    cursor: pointer;
  }
  .rel-list li:hover { color: #60a5fa; }
  .rel-type { color: #f59e0b; flex-shrink: 0; }
  .rel-name { flex: 1; }
  .rel-kind { color: #475569; font-size: .7rem; }

  .flow-list li {
    display: flex;
    gap: .4rem;
    font-size: .78rem;
    padding: .2rem 0;
    flex-wrap: wrap;
  }
  .flow-year  { color: #64748b; }
  .flow-type  { color: #f59e0b; }
  .flow-amount{ color: #10b981; font-weight: 600; }
  .flow-desc  { color: #64748b; font-style: italic; }

  .ev-date { color: #64748b; flex-shrink: 0; }
  .ev-role { color: #f59e0b; flex-shrink: 0; }

  .synthesis { background: #0f172a; border-left: 2px solid #f59e0b; }
  .synthesis h3 { display: flex; align-items: center; gap: .5rem; }
  .resume { font-size: .8rem; line-height: 1.5; color: #cbd5e1; margin-bottom: .4rem; }
  .points { list-style: none; }
  .points li {
    font-size: .77rem;
    color: #94a3b8;
    padding: .15rem 0 .15rem .75rem;
    border-left: 1px solid #334155;
    margin-bottom: .2rem;
  }
  .niveau {
    font-size: .65rem;
    padding: .1rem .35rem;
    border-radius: 3px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .niveau-faible   { background: #1e3a2f; color: #34d399; }
  .niveau-moyen    { background: #1e2e4a; color: #60a5fa; }
  .niveau-élevé    { background: #3d2e0a; color: #fbbf24; }
  .niveau-critique { background: #3d0a0a; color: #f87171; }

  .contact-link { color: #60a5fa; text-decoration: none; font-size: .78rem; word-break: break-all; }
  .contact-link:hover { text-decoration: underline; }
</style>
