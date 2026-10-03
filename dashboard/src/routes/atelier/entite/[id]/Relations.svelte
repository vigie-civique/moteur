<script>
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { cleLocale } from './brouillon.js'

  export let relations = []
  export let entityId
  export let brouillon            // { ajouts, modifs: {id: champs}, suppr }

  const REL_TYPES = [
    'dirigeant','gérant','associé','président','trésorier','secrétaire','membre',
    'élu_cm','élu_cc','candidat','agent_communal','membre_commission',
    'locataire_commune','bailleur_commune','subventionné','prestataire',
    'famille_présumé','époux_présumé','enfant_présumé','proche_présumé',
    'même_adresse','même_lieu_dit',
  ]
  const CHAMPS = ['relation_type', 'since', 'until', 'source', 'confidence']

  function relDir(r) {
    return r.from_id === entityId
      ? `→ ${r.to_name} (${r.to_type})`
      : `← ${r.from_name} (${r.from_type})`
  }

  // ── Modifier une relation existante ──────────────────────────────────────
  let editingRelId = null
  let editRelForm  = {}

  const valeurs = r => ({ relation_type: r.relation_type, since: r.since ?? '', until: r.until ?? '',
                          source: r.source ?? 'manual', confidence: r.confidence ?? 'verified' })

  function startEditRel(r) {
    editingRelId = r.id
    editRelForm  = { ...(brouillon.modifs[r.id] ?? valeurs(r)) }
  }

  function appliquer(r) {
    const avant = valeurs(r)
    const { [r.id]: _, ...autres } = brouillon.modifs
    const change = CHAMPS.some(k => String(editRelForm[k] ?? '') !== String(avant[k] ?? ''))
    brouillon.modifs = change ? { ...autres, [r.id]: { ...editRelForm } } : autres
    editingRelId = null
  }

  function annulerModif(id) {
    const { [id]: _, ...autres } = brouillon.modifs
    brouillon.modifs = autres
  }

  const basculerSuppr = id => brouillon.suppr = brouillon.suppr.includes(id)
    ? brouillon.suppr.filter(x => x !== id) : [...brouillon.suppr, id]

  // ── Ajouter une relation ─────────────────────────────────────────────────
  const relVide = () => ({ direction:'from', relation_type:'dirigeant', since:'', until:'', source:'manual',
                           confidence: auMoins($currentUser, 'validator') ? 'verified' : 'probable' })
  let newRel = relVide()
  let relSearch = ''
  let relSearchResults = []
  let relTarget = null
  let relSearchOpen = false
  let _searchTimer = null

  function onRelSearch() {
    clearTimeout(_searchTimer); relTarget = null
    if (relSearch.length < 2) { relSearchResults = []; relSearchOpen = false; return }
    _searchTimer = setTimeout(async () => {
      const r = await authFetch(`/search?q=${encodeURIComponent(relSearch)}&limit=8`)
      if (r.ok) { relSearchResults = await r.json(); relSearchOpen = relSearchResults.length > 0 }
    }, 280)
  }

  function selectTarget(e) { relTarget = e; relSearch = e.name; relSearchOpen = false }

  function ajouter() {
    if (!relTarget) return
    brouillon.ajouts = [...brouillon.ajouts,
      { cle: cleLocale(), cible: { id: relTarget.id, name: relTarget.name, type: relTarget.type },
        corps: { ...newRel } }]
    newRel = relVide()
    relTarget = null; relSearch = ''
  }

  const retirer = cle => brouillon.ajouts = brouillon.ajouts.filter(a => a.cle !== cle)
</script>

<section class="card">
  <h2>Relations <span class="count-badge">{relations.length}</span></h2>

  {#if relations.length === 0 && brouillon.ajouts.length === 0}
    <p class="muted">Aucune relation connue.</p>
  {:else}
    <ul class="relation-list">
      {#each relations as r (r.id)}
        {@const m = brouillon.modifs[r.id]}
        {@const v = m ?? r}
        <li class="rel-item" class:editing={editingRelId === r.id}
            class:a-supprimer={brouillon.suppr.includes(r.id)} class:a-modifier={m}>
          {#if editingRelId === r.id}
            <div class="rel-edit-form">
              <div class="rel-edit-row">
                <label>Type
                  <select bind:value={editRelForm.relation_type}>
                    {#each REL_TYPES as t}<option value={t}>{t}</option>{/each}
                  </select>
                </label>
                <label>Depuis<input bind:value={editRelForm.since} placeholder="AAAA-MM-JJ" /></label>
                <label>Jusqu'au<input bind:value={editRelForm.until} placeholder="AAAA-MM-JJ" /></label>
                <label>Source<input bind:value={editRelForm.source} /></label>
                <label>Qualité
                  <select bind:value={editRelForm.confidence}>
                    <option value="verified">verified</option>
                    <option value="probable">probable</option>
                    <option value="hypothesis">hypothesis</option>
                  </select>
                </label>
              </div>
              <div class="rel-edit-actions">
                <button class="btn-rel-save" on:click={() => appliquer(r)}>✓ Appliquer</button>
                <button class="btn-rel-cancel" on:click={() => editingRelId = null}>Fermer</button>
              </div>
            </div>
          {:else}
            <span class="rel-type">{v.relation_type}</span>
            <span class="rel-dir">{relDir(r)}</span>
            {#if v.since || v.until}
              <span class="rel-dates">{v.since || '?'}{v.until ? ' → '+v.until : ''}</span>
            {/if}
            <span class="rel-src">{v.source}</span>
            <span class="conf-dot" class:verified={v.confidence === 'verified'} title={v.confidence}></span>
            {#if brouillon.suppr.includes(r.id)}
              <span class="tag-attente">supprimée à l'enregistrement</span>
              <button class="lien-annuler" on:click={() => basculerSuppr(r.id)}>rétablir</button>
            {:else if m}
              <span class="tag-attente">modifiée, à enregistrer</span>
              <button class="lien-annuler" on:click={() => annulerModif(r.id)}>annuler</button>
            {/if}
            {#if !brouillon.suppr.includes(r.id)}
              <div class="rel-row-actions">
                <button class="rel-btn rel-btn-edit" on:click={() => startEditRel(r)} title="Modifier">✏</button>
                <button class="rel-btn rel-btn-del"  on:click={() => basculerSuppr(r.id)} title="Supprimer">✕</button>
              </div>
            {/if}
          {/if}
        </li>
      {/each}
      {#each brouillon.ajouts as a (a.cle)}
        <li class="rel-item a-enregistrer">
          <span class="rel-type">{a.corps.relation_type}</span>
          <span class="rel-dir">{a.corps.direction === 'from' ? '→' : '←'} {a.cible.name} ({a.cible.type})</span>
          {#if a.corps.since || a.corps.until}
            <span class="rel-dates">{a.corps.since || '?'}{a.corps.until ? ' → '+a.corps.until : ''}</span>
          {/if}
          <span class="rel-src">{a.corps.source}</span>
          <span class="conf-dot" class:verified={a.corps.confidence === 'verified'} title={a.corps.confidence}></span>
          <span class="tag-attente">à enregistrer</span>
          <button class="lien-annuler" on:click={() => retirer(a.cle)}>retirer</button>
        </li>
      {/each}
    </ul>
  {/if}

  <!-- Ajouter une relation -->
  <div class="add-rel">
    <h3>Ajouter une relation</h3>
    <div class="add-rel-grid">

      <div class="col2 champ">
        <span>Direction</span>
        <div class="dir-toggle">
          <button class="dir-btn" class:active={newRel.direction==='from'} on:click={() => newRel.direction='from'}>
            Cette entité → cible
          </button>
          <button class="dir-btn" class:active={newRel.direction==='to'} on:click={() => newRel.direction='to'}>
            Cible → cette entité
          </button>
        </div>
      </div>

      <label class="col2 search-wrap">
        Entité cible
        <input bind:value={relSearch} on:input={onRelSearch}
               on:blur={() => setTimeout(() => relSearchOpen=false, 180)}
               placeholder="Rechercher par nom…"
               class:has-target={relTarget !== null} />
        {#if relSearchOpen && relSearchResults.length > 0}
          <ul class="search-dropdown">
            {#each relSearchResults as e (e.id)}
              <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
              <li on:mousedown={() => selectTarget(e)}>
                <span class="sd-type sd-{e.type}">{e.type}</span>
                <span class="sd-name">{e.name}</span>
                {#if e.address}<span class="sd-addr">{e.address}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      </label>

      <label>Type de relation
        <select bind:value={newRel.relation_type}>
          {#each REL_TYPES as t}<option value={t}>{t}</option>{/each}
        </select>
      </label>
      <label>Qualité
        <select bind:value={newRel.confidence}>
          <option value="verified">verified</option>
          <option value="probable">probable</option>
          <option value="hypothesis">hypothesis</option>
        </select>
      </label>
      <label>Depuis<input bind:value={newRel.since} placeholder="AAAA-MM-JJ" /></label>
      <label>Jusqu'au<input bind:value={newRel.until} placeholder="AAAA-MM-JJ" /></label>
      <label class="col2">Source<input bind:value={newRel.source} placeholder="manual, sirene…" /></label>
    </div>

    <button class="btn-add-small" on:click={ajouter} disabled={!relTarget}>
      + Ajouter la relation à la fiche
    </button>
  </div>
</section>

<style>
  .relation-list { list-style: none; display: flex; flex-direction: column; gap: .25rem; }

  .rel-type  { background: #334155; color: #e2e8f0; border-radius: 3px; padding: 1px 6px; font-size: .7rem; white-space: nowrap; }
  .rel-dir   { flex: 1; color: #93c5fd; }
  .rel-dates { color: #94a3b8; font-size: .72rem; white-space: nowrap; }
  .rel-src   { color: #94a3b8; font-size: .7rem; }

  .rel-item { border-bottom: 1px solid #334155; }
  .rel-item:last-child { border-bottom: none; }
  .rel-item:not(.editing) {
    display: flex; align-items: center; gap: .4rem; flex-wrap: wrap;
    padding: .35rem .3rem; font-size: .78rem;
  }
  .rel-item.editing { padding: .55rem; margin: .25rem 0; background: #0f172a; border-radius: 6px; }

  .rel-row-actions { margin-left: auto; display: flex; gap: .2rem; }

  .rel-edit-form { display: flex; flex-direction: column; gap: .4rem; }
  .rel-edit-row  { display: flex; gap: .45rem; flex-wrap: wrap; }
  .rel-edit-row label { flex: 1; min-width: 90px; }

  .add-rel { margin-top: .85rem; padding-top: .85rem; border-top: 1px solid #334155; }
  .add-rel h3 {
    font-size: .72rem; font-weight: 600; color: #94a3b8;
    text-transform: uppercase; letter-spacing: .04em; margin-bottom: .6rem;
  }
  .add-rel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; margin-bottom: .6rem; }
  .champ { display: flex; flex-direction: column; gap: .3rem; font-size: .76rem; color: #94a3b8; }

  .dir-toggle { display: flex; gap: .25rem; }
  .dir-btn {
    flex: 1; padding: .3rem .35rem; border-radius: 4px; border: 1px solid #334155;
    background: transparent; color: #94a3b8; font-size: .72rem; cursor: pointer;
    text-align: center; transition: all .12s;
  }
  .dir-btn.active { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }

  .search-wrap { position: relative; }
  .search-wrap input.has-target { border-color: #166534; color: #4ade80; }

  .search-dropdown {
    position: absolute; top: 100%; left: 0; right: 0; z-index: 200;
    background: #1e293b; border: 1px solid #334155; border-radius: 6px;
    list-style: none; max-height: 200px; overflow-y: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,.5);
  }
  .search-dropdown li {
    display: flex; align-items: center; gap: .4rem;
    padding: .4rem .55rem; cursor: pointer; font-size: .78rem; transition: background .1s;
  }
  .search-dropdown li:hover { background: #334155; }

  .sd-type { font-size: .64rem; padding: 1px 5px; border-radius: 3px; color: #fff; font-weight: 600; white-space: nowrap; }
  .sd-person      { background: #7f1d1d; }
  .sd-business    { background: #1d4ed8; }
  .sd-association { background: #065f46; }
  .sd-place       { background: #4c1d95; }
  .sd-service     { background: #92400e; }
  .sd-name  { flex: 1; color: #e2e8f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sd-addr  { color: #94a3b8; font-size: .7rem; white-space: nowrap; }

  @media (max-width: 640px) {
    .add-rel-grid { grid-template-columns: 1fr; }
  }
</style>
