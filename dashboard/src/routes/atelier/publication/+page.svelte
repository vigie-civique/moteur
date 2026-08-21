<script>
  import { SITE_NOM, SITE_NOM_ATELIER } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { currentUser } from '$lib/stores/auth.js'

  const KEY_STORAGE = 'vigie-admin-key'

  let adminKey = ''
  let status = null
  let loading = false
  let generating = false
  let error = ''
  let saved = false
  let autoTried = false

  // Connecté avec le rôle admin → JWT suffit, la clé devient un fallback
  $: isAdmin = $currentUser?.role === 'admin'
  $: canAct = isAdmin || !!adminKey.trim()
  $: if (isAdmin && !status && !loading && !autoTried) {
    autoTried = true
    loadStatus()
  }

  $: stats = status?.stats || null
  $: exclusions = status?.exclusions || stats?.exclusions || {}
  $: project = status?.project || {}
  $: synced = status?.synced || null

  onMount(() => {
    adminKey = sessionStorage.getItem(KEY_STORAGE) || ''
    if (adminKey) loadStatus()
  })

  function rememberKey() {
    if (adminKey.trim()) {
      sessionStorage.setItem(KEY_STORAGE, adminKey.trim())
      saved = true
      setTimeout(() => saved = false, 1200)
    }
  }

  function forgetKey() {
    sessionStorage.removeItem(KEY_STORAGE)
    adminKey = ''
    status = null
  }

  async function loadStatus() {
    if (!canAct) return
    loading = true
    error = ''
    try {
      rememberKey()
      status = await api.publicSnapshotStatus(adminKey.trim())
    } catch (e) {
      error = e.message
      status = null
    } finally {
      loading = false
    }
  }

  async function generateSnapshot() {
    if (!canAct) return
    generating = true
    error = ''
    try {
      rememberKey()
      status = await api.generatePublicSnapshot(adminKey.trim())
    } catch (e) {
      error = e.message
    } finally {
      generating = false
    }
  }

  function fmt(n) {
    if (n === null || n === undefined || n === '') return '—'
    return Number(n).toLocaleString('fr-FR')
  }

  function entries(obj) {
    return Object.entries(obj || {})
  }

  // ─── Décisions : exporter / importer ────────────────────────────────────
  // La base est reconstructible, le jugement humain non. Ce qu'on partage,
  // ce ne sont pas les données — ce sont les arbitrages et les saisies.
  let decisions = null
  let rapport = null
  let sansPersonnes = false
  let occupe = ''

  async function etatDecisions() {
    try { decisions = await api.decisionsEtat() } catch { decisions = null }
  }
  onMount(etatDecisions)

  async function exporter() {
    occupe = 'export'; error = ''; rapport = null
    try {
      const r = await api.decisionsExporter(sansPersonnes)
      rapport = { type: 'export', ...r }
      await etatDecisions()
    } catch (e) { error = e.message } finally { occupe = '' }
  }

  // Deux temps, toujours : on lit le rapport, ensuite seulement on écrit.
  // Un import contredit parfois ses propres arbitrages, et c'est irréversible.
  async function importer(appliquer) {
    occupe = appliquer ? 'import' : 'blanc'; error = ''
    try {
      rapport = { type: appliquer ? 'import' : 'blanc',
                  ...(await api.decisionsImporter(appliquer)) }
    } catch (e) { error = e.message } finally { occupe = '' }
  }
</script>

<svelte:head>
  <title>Atelier publication — {SITE_NOM}</title>
</svelte:head>

<div class="page">
  <section class="topbar">
    <div>
      <p class="eyebrow">{project.private_name || SITE_NOM_ATELIER}</p>
      <h1>Publication</h1>
    </div>
    <div class="auth">
      {#if isAdmin}
        <span class="notice">Connecté admin — clé facultative</span>
      {/if}
      <input
        type="password"
        bind:value={adminKey}
        placeholder={isAdmin ? 'Clé admin (facultative)' : 'Clé admin'}
        on:keydown={(e) => e.key === 'Enter' && loadStatus()}
      />
      <button class="secondary" on:click={loadStatus} disabled={loading || !canAct}>
        {loading ? 'Lecture...' : 'Charger'}
      </button>
      <button class="ghost" on:click={forgetKey}>Oublier</button>
    </div>
  </section>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if saved}
    <p class="notice">Clé gardée pour cette session.</p>
  {/if}

  <section class="actions">
    <div>
      <h2>{project.public_name || SITE_NOM}</h2>
      <p class="muted">
        Sortie publique : {status?.output_dir || 'dashboard/static/public_api'}
      </p>
    </div>
    <button class="primary" on:click={generateSnapshot} disabled={generating || !canAct}>
      {generating ? 'Génération...' : 'Générer & synchroniser le snapshot'}
    </button>
  </section>

  <section class="decisions">
    <div class="dec-tete">
      <div>
        <h2>Décisions — exporter, reprendre</h2>
        <p class="muted">
          La base se refait toute seule avec le code et un code INSEE. Ce qui ne
          se refait pas, c'est le travail humain : les arbitrages, les
          corrections, les sites validés, les saisies. C'est ça qu'on transporte.
        </p>
      </div>
    </div>

    <div class="dec-actions">
      <label class="dec-opt">
        <input type="checkbox" bind:checked={sansPersonnes} />
        Retirer ce qui porte sur des personnes physiques
      </label>
      <button class="secondary" on:click={exporter} disabled={occupe || !isAdmin}>
        {occupe === 'export' ? 'Export…' : 'Exporter mes décisions'}
      </button>
      <button class="secondary" on:click={() => importer(false)} disabled={occupe || !isAdmin}>
        {occupe === 'blanc' ? 'Lecture…' : 'Lire un import (à blanc)'}
      </button>
      <button class="primary" on:click={() => importer(true)} disabled={occupe || !isAdmin}>
        {occupe === 'import' ? 'Import…' : 'Appliquer l\'import'}
      </button>
    </div>

    {#if !sansPersonnes}
      <p class="dec-alerte">
        ⚠ Un export complet peut nommer des personnes physiques : l'atelier
        travaille sur la base non filtrée. Le répertoire produit va dans un dépôt
        <strong>privé</strong>, ou nulle part.
      </p>
    {/if}

    {#if decisions?.present && decisions?.lisible}
      <p class="muted">
        Présent : {decisions.commune} ({decisions.insee}), exporté le
        {(decisions.exporte_le || '').slice(0, 16).replace('T', ' à ')}
        {#if decisions.sans_personnes}· sans personnes{/if}
        {#if decisions.compte}
          — {entries(decisions.compte).map(([k, v]) => `${v} ${k}`).join(', ')}
        {/if}
      </p>
    {:else if decisions && !decisions.present}
      <p class="muted">Aucun répertoire <code>decisions/</code> pour l'instant.</p>
    {/if}

    {#if rapport}
      <div class="dec-rapport">
        {#if rapport.type === 'export'}
          <p class="sync-ok">✓ Exporté vers <code>{rapport.vers}</code> —
            {entries(rapport.compte).filter(([k]) => !k.startsWith('_'))
              .map(([k, v]) => `${v} ${k}`).join(', ')}</p>
        {:else}
          <p class="sync-ok">
            {rapport.applique_reellement ? '✓ Appliqué' : 'Lecture à blanc'} :
            {rapport.appliquees} décision(s) {rapport.applique_reellement ? 'écrite(s)' : 'applicable(s)'},
            {rapport.deja_a_jour} déjà à jour
          </p>
          {#if rapport.desaccords?.length}
            <p class="dec-alerte">{rapport.desaccords.length} désaccord(s) — non appliqué(s).
              Deux jugements contraires se tranchent entre humains, pas par un import.</p>
            <ul class="dec-liste">
              {#each rapport.desaccords.slice(0, 6) as d}<li>{d}</li>{/each}
            </ul>
          {/if}
          {#if rapport.non_rattachees?.length}
            <p class="muted">{rapport.non_rattachees.length} objet(s) inconnu(s) ici —
              les deux collectes divergent.</p>
          {/if}
          {#if rapport.sans_objet?.length}
            <p class="muted">{rapport.sans_objet.length} objet(s) connu(s), mais aucune
              piste à arbitrer ici : un <code>run_all</code> la produira peut-être.</p>
          {/if}
        {/if}
      </div>
    {/if}
  </section>

  {#if synced}
    <section class="sync">
      <p class="sync-ok">✓ {synced.count} fichiers synchronisés vers le site public
        <code>{synced.dest}</code></p>
      <p class="sync-next">Prochaine étape — déployer :
        <code>cd public &amp;&amp; npm run build</code> puis push (Cloudflare Pages build sur push).</p>
    </section>
  {/if}

  {#if stats}
    <section class="metrics">
      <div class="metric">
        <span>{fmt(stats.entities_public)}</span>
        <small>entités publiques</small>
        <em>{fmt(stats.entities_total_private)} privées</em>
      </div>
      <div class="metric">
        <span>{fmt(stats.relations_public)}</span>
        <small>relations publiques</small>
        <em>{fmt(stats.relations_total_private)} privées</em>
      </div>
      <div class="metric">
        <span>{fmt(stats.events_public)}</span>
        <small>événements publics</small>
        <em>{fmt(stats.events_total_private)} privés</em>
      </div>
      <div class="metric">
        <span>{fmt(stats.map_features_public)}</span>
        <small>points carte</small>
        <em>{fmt(stats.urls_public_confirmed)} URLs confirmées</em>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Qualité localisation</h2>
        <table>
          <tbody>
            {#each entries(stats.location_quality) as [key, count]}
              <tr>
                <td>{key}</td>
                <td>{fmt(count)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h2>Exclusions</h2>
        {#each entries(exclusions) as [section, values]}
          <div class="block">
            <h3>{section}</h3>
            <table>
              <tbody>
                {#each entries(values) as [reason, count]}
                  <tr>
                    <td>{reason}</td>
                    <td>{fmt(count)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/each}
      </div>
    </section>

    <section class="rules">
      <h2>Règles actives</h2>
      <div class="rule-list">
        <span>confiance : {(status?.rules?.public_confidence || []).join(', ')}</span>
        <span>relations : {(status?.rules?.public_relation_types || []).length}</span>
        <span>rôles personnes : {(status?.rules?.public_person_relation_types || []).length}</span>
        <span>sources événements : {(status?.rules?.public_event_sources || []).join(', ')}</span>
      </div>
    </section>
  {:else}
    <section class="empty">
      <p>Entrer la clé admin pour charger l’état de publication.</p>
    </section>
  {/if}
</div>

<style>
  .page {
    width: 100%;
    height: 100%;
    overflow-y: auto;
    padding: 1rem;
    background: #0f172a;
  }

  .topbar, .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .eyebrow {
    font-size: .72rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .04em;
    margin-bottom: .25rem;
  }

  h1 {
    font-size: 1.25rem;
    font-weight: 700;
  }

  h2 {
    font-size: .92rem;
    font-weight: 700;
    margin-bottom: .45rem;
  }

  h3 {
    font-size: .78rem;
    color: #93c5fd;
    margin: .55rem 0 .25rem;
    text-transform: uppercase;
    letter-spacing: .03em;
  }

  .auth {
    display: flex;
    align-items: center;
    gap: .4rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  input {
    width: 220px;
    background: #020617;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #e2e8f0;
    padding: .42rem .55rem;
    font-size: .82rem;
  }

  button {
    border-radius: 6px;
    padding: .42rem .7rem;
    font-size: .8rem;
    font-weight: 650;
  }

  button:disabled {
    opacity: .45;
    cursor: default;
  }

  .primary {
    background: #2563eb;
    color: white;
  }

  .secondary {
    background: #334155;
    color: #e2e8f0;
  }

  .ghost {
    color: #94a3b8;
  }

  .muted, .notice {
    color: #94a3b8;
    font-size: .8rem;
  }

  .notice {
    margin-bottom: .7rem;
  }

  .error {
    background: #7f1d1d;
    color: #fee2e2;
    border: 1px solid #991b1b;
    border-radius: 6px;
    padding: .55rem .7rem;
    margin-bottom: .8rem;
    font-size: .82rem;
  }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .75rem;
    margin-bottom: 1rem;
  }

  .metric, .panel, .rules, .empty {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
  }

  .metric {
    padding: .8rem;
  }

  .metric span {
    display: block;
    font-size: 1.45rem;
    font-weight: 750;
    color: #bfdbfe;
  }

  .metric small {
    display: block;
    color: #e2e8f0;
    font-size: .78rem;
    margin-top: .1rem;
  }

  .metric em {
    display: block;
    color: #64748b;
    font-size: .72rem;
    font-style: normal;
    margin-top: .25rem;
  }

  .grid {
    display: grid;
    grid-template-columns: minmax(260px, 1fr) minmax(320px, 1.4fr);
    gap: .75rem;
  }

  .panel, .rules, .empty {
    padding: .9rem;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  td {
    border-bottom: 1px solid #334155;
    padding: .32rem 0;
    font-size: .78rem;
    color: #cbd5e1;
    vertical-align: top;
  }

  td:first-child {
    color: #94a3b8;
    padding-right: .75rem;
  }

  td:last-child {
    text-align: right;
    font-weight: 700;
  }

  .rules {
    margin-top: .75rem;
  }

  .rule-list {
    display: flex;
    flex-wrap: wrap;
    gap: .45rem;
  }

  .rule-list span {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 999px;
    padding: .22rem .55rem;
    color: #cbd5e1;
    font-size: .74rem;
  }

  .empty {
    color: #94a3b8;
    font-size: .85rem;
  }

  @media (max-width: 900px) {
    .topbar, .actions {
      align-items: stretch;
      flex-direction: column;
    }

    .auth {
      justify-content: flex-start;
    }

    .metrics, .grid {
      grid-template-columns: 1fr;
    }
  }

  .sync { margin: 1rem 0; padding: .75rem 1rem; background: #052e1a; border: 1px solid #065f46; border-radius: 8px; }
  .sync-ok { color: #6ee7b7; margin: 0 0 .35rem; font-size: .9rem; }
  .sync-next { color: #94a3b8; margin: 0; font-size: .82rem; }
  .sync code { background: #0f172a; padding: 1px 6px; border-radius: 4px; color: #cbd5e1; font-size: .78rem; }

  .decisions { margin: 1.25rem 0; padding: 1rem; background: #0f172a;
               border: 1px solid #1e293b; border-radius: 8px; }
  .decisions h2 { font-size: 1rem; margin: 0 0 .3rem; }
  .dec-actions { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap;
                 margin: .8rem 0 .5rem; }
  .dec-opt { display: flex; align-items: center; gap: .35rem; font-size: .8rem;
             color: #94a3b8; margin-right: auto; }
  .dec-opt input { width: auto; }
  .dec-alerte { color: #fbbf24; font-size: .8rem; line-height: 1.5; margin: .4rem 0; }
  .dec-rapport { margin-top: .7rem; border-top: 1px solid #1e293b; padding-top: .6rem; }
  .dec-liste { margin: .3rem 0 0; padding-left: 1.1rem; color: #94a3b8; font-size: .78rem; }
  .decisions code { background: #020617; padding: 1px 6px; border-radius: 4px;
                    color: #cbd5e1; font-size: .78rem; }
</style>
