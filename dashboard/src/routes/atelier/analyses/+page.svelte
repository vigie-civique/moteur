<script>
  import { onMount } from 'svelte'
  import { authFetch } from '$lib/stores/auth.js'

  let mandats     = []
  let conflits    = []
  let adresses    = []
  let familles    = []
  let loading     = true
  let error       = ''

  // filtres
  let minRoles  = 2
  let activeTab = 'mandats'
  let chronoFilter = 'tous'  // tous | contemporain | lien_sans_flux | dates_manquantes

  onMount(() => loadAll())

  async function loadAll() {
    loading = true; error = ''
    try {
      const [r1, r2, r3, r4] = await Promise.all([
        authFetch(`/analyses/mandats-croises?min_roles=${minRoles}`),
        authFetch('/analyses/conflits'),
        authFetch('/analyses/adresses-partagees'),
        authFetch('/analyses/familles?min_personnes=2'),
      ])
      mandats  = r1.ok ? await r1.json() : []
      conflits = r2.ok ? await r2.json() : []
      adresses = r3.ok ? await r3.json() : []
      familles = r4.ok ? await r4.json() : []
    } catch(e) { error = e.message }
    finally { loading = false }
  }

  const CHRONO_LABELS = {
    contemporain:        '⚠ Contemporain (flux pendant le mandat)',
    chevauchement_annee: '~ Chevauchement d\'année (ambiguïté — date exacte manquante)',
    lien_sans_flux:      'Lien sans flux documenté',
    dates_manquantes:    'Dates de mandat inconnues',
    hors_mandat:         'Hors mandat (flux après fin)',
    anterieur_mandat:    'Antérieur au mandat',
  }
  const CHRONO_ORDER = ['contemporain','chevauchement_annee','lien_sans_flux','dates_manquantes','hors_mandat','anterieur_mandat']

  // Grouper par chronologie, dédupliquer par person+entite+flux_annee
  $: conflitsGroupes = (() => {
    const seen = new Set()
    const groups = {}
    for (const c of conflits) {
      const key = `${c.person_id}_${c.entite_id}_${c.flux_annee ?? 'x'}_${c.role_elu}`
      if (seen.has(key)) continue
      seen.add(key)
      if (!groups[c.chronologie]) groups[c.chronologie] = []
      groups[c.chronologie].push(c)
    }
    return groups
  })()

  // Total dédupliqué (compteur de l'onglet) : les groupes portent déjà la dédup.
  $: conflitsDedup = Object.values(conflitsGroupes).flat()

  function fmtDate(d) { return d ? d.slice(0,10) : '?' }
  function fmtFluxDate(c) { return c.flux_date ? c.flux_date.slice(0,10) : (c.flux_annee ?? '—') }
  function fmtMontant(v) { return v != null ? v.toLocaleString('fr-FR') + ' €' : '—' }

  const TABS = [
    { id: 'mandats',  label: 'Mandats croisés' },
    { id: 'conflits', label: 'Conflits potentiels' },
    { id: 'adresses', label: 'Adresses partagées' },
    { id: 'familles', label: 'Familles' },
  ]
</script>

<svelte:head><title>Analyses croisées — Atelier Lasalle</title></svelte:head>

<div class="analyses-page">
  <div class="page-header">
    <h1>Analyses croisées</h1>
    <span class="muted">Données privées — non publiées</span>
  </div>

  {#if error}<p class="err">{error}</p>{/if}

  <div class="tabs">
    {#each TABS as t}
      <button class="tab" class:active={activeTab === t.id} on:click={() => activeTab = t.id}>
        {t.label}
        <span class="tab-count">
          {#if t.id === 'mandats'}{mandats.length}
          {:else if t.id === 'conflits'}{conflitsDedup.length}
          {:else if t.id === 'adresses'}{adresses.length}
          {:else}{familles.length}{/if}
        </span>
      </button>
    {/each}
    <button class="btn-reload" on:click={loadAll} disabled={loading}>↺</button>
  </div>

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else}

    <!-- ── Mandats croisés ── -->
    {#if activeTab === 'mandats'}
      <div class="section-header">
        <p class="section-desc">Personnes cumulant plusieurs rôles publics (élu, dirigeant, agent).</p>
        <label class="filter-label">
          Min rôles :
          <input type="number" bind:value={minRoles} min="2" max="6"
                 on:change={loadAll} class="nb-input" />
        </label>
      </div>
      {#if mandats.length === 0}
        <p class="muted-center">Aucun résultat.</p>
      {:else}
        <table class="data-table">
          <thead>
            <tr>
              <th>Personne</th><th>Rôles élu</th><th>Rôles privés</th><th>Total</th><th>Détail</th>
            </tr>
          </thead>
          <tbody>
            {#each mandats as m}
              <tr class:high={m.nb_roles >= 4}>
                <td><a href="/atelier/entite/{m.person_id}" class="ent-link">{m.person_name}</a></td>
                <td class="center"><span class="badge badge-elu">{m.nb_mandats_elus}</span></td>
                <td class="center"><span class="badge badge-priv">{m.nb_mandats_prives}</span></td>
                <td class="center bold">{m.nb_roles}</td>
                <td class="roles-cell">{m.roles}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    <!-- ── Conflits potentiels ── -->
    {:else if activeTab === 'conflits'}
      <div class="section-header">
        <p class="section-desc">Élus CM/CC dirigeant une entité avec des liens financiers. Filtrés par chevauchement temporel mandat ↔ flux.</p>
        <div class="chrono-filter">
          <label class="filter-label">Chronologie :
            <select bind:value={chronoFilter} class="nb-input" style="width:200px">
              <option value="tous">Tous ({conflitsDedup.length})</option>
              {#each CHRONO_ORDER as k}
                {#if conflitsGroupes[k]}
                  <option value={k}>{CHRONO_LABELS[k]} ({conflitsGroupes[k].length})</option>
                {/if}
              {/each}
            </select>
          </label>
        </div>
      </div>

      <p class="chrono-note">
        <strong>Méthode :</strong> un conflit est marqué <em>contemporain</em> si le flux financier a eu lieu pendant la période de mandat élu connue.
        <em>Lien sans flux</em> = structure à surveiller, aucun flux documenté à ce jour.
      </p>

      {#each CHRONO_ORDER as chrono}
        {#if conflitsGroupes[chrono] && (chronoFilter === 'tous' || chronoFilter === chrono)}
          <h3 class="sub-h chrono-{chrono}" style="margin-top:1rem">
            {CHRONO_LABELS[chrono]} — {conflitsGroupes[chrono].length}
          </h3>
          <table class="data-table" class:dimmed={chrono === 'hors_mandat' || chrono === 'anterieur_mandat'}>
            <thead>
              <tr>
                <th>Élu</th><th>Rôle élu</th><th>Fenêtre mandat</th>
                <th>Entité</th><th>Rôle</th>
                {#if chrono !== 'lien_sans_flux'}<th>Flux</th><th>Montant</th><th>Date flux</th>{/if}
              </tr>
            </thead>
            <tbody>
              {#each conflitsGroupes[chrono] as c}
                <tr class:conflict-row={chrono === 'contemporain'}
                    class:chev-row={chrono === 'chevauchement_annee'}>
                  <td><a href="/atelier/entite/{c.person_id}" class="ent-link">{c.person_name}</a></td>
                  <td><span class="badge badge-elu">{c.role_elu}</span></td>
                  <td class="muted dates-cell">{fmtDate(c.mandat_debut)} → {fmtDate(c.mandat_fin) === '?' ? 'en cours' : fmtDate(c.mandat_fin)}</td>
                  <td><a href="/atelier/entite/{c.entite_id}" class="ent-link">{c.entite_nom}</a></td>
                  <td class="muted">{c.role_entite}</td>
                  {#if chrono !== 'lien_sans_flux'}
                    <td class="muted">{c.flux_type ?? '—'}</td>
                    <td class="montant">{fmtMontant(c.flux_montant)}</td>
                    <td class="muted dates-cell" class:exact-date={!!c.flux_date}>{fmtFluxDate(c)}</td>
                  {/if}
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {/each}

    <!-- ── Adresses partagées ── -->
    {:else if activeTab === 'adresses'}
      <div class="section-header">
        <p class="section-desc">Adresses regroupant ≥3 entreprises ou associations (domiciliation multiple).</p>
      </div>
      {#if adresses.length === 0}
        <p class="muted-center">Aucune adresse partagée détectée.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Adresse</th><th>Entités</th><th>Biz</th><th>Asso</th><th>Noms</th></tr></thead>
          <tbody>
            {#each adresses as a}
              <tr>
                <td class="addr-cell">{a.address}</td>
                <td class="center bold">{a.nb_entites}</td>
                <td class="center">{a.nb_biz}</td>
                <td class="center">{a.nb_asso}</td>
                <td class="names-cell muted">{a.entity_names}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

    <!-- ── Familles ── -->
    {:else if activeTab === 'familles'}
      <div class="section-header">
        <p class="section-desc">Personnes partageant le même nom de famille (≥2). Peut inclure des homonymes.</p>
      </div>
      {#if familles.length === 0}
        <p class="muted-center">Aucune famille détectée.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>Nom</th><th>Personnes</th><th>Membres</th></tr></thead>
          <tbody>
            {#each familles as f}
              <tr class:high={f.nb_personnes >= 5}>
                <td class="bold">{f.lastname}</td>
                <td class="center">{f.nb_personnes}</td>
                <td class="names-cell muted">{f.person_names}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}

  {/if}
</div>

<style>
  .analyses-page { padding: 1.2rem; max-width: 1100px; }
  .page-header { display: flex; align-items: baseline; gap: 1rem; margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }

  .tabs { display: flex; gap: .3rem; border-bottom: 1px solid #334155; margin-bottom: 1rem; flex-wrap: wrap; }
  .tab {
    padding: .4rem .75rem; font-size: .78rem; color: #94a3b8; cursor: pointer;
    border-bottom: 2px solid transparent; background: none; border-radius: 4px 4px 0 0;
    display: flex; align-items: center; gap: .35rem;
  }
  .tab.active { color: #60a5fa; border-bottom-color: #60a5fa; }
  .tab:hover:not(.active) { color: #e2e8f0; }
  .tab-count { font-size: .68rem; background: #334155; color: #94a3b8; border-radius: 999px; padding: 1px 5px; }
  .tab.active .tab-count { background: #1d4ed8; color: #bfdbfe; }
  .btn-reload { margin-left: auto; background: none; border: none; color: #64748b; cursor: pointer; font-size: .85rem; padding: .3rem .5rem; }
  .btn-reload:hover { color: #e2e8f0; }

  .section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: .75rem; gap: 1rem; flex-wrap: wrap; }
  .section-desc { font-size: .78rem; color: #64748b; margin: 0; }
  .filter-label { display: flex; align-items: center; gap: .4rem; font-size: .75rem; color: #94a3b8; }
  .nb-input { width: 52px; background: #1e293b; border: 1px solid #334155; color: #e2e8f0; border-radius: 4px; padding: .2rem .4rem; font-size: .78rem; text-align: center; }

  .sub-h { font-size: .82rem; font-weight: 600; color: #f59e0b; margin: .4rem 0 .5rem; }

  .data-table { width: 100%; border-collapse: collapse; font-size: .77rem; }
  .data-table.dimmed { opacity: .65; }
  .data-table th { background: #1e293b; color: #64748b; font-weight: 600; text-transform: uppercase; font-size: .65rem; letter-spacing: .04em; padding: .4rem .6rem; text-align: left; border-bottom: 1px solid #334155; }
  .data-table td { padding: .38rem .6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; vertical-align: top; }
  .data-table tr.high td { background: #1a1000; }
  .data-table tr.conflict-row td { background: #1a0a0a; }
  .data-table tr:hover td { background: #1e293b; }

  .ent-link { color: #93c5fd; }
  .ent-link:hover { text-decoration: underline; }
  .badge { font-size: .65rem; padding: 1px 6px; border-radius: 999px; font-weight: 700; }
  .badge-elu  { background: #1d4ed8; color: #bfdbfe; }
  .badge-priv { background: #065f46; color: #6ee7b7; }
  .center { text-align: center; }
  .bold { font-weight: 600; }
  .montant { font-weight: 700; color: #fb923c; }
  .roles-cell { color: #64748b; font-size: .72rem; max-width: 300px; }
  .addr-cell { font-size: .75rem; }
  .names-cell { font-size: .7rem; max-width: 380px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .muted { color: #64748b; }

  .err { color: #f87171; font-size: .83rem; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; font-size: .85rem; }

  .chrono-filter { display: flex; align-items: center; gap: .5rem; }
  .chrono-note { font-size: .72rem; color: #64748b; background: #1e293b; border-left: 3px solid #334155; padding: .4rem .75rem; margin-bottom: .5rem; border-radius: 0 4px 4px 0; }
  .chrono-note em { color: #94a3b8; font-style: normal; font-weight: 600; }

  .sub-h.chrono-contemporain       { color: #f87171; }
  .sub-h.chrono-chevauchement_annee { color: #fb923c; }
  .sub-h.chrono-lien_sans_flux     { color: #f59e0b; }
  .sub-h.chrono-dates_manquantes   { color: #94a3b8; }
  .sub-h.chrono-hors_mandat,
  .sub-h.chrono-anterieur_mandat   { color: #475569; }

  .data-table tr.chev-row td { background: #1a0d00; }
  .exact-date { color: #a3e635 !important; font-weight: 600; }

  .dates-cell { font-size: .7rem; white-space: nowrap; }
</style>
