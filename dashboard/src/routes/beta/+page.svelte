<script>
  import { SITE_NOM } from '$lib/instance.js'
  import { onMount } from 'svelte'

  let stats = null
  let events = []
  let entities = []
  let relations = []
  let loading = true
  let error = ''

  async function loadJson(path, fallback) {
    const res = await fetch(path)
    if (!res.ok) return fallback
    return res.json()
  }

  onMount(async () => {
    try {
      const [s, ev, en, rel] = await Promise.all([
        loadJson('/public_api/stats.json', null),
        loadJson('/public_api/events.json', { events: [] }),
        loadJson('/public_api/entities.json', { entities: [] }),
        loadJson('/public_api/relations.json', { relations: [] }),
      ])
      stats = s
      events = ev.events || []
      entities = en.entities || []
      relations = rel.relations || []
    } catch (e) {
      error = 'Snapshot public indisponible.'
    } finally {
      loading = false
    }
  })

  $: nextEvents = events
    .filter(e => e.date)
    .slice(0, 8)

  $: typeCounts = entities.reduce((acc, e) => {
    acc[e.type] = (acc[e.type] || 0) + 1
    return acc
  }, {})

  function fmt(n) {
    if (n === null || n === undefined) return '—'
    return Number(n).toLocaleString('fr-FR')
  }

  function fmtDate(d) {
    return d ? d.slice(0, 10) : '—'
  }
</script>

<svelte:head>
  <title>{SITE_NOM} — bêta publique</title>
</svelte:head>

<div class="public-page">
  <section class="hero">
    <div>
      <p class="eyebrow">Bêta confidentielle</p>
      <h1>{SITE_NOM}</h1>
      <p class="lede">Veille locale, décisions publiques, événements et données utiles à la vie citoyenne.</p>
    </div>
    {#if stats?.generated_at}
      <div class="stamp">
        <span>Snapshot</span>
        <strong>{stats.generated_at.slice(0, 10)}</strong>
      </div>
    {/if}
  </section>

  {#if loading}
    <p class="state">Chargement du snapshot public…</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else}
    <section class="metrics">
      <div><strong>{fmt(stats?.entities_public)}</strong><span>entités publiées</span></div>
      <div><strong>{fmt(stats?.events_public)}</strong><span>événements</span></div>
      <div><strong>{fmt(stats?.relations_public)}</strong><span>relations sourcées</span></div>
      <div><strong>{fmt(stats?.map_features_public)}</strong><span>points carte</span></div>
    </section>

    <section class="columns">
      <div class="panel">
        <h2>Aujourd’hui</h2>
        <div class="event-list">
          {#each nextEvents as ev}
            <article>
              <time>{fmtDate(ev.date)}</time>
              <div>
                <strong>{ev.title}</strong>
                <span>{ev.source} · {ev.type}</span>
              </div>
            </article>
          {/each}
        </div>
      </div>

      <div class="panel">
        <h2>Base publique</h2>
        <div class="type-grid">
          <div><strong>{fmt(typeCounts.business)}</strong><span>entreprises</span></div>
          <div><strong>{fmt(typeCounts.association)}</strong><span>associations</span></div>
          <div><strong>{fmt(typeCounts.place)}</strong><span>lieux</span></div>
          <div><strong>{fmt(typeCounts.service)}</strong><span>services</span></div>
          <div><strong>{fmt(typeCounts.person)}</strong><span>personnes civiques</span></div>
          <div><strong>{fmt(relations.length)}</strong><span>liens publics</span></div>
        </div>
      </div>
    </section>

    <section class="guardrails">
      <h2>Garde-fous de publication</h2>
      <ul>
        <li>Données issues du snapshot public uniquement.</li>
        <li>Aucune coordonnée de personne publiée.</li>
        <li>Hypothèses, notes IA non relues et relations présumées exclues.</li>
        <li>URLs publiques limitées aux liens confirmés et non génériques.</li>
      </ul>
    </section>
  {/if}
</div>

<style>
  .public-page {
    flex: 1;
    overflow-y: auto;
    background: #f8fafc;
    color: #0f172a;
    padding: 1.25rem;
  }

  .hero {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: flex-start;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 1rem;
    margin-bottom: 1rem;
  }

  .eyebrow {
    color: #b45309;
    font-size: .72rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: .35rem;
  }

  h1 {
    font-size: 1.55rem;
    margin-bottom: .35rem;
  }

  h2 {
    font-size: .95rem;
    margin-bottom: .7rem;
  }

  .lede {
    color: #475569;
    max-width: 680px;
  }

  .stamp {
    text-align: right;
    color: #64748b;
    font-size: .75rem;
  }

  .stamp strong {
    display: block;
    color: #0f172a;
    font-size: .9rem;
  }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .75rem;
    margin-bottom: .75rem;
  }

  .metrics div,
  .panel,
  .guardrails {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: .9rem;
  }

  .metrics strong {
    display: block;
    font-size: 1.5rem;
  }

  .metrics span,
  .type-grid span,
  article span,
  .state {
    color: #64748b;
    font-size: .8rem;
  }

  .columns {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(320px, .7fr);
    gap: .75rem;
  }

  .event-list {
    display: grid;
    gap: .55rem;
  }

  article {
    display: grid;
    grid-template-columns: 90px 1fr;
    gap: .75rem;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: .55rem;
  }

  article time {
    color: #2563eb;
    font-size: .8rem;
    font-weight: 750;
  }

  article strong,
  article span {
    display: block;
  }

  .type-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: .65rem;
  }

  .type-grid strong {
    display: block;
    font-size: 1.15rem;
  }

  .guardrails {
    margin-top: .75rem;
  }

  ul {
    padding-left: 1.1rem;
    color: #475569;
    font-size: .85rem;
    line-height: 1.6;
  }

  .error {
    background: #fee2e2;
    color: #991b1b;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: .8rem;
  }

  @media (max-width: 900px) {
    .hero,
    .columns {
      display: block;
    }

    .metrics {
      grid-template-columns: 1fr 1fr;
    }

    .panel {
      margin-bottom: .75rem;
    }
  }
</style>
