<script>
  // Revue & annotation des données importées (délibs / flux / marchés).
  // Le manque central pointé par CARTE_PRODUIT §4 : ces données étaient
  // collectées mais ni éditables ni validables côté atelier.
  import { api } from '$lib/api.js'

  const TABS = [
    { key: 'deliberation', label: 'Délibérations' },
    { key: 'flow',         label: 'Flux financiers' },
    { key: 'marche',       label: 'Marchés publics' },
  ]
  const STATUSES = [
    { key: '',          label: 'Tous' },
    { key: 'pending',   label: 'À revoir' },
    { key: 'validated', label: 'Validés' },
    { key: 'rejected',  label: 'Rejetés' },
  ]
  const CONFIDENCES = ['', 'verified', 'confirmed', 'probable', 'hypothesis']

  // Filtrer par origine n'est pas du confort : c'est ce qui rend l'arbitrage
  // faisable. Sur 9 264 actes, 4 934 seulement sont rectifiables — les autres
  // viennent d'une administration et ne se réécrivent pas. Et « non classé »
  // est la liste qu'il faut regarder pour déclarer les sources manquantes,
  // sans quoi ces lignes restent invisibles ET non corrigeables.
  const ORIGINES = [
    { key: '',               label: 'Toutes origines' },
    { key: 'verbatim',       label: 'Lu dans un document' },
    { key: 'institutionnel', label: 'Source institutionnelle' },
    { key: 'atelier',        label: 'Saisi à la main' },
    { key: 'non-classe',     label: 'Non classé' },
  ]

  let tab = 'deliberation'
  let statusFilter = ''
  let origineFilter = ''
  let items = []
  let loading = false
  let error = ''
  let selected = null        // item en cours d'annotation
  let draft = { review_status: 'pending', confidence: '', note: '' }
  let saving = false

  // ─── Corrections ───────────────────────────────────────────────────────────
  // Annoter « rejeté » fait disparaître la donnée ; le plus souvent il faut la
  // rectifier — un montant OCR aberrant, une date, un statut de cession. La
  // correction n'écrase pas la ligne source : elle est appliquée à la
  // publication, et le site affiche « rectifié ».
  const LIBELLES_CHAMPS = {
    date: 'Date', title: 'Titre', source_url: 'URL source', montant: 'Montant',
    year: 'Année', amount: 'Montant', description: 'Libellé',
    statut: 'Statut', type_norm: 'Type normalisé',
    date_notif: 'Date de notification', objet: 'Objet',
    titulaire_nom: 'Titulaire', acheteur_nom: 'Acheteur',
  }
  let champsParType = {}     // {type: {champ: genre}}
  let statutsFlux = []
  let corrections = {}       // brouillon des corrections de la ligne courante

  $: champsDuType = Object.entries(champsParType[tab] || {})
  // Valeur d'origine du champ, telle que la donnée source la porte.
  const valeurSource = (it, champ) => it?.[champ] ?? ''

  // ─── Origine ───────────────────────────────────────────────────────────────
  // Une donnée structurée par une administration (OFGL, BOAMP, BODACC, DECP…)
  // ne se réécrit pas à la main : le montant est celui qu'elle publie. Ce qui
  // vient d'une lecture — PDF, page web, OCR — le peut, parce que le chiffre y
  // est notre interprétation d'une phrase. L'API refuse de toute façon ; ce qui
  // suit évite d'offrir un champ dont on saura ensuite qu'il sera rejeté.
  const LIBELLE_ORIGINE = {
    institutionnel: 'source institutionnelle',
    verbatim: 'lu dans un document',
    atelier: 'saisi à la main',
  }
  $: rectifiable = selected
      && ['verbatim', 'atelier'].includes(selected.origine)

  async function load() {
    loading = true; error = ''; selected = null
    try {
      items = await api.donnees(tab, statusFilter, 300, origineFilter)
    } catch (e) {
      error = e.message || 'Erreur de chargement'
      items = []
    } finally {
      loading = false
    }
  }

  function pick(it) {
    selected = it
    draft = {
      review_status: it.annotation?.review_status || 'pending',
      confidence:    it.annotation?.confidence || '',
      note:          it.annotation?.note || '',
    }
    corrections = { ...(it.annotation?.corrections || {}) }
  }

  async function save() {
    if (!selected) return
    saving = true; error = ''
    try {
      // Un champ vidé est envoyé quand même : côté API, une valeur vide
      // ANNULE la correction et rend la donnée d'origine. Ne pas l'envoyer
      // laisserait la correction précédente en place.
      const aEnvoyer = {}
      for (const [champ] of champsDuType) {
        const v = corrections[champ]
        if (v !== undefined) aEnvoyer[champ] = v === '' ? null : v
      }
      const res = await api.annotate(tab, selected.id, { ...draft, corrections: aEnvoyer })
      corrections = { ...(res.corrections || {}) }
      selected.annotation = {
        ...selected.annotation,
        review_status: res.review_status,
        confidence: draft.confidence || null,
        note: draft.note,
        corrections: res.corrections || {},
      }
      items = items   // trigger reactivity
      if (statusFilter && res.review_status !== statusFilter) {
        items = items.filter(i => i.id !== selected.id)
        selected = null
      }
    } catch (e) {
      error = e.message || "Échec de l'enregistrement"
    } finally {
      saving = false
    }
  }

  $: counts = items.reduce((acc, it) => {
    const s = it.annotation?.review_status || 'pending'
    acc[s] = (acc[s] || 0) + 1
    return acc
  }, {})

  function fmtMontant(v) {
    if (v == null) return '—'
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(v)
  }

  $: tab, statusFilter, origineFilter, load()

  // Le front ne devine pas ce qui est corrigeable : il demande le contrat.
  api.champsCorrigeables()
    .then(r => { champsParType = r.champs || {}; statutsFlux = r.statuts_flux || [] })
    .catch(() => {})
</script>

<div class="donnees">
  <header class="top">
    <h1>Données importées</h1>
    <p class="sub">Revoir, annoter et valider les délibérations, flux financiers et marchés
       avant publication. L'annotation n'écrase jamais la donnée source.</p>
  </header>

  <div class="tabs">
    {#each TABS as t}
      <button class:active={tab === t.key} on:click={() => (tab = t.key)}>{t.label}</button>
    {/each}
  </div>

  <div class="toolbar">
    <div class="filters">
      {#each STATUSES as s}
        <button class="chip" class:on={statusFilter === s.key} on:click={() => (statusFilter = s.key)}>{s.label}</button>
      {/each}
      <select class="chip-select" bind:value={origineFilter}>
        {#each ORIGINES as o}<option value={o.key}>{o.label}</option>{/each}
      </select>
    </div>
    <div class="legend">
      <span class="pill pending">{counts.pending || 0} à revoir</span>
      <span class="pill validated">{counts.validated || 0} validés</span>
      <span class="pill rejected">{counts.rejected || 0} rejetés</span>
    </div>
  </div>

  {#if error}<div class="err">{error}</div>{/if}

  <div class="layout">
    <div class="table-wrap">
      {#if loading}
        <p class="muted">Chargement…</p>
      {:else if items.length === 0}
        <p class="muted">Aucune donnée pour ce filtre.</p>
      {:else}
        <table>
          <thead>
            {#if tab === 'deliberation'}
              <tr><th>Date</th><th>Type</th><th>Titre</th><th>Statut</th></tr>
            {:else if tab === 'flow'}
              <tr><th>Année</th><th>Type</th><th>Montant</th><th>Bénéficiaire</th><th>Statut</th></tr>
            {:else}
              <tr><th>Date</th><th>Acheteur</th><th>Titulaire</th><th>Montant</th><th>Statut</th></tr>
            {/if}
          </thead>
          <tbody>
            {#each items as it (it.id)}
              <tr class:sel={selected?.id === it.id} on:click={() => pick(it)}>
                {#if tab === 'deliberation'}
                  <td class="nowrap">{it.date || '—'}</td>
                  <td>{it.type}</td>
                  <td class="title">{it.title || it.excerpt || '—'}</td>
                {:else if tab === 'flow'}
                  <td>{it.year || '—'}</td>
                  <td>{it.type || '—'}</td>
                  <td class="nowrap">{fmtMontant(it.amount)}</td>
                  <td class="title">{it.to_name || it.description || '—'}</td>
                {:else}
                  <td class="nowrap">{it.date_notif || '—'}</td>
                  <td>{it.acheteur_nom || '—'}</td>
                  <td>{it.titulaire_nom || '—'}</td>
                  <td class="nowrap">{fmtMontant(it.montant)}</td>
                {/if}
                <td>
                  <span class="dot {it.annotation?.review_status || 'pending'}"></span>
                  {#if Object.keys(it.annotation?.corrections || {}).length}<span class="crayon" title="Donnée rectifiée">✎</span>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <aside class="panel" class:empty={!selected}>
      {#if !selected}
        <p class="muted">Sélectionne une ligne pour l'annoter.</p>
      {:else}
        <h2>Annotation</h2>
        <div class="src">
          {#if tab === 'deliberation'}
            <strong>{selected.title || '(sans titre)'}</strong>
            <p class="excerpt">{selected.excerpt || ''}</p>
          {:else if tab === 'flow'}
            <strong>{fmtMontant(selected.amount)} · {selected.type || ''}</strong>
            <p class="excerpt">{selected.from_name || '?'} → {selected.to_name || '?'} ({selected.year || '—'})</p>
            <p class="excerpt">{selected.description || ''}</p>
          {:else}
            <strong>{selected.objet || '(objet inconnu)'}</strong>
            <p class="excerpt">{selected.acheteur_nom} → {selected.titulaire_nom || '?'} · {fmtMontant(selected.montant)}</p>
          {/if}
          <p class="origine {selected.origine || 'inconnue'}">
            {LIBELLE_ORIGINE[selected.origine] || 'origine non classée'}
            {#if selected.saisi_par}· {selected.saisi_par}{/if}
          </p>
          {#if selected.source_url}
            <a class="src-link" href={selected.source_url} target="_blank" rel="noopener">↗ source</a>
          {/if}
          {#if selected.document_id}
            <a class="src-link" href={`/api/atelier/documents/${selected.document_id}/fichier`}
               target="_blank" rel="noopener">↗ document archivé</a>
          {/if}
        </div>

        <label class="field">
          <span>Statut de revue</span>
          <div class="seg">
            {#each ['pending','validated','rejected'] as s}
              <button class:on={draft.review_status === s} on:click={() => (draft.review_status = s)}>
                {s === 'pending' ? 'À revoir' : s === 'validated' ? 'Valider' : 'Rejeter'}
              </button>
            {/each}
          </div>
        </label>

        <label class="field">
          <span>Fiabilité</span>
          <select bind:value={draft.confidence}>
            {#each CONFIDENCES as c}
              <option value={c}>{c || '— (non renseigné)'}</option>
            {/each}
          </select>
        </label>

        {#if champsDuType.length && !rectifiable}
          <div class="field corrections verrou">
            <span>Corriger la donnée</span>
            <p class="hint">
              {#if selected.origine === 'institutionnel'}
                Cette ligne vient d'un collecteur institutionnel : sa valeur est
                celle que publie l'administration source, et l'atelier ne la
                réécrit pas. Vous pouvez en revanche <strong>l'écarter de la
                publication</strong> ci-dessus, ou la commenter.
              {:else}
                L'origine de cette ligne n'est pas classée : par précaution, sa
                valeur n'est pas modifiable. Lancer
                <code>scripts/classer_origine.py</code>, qui indiquera la source
                à déclarer.
              {/if}
            </p>
          </div>
        {:else if champsDuType.length}
          <div class="field corrections">
            <span>Corriger la donnée</span>
            <p class="hint">
              La ligne source n'est pas modifiée. La correction s'applique à la
              publication, et le site affiche « rectifié ». Vider un champ annule
              sa correction.
            </p>
            {#each champsDuType as [champ, genre]}
              <label class="corr">
                <span class="corr-lab">
                  {LIBELLES_CHAMPS[champ] || champ}
                  {#if corrections[champ] != null && corrections[champ] !== ''}
                    <em class="marque">rectifié</em>
                  {/if}
                </span>
                {#if genre === 'statut'}
                  <select bind:value={corrections[champ]}>
                    <option value="">— source : {valeurSource(selected, champ) || '—'}</option>
                    {#each statutsFlux as s}<option value={s}>{s}</option>{/each}
                  </select>
                {:else if genre === 'texte'}
                  <textarea rows="2" bind:value={corrections[champ]}
                            placeholder={String(valeurSource(selected, champ) || '—')}></textarea>
                {:else if genre === 'montant' || genre === 'annee'}
                  <!-- `type` ne peut pas être dynamique avec bind:value (Svelte) :
                       les deux variantes sont écrites en clair. -->
                  <input type="number" step={genre === 'montant' ? '0.01' : '1'}
                         bind:value={corrections[champ]}
                         placeholder={String(valeurSource(selected, champ) ?? '—')} />
                {:else}
                  <input type="text" bind:value={corrections[champ]}
                         placeholder={String(valeurSource(selected, champ) ?? '—')} />
                {/if}
              </label>
            {/each}
          </div>
        {/if}

        <label class="field">
          <span>Note</span>
          <textarea rows="4" bind:value={draft.note}
                    placeholder="Pourquoi cette correction ? La note s'affiche au survol du repère « rectifié » sur le site public."></textarea>
        </label>

        <button class="save" on:click={save} disabled={saving}>
          {saving ? 'Enregistrement…' : 'Enregistrer'}
        </button>
        {#if selected.annotation?.reviewed_by}
          <p class="meta">Dernière revue : {selected.annotation.reviewed_by}{selected.annotation.reviewed_at ? ' · ' + selected.annotation.reviewed_at : ''}</p>
        {/if}
      {/if}
    </aside>
  </div>
</div>

<style>
  .donnees { padding: 1.25rem 1.5rem; height: 100%; overflow-y: auto; color: #e2e8f0; }
  .top h1 { font-size: 1.4rem; margin: 0; }
  .sub { color: #94a3b8; font-size: .85rem; max-width: 70ch; margin: .35rem 0 1rem; }

  .tabs { display: flex; gap: .25rem; margin-bottom: .75rem; }
  .tabs button {
    padding: .4rem .9rem; border-radius: 6px; background: #1e293b; color: #94a3b8; font-size: .85rem;
  }
  .tabs button.active { background: #3b82f6; color: #fff; }

  .toolbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: .75rem; }
  .filters { display: flex; gap: .35rem; }
  .chip { padding: .25rem .7rem; border-radius: 999px; background: #1e293b; color: #94a3b8; font-size: .78rem; }
  .chip.on { background: #334155; color: #fff; }
  .chip-select { width: auto; padding: .25rem .5rem; border-radius: 999px;
                 background: #1e293b; color: #94a3b8; font-size: .78rem;
                 border: none; }

  .crayon { color: #34d399; font-size: .8rem; margin-left: .25rem; }

  .origine { margin: .4rem 0 0; font-size: .7rem; text-transform: uppercase;
             letter-spacing: .04em; }
  .origine.institutionnel { color: #60a5fa; }
  .origine.verbatim       { color: #a78bfa; }
  .origine.atelier        { color: #34d399; }
  .origine.inconnue       { color: #f59e0b; }
  .corrections.verrou .hint { color: #94a3b8; }
  .corrections.verrou code { background: #0f172a; padding: 0 .25rem; border-radius: 3px; }
  .corrections { border-top: 1px solid #1e293b; padding-top: .75rem; margin-top: .25rem; }
  .corrections .hint { color: #64748b; font-size: .74rem; line-height: 1.45;
                       margin: .2rem 0 .6rem; font-weight: 400; }
  .corr { display: block; margin-bottom: .5rem; }
  .corr-lab { display: block; font-size: .74rem; color: #94a3b8; margin-bottom: .15rem; }
  .corr .marque { color: #34d399; font-style: normal; font-size: .68rem;
                  text-transform: uppercase; letter-spacing: .03em; margin-left: .3rem; }
  .corr input, .corr select, .corr textarea {
    width: 100%; background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
    border-radius: 6px; padding: .35rem .5rem; font-size: .82rem; font-family: inherit;
  }
  .corr input::placeholder, .corr textarea::placeholder { color: #475569; }
  .legend { display: flex; gap: .4rem; }
  .pill { font-size: .72rem; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
  .pill.pending   { background: #78350f; color: #fde68a; }
  .pill.validated { background: #065f46; color: #d1fae5; }
  .pill.rejected  { background: #7f1d1d; color: #fecaca; }

  .err { background: #7f1d1d; color: #fecaca; padding: .5rem .75rem; border-radius: 6px; margin-bottom: .75rem; font-size: .85rem; }

  .layout { display: grid; grid-template-columns: 1fr 340px; gap: 1rem; align-items: start; }
  .table-wrap { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  thead th { text-align: left; padding: .5rem .7rem; color: #64748b; font-weight: 600; border-bottom: 1px solid #1e293b; position: sticky; top: 0; background: #0f172a; }
  tbody td { padding: .45rem .7rem; border-bottom: 1px solid #1e293b; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #1e293b; }
  tbody tr.sel { background: #1d3a5f; }
  .nowrap { white-space: nowrap; }
  .title { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .muted { color: #64748b; font-size: .85rem; padding: 1rem; }

  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; }
  .dot.pending   { background: #f59e0b; }
  .dot.validated { background: #10b981; }
  .dot.rejected  { background: #ef4444; }

  .panel { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem; position: sticky; top: 0; }
  .panel.empty { display: flex; align-items: center; justify-content: center; min-height: 120px; }
  .panel h2 { font-size: 1rem; margin: 0 0 .6rem; }
  .src { background: #0f172a; border-radius: 6px; padding: .6rem .7rem; margin-bottom: .8rem; }
  .src strong { font-size: .85rem; }
  .excerpt { color: #94a3b8; font-size: .78rem; margin: .3rem 0 0; line-height: 1.4; }
  .src-link { display: inline-block; margin-top: .4rem; font-size: .78rem; }

  .field { display: block; margin-bottom: .8rem; }
  .field > span { display: block; font-size: .75rem; color: #94a3b8; margin-bottom: .3rem; }
  .seg { display: flex; gap: .25rem; }
  .seg button { flex: 1; padding: .35rem; border-radius: 5px; background: #0f172a; color: #94a3b8; font-size: .78rem; }
  .seg button.on { background: #3b82f6; color: #fff; }
  select, textarea { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 5px; color: #e2e8f0; padding: .4rem; font: inherit; font-size: .82rem; }
  .save { width: 100%; padding: .55rem; border-radius: 6px; background: #2563eb; color: #fff; font-weight: 600; }
  .save:disabled { opacity: .6; }
  .meta { color: #64748b; font-size: .72rem; margin: .5rem 0 0; }

  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
</style>
