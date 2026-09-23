<script>
  import { COMMUNE, COMMUNE_A, EPCI, EPCI_NB_AUTRES } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'
  import { VERDICTS, VERDICT, FIABILITE, FIABILITE_AIDE } from '$lib/axes.js'

  let data       = null
  let stats      = {}
  let loading    = true
  let error      = ''
  let avis       = ''      // ce qu'une action n'a pas pu faire, sans masquer la liste
  $: tranche = auMoins($currentUser, 'validator')
  let filter     = 'jamais_relu'
  let typeFilter = ''
  // Par défaut, l'atelier travaille sur la commune. Depuis l'élargissement de
  // la collecte aux 15 communes de l'intercommunalité, la file contient plus
  // de fiches C2 que C1 : sans ce défaut, on valide des commerces de Trèves en
  // croyant traiter Lasalle.
  let perimFilter = 'C1'
  let offset     = 0
  const LIMIT    = 50

  const TYPES    = ['person', 'business', 'association', 'place', 'service']

  const PERIMETRES = [
    { key: 'C1',   label: 'La commune',    tip: `${COMMUNE} — le cœur du projet` },
    { key: 'C2',   label: 'Interco',       tip: `${EPCI} et ses ${EPCI_NB_AUTRES} autres communes membres. Collectées pour la comparaison, publiées seulement en agrégat.` },
    { key: 'C3',   label: 'Supra',         tip: 'Préfecture, département, région, agences d\'État' },
    { key: 'lien', label: 'Rattaché',      tip: "Hors du territoire mais lié à un acteur suivi — SCI d'élu, titulaire de marché" },
    { key: '',     label: 'Tout',          tip: 'Tous périmètres confondus' },
  ]

  const PERIM_COLORS = {
    C1: '#14556b', C2: '#9a6b12', C3: '#5b5b66', lien: '#7c3f58',
  }

  const TYPE_COLORS = {
    person: '#7f1d1d', business: '#1d4ed8', association: '#065f46',
    place: '#4c1d95', service: '#92400e',
  }

  onMount(() => { loadStats(); loadQueue() })

  async function loadStats() {
    try {
      const res = await authFetch('/atelier/stats')
      if (res.ok) stats = await res.json()
    } catch {}
  }

  async function loadQueue() {
    loading = true; error = ''
    try {
      const qs = new URLSearchParams({ status: filter, limit: LIMIT, offset })
      if (typeFilter) qs.set('type', typeFilter)
      if (perimFilter) qs.set('perimetre', perimFilter)
      const res = await authFetch(`/atelier/workqueue?${qs}`)
      if (!res.ok) throw new Error(`${res.status}`)
      data = await res.json()
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  }

  // Poser un verdict. Depuis le 21/09/2026 il est lu par la publication :
  // « Écarter » retire vraiment la fiche du site — ce que l'ancien ✗ ne faisait
  // pas. `statut_lu` : le verdict affiché dans la liste. La liste reste ouverte
  // des heures ; si quelqu'un a tranché la fiche entre-temps, l'API refuse (409)
  // au lieu d'écraser sa décision — et dit qui l'a prise.
  async function setStatus(item, verdict) {
    avis = ''
    const res = await authFetch(`/atelier/entities/${item.id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ verdict, statut_lu: item.verdict || 'jamais_relu' }),
    })
    if (res.ok) {
      data.items = data.items.filter(e => e.id !== item.id)
      data.total = Math.max(0, data.total - 1)
      // La ligne quitte cette file : dire où elle est allée, et comment revenir.
      avis = `« ${item.name} » → ${VERDICT[verdict].libelle}. ${VERDICT[verdict].effet}`
        + (verdict !== 'jamais_relu' ? ' Pour revenir en arrière : onglet « '
           + VERDICT[verdict].libelle + ' », « Remettre à relire ».' : '')
      await loadStats()
    } else if (res.status === 409) {
      const d = (await res.json()).detail || {}
      avis = `« ${item.name} » : ${d.message || 'le statut a changé entre-temps.'}`
        + (d.par ? ` Par ${d.par}` : '') + (d.le ? `, le ${heureLocale(d.le)}` : '')
        + '. Rien n\'a été écrasé ; la liste a été rechargée.'
      await Promise.all([loadQueue(), loadStats()])
    } else {
      // Un échec passait sans un mot : la ligne restait, et rien ne disait pourquoi.
      avis = `« ${item.name} » : l'enregistrement a échoué (${res.status}).`
    }
  }

  function changeFilter(s) { filter = s; offset = 0; loadQueue() }
  function changeType(t)   { typeFilter = t; offset = 0; loadQueue() }
  function changePerim(p)  { perimFilter = p; offset = 0; loadQueue() }

  function activite(item) {
    if (item.type === 'business')    return item.naf_label || item.siren || ''
    if (item.type === 'association') return item.asso_object || item.rna_id || ''
    if (item.type === 'service')     return item.svc_category || ''
    if (item.type === 'place')       return item.osm_value || ''
    return ''
  }
</script>

<svelte:head><title>Toutes les fiches — Atelier {COMMUNE}</title></svelte:head>

<div class="page">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>Toutes les fiches</h1>
      <a class="retour" href="/atelier">← Aujourd'hui</a>
      {#if stats.total !== undefined}
        <span class="total">
          {stats.perimetre?.C1?.toLocaleString('fr-FR') ?? '—'} {COMMUNE_A}
          <span class="total-sub">sur {stats.total?.toLocaleString('fr-FR')} en base</span>
        </span>
      {/if}
      <a class="tool-link" href="/atelier/geo">Points sur la carte</a>
    </div>
    <div class="stat-chips">
      {#each VERDICTS as v}
        <button class="chip" class:active={filter === v.cle} title={v.effet}
                on:click={() => changeFilter(v.cle)}>
          {v.libelle}
          <span class="chip-count">{stats[v.cle] ?? 0}</span>
        </button>
      {/each}
    </div>
  </div>

  <!-- Filtre périmètre : quel territoire on traite -->
  <div class="perim-bar">
    <span class="perim-label">Périmètre</span>
    {#each PERIMETRES as p}
      <button class="perim-btn" class:active={perimFilter === p.key}
              style="--pc:{PERIM_COLORS[p.key] ?? '#334155'}"
              title={p.tip} on:click={() => changePerim(p.key)}>
        {p.label}
        {#if p.key && stats.perimetre?.[p.key] !== undefined}
          <span class="perim-count">{stats.perimetre[p.key]}</span>
        {/if}
      </button>
    {/each}
  </div>

  <!-- Filtre type -->
  <div class="type-bar">
    <button class="type-btn" class:active={typeFilter === ''} on:click={() => changeType('')}>Tous</button>
    {#each TYPES as t}
      <button class="type-btn" class:active={typeFilter === t}
              style="--tc:{TYPE_COLORS[t]}" on:click={() => changeType(t)}>{t}</button>
    {/each}
  </div>

  {#if avis}<div class="avis" role="status">{avis}</div>{/if}
  {#if $currentUser && !tranche}<div class="msg">Vous pouvez corriger les fiches (✏️). Vous proposez ; un validateur tranche.</div>{/if}

  <!-- Table -->
  {#if loading}
    <div class="msg">Chargement…</div>
  {:else if error}
    <div class="msg error">Erreur : {error}</div>
  {:else if data}
    <div class="table-wrap">
      <div class="table-meta">{data.total} résultat{data.total !== 1 ? 's' : ''}</div>

      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th title="C1 la commune · C2 l'intercommunalité · C3 autorité supra-communale · lien rattaché à un acteur suivi">Périm.</th>
            <th>Nom</th>
            <th>Adresse</th>
            <th>Activité / Objet</th>
            <th>Responsable</th>
            <th title="Website, téléphone, email">Contact</th>
            <th title="Ce que la machine sait de la fiche — pas un jugement humain">Fiabilité</th>
            <th title="Nombre de relations dans le graphe">Rel.</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each data.items as item (item.id)}
            <tr>
              <td>
                <span class="type-badge" style="background:{TYPE_COLORS[item.type] ?? '#334155'}">
                  {item.type}
                </span>
              </td>
              <td>
                {#if item.perimetre}
                  <span class="perim-badge" style="--pc:{PERIM_COLORS[item.perimetre] ?? '#334155'}"
                        title={item.commune ?? 'commune inconnue'}>{item.perimetre}</span>
                {:else}
                  <span class="perim-badge unset" title="non classé — relancer python3 -m collectors.run_all --step perimetre">?</span>
                {/if}
              </td>
              <td class="name-cell">
                <a href="/atelier/entite/{item.id}" class="entity-link">{item.name}</a>
                {#if item.perimetre !== 'C1' && item.commune}
                  <span class="commune-hint">{item.commune}</span>
                {/if}
              </td>
              <td class="addr-cell">{item.address ?? '—'}</td>
              <td class="detail-cell">{activite(item) || '—'}</td>
              <td class="resp-cell">{item.responsible ?? '—'}</td>
              <td class="contact-cell">
                {#if item.website}
                  <a href={item.website} target="_blank" rel="noopener" title={item.website}>🌐</a>
                {/if}
                {#if item.contacts_count > 0 && !item.website}
                  <span title="{item.contacts_count} contact(s)">📋</span>
                {/if}
                {#if !item.website && !item.contacts_count}
                  <span class="empty-contact">—</span>
                {/if}
              </td>
              <td class="conf-cell">
                <span class="conf conf-{item.confidence}" title={FIABILITE_AIDE[item.confidence] ?? ''}>
                  {FIABILITE[item.confidence] ?? item.confidence ?? '—'}
                </span>
              </td>
              <td class="center">{item.rel_count ?? 0}</td>
              <td class="actions-cell">
                <a href="/atelier/entite/{item.id}" class="act act-edit" title="Éditer">✏️</a>
                {#if tranche}
                  {#each VERDICTS.filter(v => v.cle !== filter) as v}
                    <button class="act act-mot act-{v.cle}" title={v.effet}
                            on:click={() => setStatus(item, v.cle)}>{v.geste}</button>
                  {/each}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      {#if data.items.length === 0}
        <div class="msg">Aucune entité dans cette file.</div>
      {/if}

      {#if data.total > offset + LIMIT}
        <button class="load-more" on:click={() => { offset += LIMIT; loadQueue() }}>
          Charger plus ({data.total - offset - LIMIT} restantes)
        </button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page {
    padding: .9rem 1.1rem;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: .6rem;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .header-left { display: flex; align-items: baseline; gap: .65rem; }
  h1 { font-size: 1rem; font-weight: 700; color: #e2e8f0; }
  .total { font-size: .75rem; color: #64748b; }
  .retour { font-size: .78rem; color: #93c5fd; text-decoration: none; }

  .stat-chips { display: flex; gap: .3rem; flex-wrap: wrap; }
  .chip {
    display: flex; align-items: center; gap: .3rem;
    padding: .25rem .6rem; border-radius: 999px;
    border: 1px solid #334155; background: #1e293b;
    color: #94a3b8; font-size: .73rem; cursor: pointer; transition: all .12s;
  }
  .chip.active { background: #3b82f6; border-color: #3b82f6; color: #fff; }
  .chip:hover:not(.active) { border-color: #475569; color: #e2e8f0; }
  .chip-count {
    background: rgba(255,255,255,.15); border-radius: 999px;
    padding: 0 5px; font-size: .68rem; font-weight: 700;
  }

  .type-bar { display: flex; gap: .25rem; flex-wrap: wrap; }
  .type-btn {
    padding: .2rem .5rem; border-radius: 4px;
    border: 1px solid #334155; background: transparent;
    color: #94a3b8; font-size: .72rem; cursor: pointer; transition: all .12s;
  }
  .type-btn.active { background: var(--tc, #3b82f6); border-color: var(--tc, #3b82f6); color: #fff; }
  .type-btn:hover:not(.active) { border-color: #475569; color: #e2e8f0; }

  .table-wrap { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: .4rem; }
  .table-meta { font-size: .73rem; color: #64748b; padding: .15rem 0; }

  table { width: 100%; border-collapse: collapse; font-size: .78rem; }

  th {
    text-align: left; padding: .38rem .5rem;
    color: #64748b; font-size: .69rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: .04em;
    border-bottom: 1px solid #334155; white-space: nowrap;
    cursor: default;
  }

  td { padding: .4rem .5rem; border-bottom: 1px solid #1e293b; vertical-align: middle; color: #cbd5e1; }
  tr:hover td { background: #1e293b; }

  .perim-bar {
    display: flex; align-items: center; gap: .4rem;
    margin-bottom: .6rem; flex-wrap: wrap;
  }
  .perim-label {
    font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
    opacity: .6; margin-right: .3rem;
  }
  .perim-btn {
    border: 1px solid var(--pc); background: transparent; color: var(--pc);
    border-radius: 999px; padding: .18rem .6rem; font-size: .78rem;
    cursor: pointer; display: inline-flex; align-items: center; gap: .35rem;
  }
  .perim-btn.active { background: var(--pc); color: #fff; }
  .perim-count { font-variant-numeric: tabular-nums; opacity: .8; font-size: .72rem; }
  .perim-badge {
    display: inline-block; min-width: 2.1rem; text-align: center;
    background: var(--pc); color: #fff; border-radius: 4px;
    padding: .1rem .3rem; font-size: .68rem; font-weight: 600;
  }
  .perim-badge.unset { background: #b91c1c; }
  .commune-hint {
    display: block; font-size: .7rem; opacity: .65; margin-top: .1rem;
  }
  .total-sub { opacity: .6; font-weight: 400; }

  .type-badge {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: .66rem; font-weight: 600; color: #fff; white-space: nowrap;
  }

  .name-cell { max-width: 180px; }
  .entity-link {
    color: #93c5fd; font-weight: 500;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block;
  }
  .entity-link:hover { color: #bfdbfe; text-decoration: underline; }

  .addr-cell   { max-width: 160px; color: #94a3b8; font-size: .74rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .detail-cell { max-width: 180px; color: #94a3b8; font-size: .74rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .resp-cell   { max-width: 120px; color: #cbd5e1; font-size: .76rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .contact-cell { text-align: center; font-size: .88rem; }
  .empty-contact { color: #334155; }

  .conf { font-size: .7rem; border-radius: 3px; padding: 1px 5px; }
  .conf-verified   { color: #4ade80; background: #052e16; }
  .conf-probable   { color: #fbbf24; background: #451a03; }
  .conf-hypothesis { color: #94a3b8; background: #1e293b; }

  .center { text-align: center; color: #475569; }

  .actions-cell { display: flex; gap: .2rem; align-items: center; white-space: nowrap; }

  .act {
    width: 26px; height: 26px; border-radius: 4px;
    border: 1px solid #334155; font-size: .78rem; cursor: pointer;
    display: flex; align-items: center; justify-content: center; transition: all .12s;
    text-decoration: none;
  }
  .act-edit   { background: #1e293b; color: #e2e8f0; font-size: .82rem; }
  .act-edit:hover { background: #334155; border-color: #475569; }
  /* Des mots, plus des ✓ ✗ nus : on sait ce que fait le bouton avant d'appuyer. */
  .act-mot { width: auto; padding: 0 .45rem; font-size: .72rem; }
  .act-jamais_relu { background: #1e293b; color: #cbd5e1; }
  .act-jamais_relu:hover { background: #334155; border-color: #475569; }
  .act-a_revoir { background: #1e3a5f; color: #93c5fd; }
  .act-a_revoir:hover { background: #1d4ed8; border-color: #1d4ed8; }
  .act-retenu  { background: #052e16; color: #4ade80; }
  .act-retenu:hover { background: #166534; border-color: #166534; }
  .act-ecarte  { background: #450a0a; color: #f87171; }
  .act-ecarte:hover { background: #7f1d1d; border-color: #7f1d1d; }

  .msg { padding: 2rem; text-align: center; color: #64748b; font-size: .85rem; }
  .msg.error { color: #f87171; }
  .avis {
    margin: .25rem 0 .5rem; padding: .5rem .75rem;
    background: #3b2506; border: 1px solid #b45309; border-radius: 6px;
    color: #fde68a; font-size: .82rem;
  }

  .load-more {
    align-self: center; margin: .4rem 0;
    padding: .4rem 1.1rem; border: 1px solid #334155;
    border-radius: 6px; background: #1e293b; color: #94a3b8;
    font-size: .78rem; cursor: pointer;
  }
  .load-more:hover { border-color: #475569; color: #e2e8f0; }
</style>
