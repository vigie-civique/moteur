<script>
  import { COMMUNE_DE, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
  import SourceAbsente from '$lib/components/SourceAbsente.svelte'

  // Vie locale — v1 (décision 03/07/2026) : agenda et événements du territoire.
  const AGENDA_TYPES = new Set(['local_event', 'evenement_culturel', 'exposition'])

  // Rendu au build par +page.server.js.
  export let data
  $: all = data.all
  $: source = data.source || { etat: 'servie', sources: [] }
  let q = ''
  const today = new Date().toISOString().slice(0, 10)

  // « À venir » inclut les événements en cours (multi-jours dont la fin est future).
  const endOf = (e) => e.date_end || e.date || ''
  $: filtered = all.filter(e => !q || (e.title || '').toLowerCase().includes(q.toLowerCase()))
  $: aVenir = filtered.filter(e => endOf(e) >= today)
                      .sort((a, b) => (a.date || '').localeCompare(b.date || ''))
  $: passes = filtered.filter(e => endOf(e) < today)

  function fmtDate(d) {
    if (!d) return '—'
    try {
      return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR',
        { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    } catch { return d }
  }
  const fmtShort = (d) => {
    if (!d) return ''
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
  // Libellé de date : plage si multi-jours, sinon date simple ; « en cours » si déjà commencé.
  function dateLabel(e) {
    if (e.date_end && e.date_end !== e.date) {
      const started = (e.date || '') <= today
      return `${started ? 'En cours' : 'Du'} ${started ? 'jusqu’au ' + fmtShort(e.date_end) : fmtShort(e.date) + ' au ' + fmtShort(e.date_end)}`
    }
    return fmtDate(e.date)
  }
</script>

<svelte:head>
  <title>Vie locale — {SITE_NOM}</title>
  <meta name="description" content="Agenda et événements {COMMUNE_DE} : manifestations, culture, vie associative — collectés depuis les sources publiques locales." />
</svelte:head>

<section>
  <h1 class="avec-icone"><Icon name="vie" size={26} />La vie locale</h1>
  {#if source.etat === 'absente'}
    <p class="sub">Événements, manifestations et vie associative locales.</p>
    <SourceAbsente etat={source.etat} sources={source.sources} dernier={source.dernier} travailManuel
                   quoi="L'agenda local" />
  {:else}
    <p class="sub">Événements, manifestations et vie associative locales,
       collectés depuis les sources publiques locales : site de la commune,
       de l'intercommunalité et des associations.</p>
  {/if}

  <div class="filters" class:masque={source.etat === 'absente'}>
    <input placeholder="Rechercher un événement…" bind:value={q} />
    <!-- Le compteur s'affichait à 0 pendant le chargement : le visiteur lisait
         « aucun événement » alors que la page en avait 1 320 à venir. -->
    <span class="count">{filtered.length}</span>
  </div>



  {#if aVenir.length}
    <h2>À venir</h2>
    <ul class="events upcoming">
      {#each aVenir as e}
        <li>
          <span class="date">{dateLabel(e)}</span>
          <span class="title">{e.title}</span>
          {#if e.source_url}<a href={e.source_url} target="_blank" rel="noopener">source ↗</a>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if passes.length}
    <h2>Passés</h2>
    <ul class="events">
      {#each passes.slice(0, 100) as e}
        <li>
          <span class="date">{dateLabel(e)}</span>
          <span class="title">{e.title}</span>
          {#if e.source_url}<a href={e.source_url} target="_blank" rel="noopener">source ↗</a>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if !filtered.length && source.etat === 'servie'}
    <p class="empty">Aucun événement ne correspond.</p>
  {:else if !filtered.length && source.etat === 'vide'}
    <SourceAbsente etat="vide" sources={source.sources} dernier={source.dernier} />
  {/if}
</section>

<style>
  section { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
  /* Un champ de recherche sur un corpus qui n'existe pas n'a rien à filtrer. */
  .filters.masque { display: none; }
  h1 { color: var(--encre); }
  h2 { color: var(--encre); margin-top: 1.6rem; }
  .sub { color: var(--gris); }
  .filters { display: flex; align-items: center; gap: .75rem; margin: 1rem 0; }
  .filters input { flex: 1; padding: .5rem .75rem; border: 1px solid var(--trait); border-radius: 8px; }
  .count { color: var(--gris); font-size: .9rem; }
  .events { list-style: none; padding: 0; margin: 0; }
  .events li { display: flex; gap: .9rem; align-items: baseline; padding: .55rem .25rem;
               border-bottom: 1px solid var(--trait-pale); }
  .events.upcoming li { background: var(--papier); border-radius: 6px; margin-bottom: .25rem; }
  .date { color: var(--ardoise); font-size: .85rem; white-space: nowrap; min-width: 12rem; }
  .title { flex: 1; }
  .events a { font-size: .8rem; color: var(--gris); }
  .empty { color: var(--gris); }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
