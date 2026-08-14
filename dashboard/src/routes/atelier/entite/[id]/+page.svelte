<script>
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { goto } from '$app/navigation'
  import { authFetch } from '$lib/stores/auth.js'
  import MapEdit from '$lib/components/MapEdit.svelte'

  const ENTITY_TYPES  = ['person','business','association','place','service','property']
  const CONFIDENCES   = ['verified','probable','hypothesis']
  const VALID_STATUSES = ['draft','unverified','reviewing','verified','published','rejected']
  const CONTACT_TYPES = ['website','phone','email','other']
  const GENDERS       = ['M','F','']

  let entity     = null
  let form       = {}
  let contacts   = []
  let relations  = []
  let audit      = []
  let loading    = true
  let saving     = false
  let dirty      = false
  let error      = ''
  let saveMsg    = ''

  // new contact form
  let newContact = { type: 'website', value: '', label: '' }
  let addingContact = false

  $: entityId = $page.params.id

  onMount(() => load())

  async function load() {
    loading = true
    error = ''
    try {
      const res = await authFetch(`/atelier/entities/${entityId}`)
      if (!res.ok) throw new Error(res.status === 404 ? 'Entité introuvable' : `${res.status}`)
      entity = await res.json()
      initForm()
      await loadBudgetAnnexe()
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  }

  function initForm() {
    // Copie tous les champs éditables
    form = {
      name:        entity.name        ?? '',
      short_name:  entity.short_name  ?? '',
      type:        entity.type        ?? 'business',
      address:     entity.address     ?? '',
      lat:         entity.lat         ?? '',
      lng:         entity.lng         ?? '',
      confidence:  entity.confidence  ?? 'verified',
      validation_status: entity.validation_status ?? 'unverified',
      responsible: entity.responsible ?? '',
      // person
      firstname:   entity.firstname   ?? '',
      lastname:    entity.lastname    ?? '',
      birth_year:  entity.birth_year  ?? '',
      birth_month: entity.birth_month ?? '',
      gender:      entity.gender      ?? '',
      // business
      naf_code:        entity.naf_code        ?? '',
      naf_label:       entity.naf_label       ?? '',
      legal_form:      entity.legal_form      ?? '',
      biz_status:      entity.biz_status      ?? '',
      capital:         entity.capital         ?? '',
      employees_range: entity.employees_range ?? '',
      biz_creation:    entity.biz_creation    ?? '',
      closing_date:    entity.closing_date    ?? '',
      // association
      rna_id:          entity.rna_id          ?? '',
      asso_object:     entity.asso_object      ?? '',
      asso_status:     entity.asso_status     ?? '',
      asso_creation:   entity.asso_creation   ?? '',
      dissolution_date: entity.dissolution_date ?? '',
      // place
      osm_category: entity.osm_category ?? '',
      osm_value:    entity.osm_value    ?? '',
      // service
      svc_category:  entity.svc_category  ?? '',
      operator:      entity.operator      ?? '',
      opening_hours: entity.opening_hours ?? '',
    }
    contacts  = [...(entity.contacts  ?? [])]
    relations = [...(entity.relations ?? [])]
    audit     = [...(entity.audit     ?? [])]
    notes     = [...(entity.notes     ?? [])]
    websites  = [...(entity.websites  ?? [])]
    dirty = false
  }

  function markDirty() { dirty = true; saveMsg = '' }

  async function save() {
    saving = true; saveMsg = ''; error = ''
    try {
      // Verrou optimiste : envoyer updated_at lu au chargement
      const body = { updated_at: entity.updated_at ?? '' }
      for (const [k, v] of Object.entries(form)) {
        body[k] = v === '' ? null : v
      }
      const res = await authFetch(`/atelier/entities/${entityId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
      if (res.status === 409) {
        // Conflit d'édition concurrente
        const d = await res.json()
        error = '⚠ Conflit : ' + (d.detail || 'La fiche a été modifiée par quelqu\'un d\'autre. Rechargez et recommencez.')
        return
      }
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || `${res.status}`)
      }
      const saved = await res.json()
      // Mettre à jour updated_at local pour le prochain save
      if (saved.updated_at) entity = { ...entity, updated_at: saved.updated_at }
      dirty = false
      saveMsg = 'Sauvegardé ✓'
      // Recharge l'audit log
      const r2 = await authFetch(`/atelier/entities/${entityId}`)
      if (r2.ok) { const d = await r2.json(); audit = d.audit ?? [] }
      setTimeout(() => saveMsg = '', 2500)
    } catch (e) {
      error = e.message
    } finally {
      saving = false
    }
  }

  async function addContact() {
    if (!newContact.value.trim()) return
    addingContact = true
    try {
      const res = await authFetch(`/atelier/entities/${entityId}/contacts`, {
        method: 'POST',
        body: JSON.stringify(newContact),
      })
      if (!res.ok) throw new Error(`${res.status}`)
      const c = await res.json()
      contacts = [...contacts, c]
      newContact = { type: 'website', value: '', label: '' }
    } catch (e) {
      error = e.message
    } finally {
      addingContact = false
    }
  }

  async function removeContact(id) {
    const res = await authFetch(`/atelier/contacts/${id}`, { method: 'DELETE' })
    if (res.ok) contacts = contacts.filter(c => c.id !== id)
  }

  function contactIcon(type) {
    return { website: '🌐', phone: '📞', email: '✉️', other: '🔗' }[type] ?? '🔗'
  }

  function relDir(r) {
    return r.from_id === entity?.id
      ? `→ ${r.to_name} (${r.to_type})`
      : `← ${r.from_name} (${r.from_type})`
  }

  // ── Relation editing ───────────────────────────────────────────────────────

  const REL_TYPES = [
    'dirigeant','gérant','associé','président','trésorier','secrétaire','membre',
    'élu_cm','élu_cc','candidat','agent_communal','membre_commission',
    'locataire_commune','bailleur_commune','subventionné','prestataire',
    'famille_présumé','époux_présumé','enfant_présumé','proche_présumé',
    'même_adresse','même_lieu_dit',
  ]

  // ── Budget annexe ──────────────────────────────────────────────────────────
  let budgetAnnexe    = []
  let budgetLoading   = false
  let newBudget       = { year: new Date().getFullYear(), section: 'fonctionnement', sens: 'recette', compte: '', libelle: '', montant: '', source: '' }
  let addingBudget    = false
  let budgetError     = ''

  async function loadBudgetAnnexe() {
    if (!entityId) return
    budgetLoading = true
    try {
      const res = await authFetch(`/budget-annexe?entity_id=${entityId}`)
      if (res.ok) budgetAnnexe = (await res.json()) ?? []
    } catch {} finally { budgetLoading = false }
  }

  async function addBudgetLine() {
    if (!newBudget.libelle || !newBudget.montant || !newBudget.source) return
    addingBudget = true; budgetError = ''
    try {
      const body = { ...newBudget, entity_id: parseInt(entityId), montant: parseFloat(newBudget.montant) }
      const res = await authFetch('/atelier/budget-annexe', { method:'POST', body:JSON.stringify(body) })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || `${res.status}`) }
      const created = await res.json()
      budgetAnnexe = [...budgetAnnexe, created]
      newBudget = { year: new Date().getFullYear(), section: 'fonctionnement', sens: 'recette', compte: '', libelle: '', montant: '', source: '' }
    } catch(e) { budgetError = e.message }
    finally { addingBudget = false }
  }

  async function deleteBudgetLine(id) {
    if (!confirm('Supprimer cette ligne ?')) return
    const res = await authFetch(`/atelier/budget-annexe/${id}`, { method:'DELETE' })
    if (res.ok) budgetAnnexe = budgetAnnexe.filter(b => b.id !== id)
  }

  // ── Coords drag-and-drop ────────────────────────────────────────────────────
  let coordsSaving = false
  let coordsMsg    = ''

  async function saveCoords(lat, lng) {
    coordsSaving = true; coordsMsg = ''
    try {
      const res = await authFetch(`/atelier/entities/${entityId}/coords`, {
        method: 'PATCH',
        body: JSON.stringify({ lat, lng })
      })
      if (!res.ok) throw new Error(`${res.status}`)
      form.lat = lat; form.lng = lng
      coordsMsg = `Position sauvegardée (${lat.toFixed(5)}, ${lng.toFixed(5)})`
      setTimeout(() => coordsMsg = '', 3000)
    } catch(e) { coordsMsg = '⚠ Erreur : ' + e.message }
    finally { coordsSaving = false }
  }

  // ── Relation editing ──────────────────────────────────────────────────────
  let editingRelId = null
  let editRelForm  = {}
  let relSaving    = false
  let relError     = ''
  let newRel = { direction:'from', relation_type:'dirigeant', since:'', until:'', source:'manual', confidence:'verified' }
  let relSearch = ''
  let relSearchResults = []
  let relTarget = null
  let relSearchOpen = false
  let relAdding = false
  let _searchTimer = null

  // ── Notes ─────────────────────────────────────────────────────────────────
  let notes         = []
  let editingNoteId = null
  let editNoteText  = ''
  let editNoteSrc   = ''
  let editNoteConf  = 'verified'
  let newNote       = { note: '', source: 'manual', confidence: 'verified' }
  let noteError     = ''
  let noteSaving    = false

  async function addNote() {
    if (!newNote.note.trim()) return
    noteSaving = true; noteError = ''
    try {
      const res = await authFetch(`/atelier/entities/${entityId}/notes`, {
        method: 'POST', body: JSON.stringify(newNote)
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || res.status) }
      notes = [await res.json(), ...notes]
      newNote = { note: '', source: 'manual', confidence: 'verified' }
    } catch(e) { noteError = e.message }
    finally { noteSaving = false }
  }

  function startEditNote(n) {
    editingNoteId = n.id; editNoteText = n.note; editNoteSrc = n.source; editNoteConf = n.confidence
  }

  async function saveNote(id) {
    noteSaving = true; noteError = ''
    try {
      const res = await authFetch(`/atelier/notes/${id}`, {
        method: 'PUT', body: JSON.stringify({ note: editNoteText, source: editNoteSrc, confidence: editNoteConf })
      })
      if (!res.ok) throw new Error(res.status)
      const updated = await res.json()
      notes = notes.map(n => n.id === id ? updated : n)
      editingNoteId = null
    } catch(e) { noteError = e.message }
    finally { noteSaving = false }
  }

  async function deleteNote(id) {
    if (!confirm('Supprimer cette note ?')) return
    const res = await authFetch(`/atelier/notes/${id}`, { method: 'DELETE' })
    if (res.ok) notes = notes.filter(n => n.id !== id)
  }

  // ── Websites ──────────────────────────────────────────────────────────────
  let websites     = []
  let newWebUrl    = ''
  let webError     = ''
  let webSaving    = false

  async function addWebsite() {
    if (!newWebUrl.trim()) return
    webSaving = true; webError = ''
    try {
      const res = await authFetch(`/atelier/entities/${entityId}/websites`, {
        method: 'POST', body: JSON.stringify({ url: newWebUrl.trim(), found_by: 'manual', score: 1.0 })
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || res.status) }
      websites = [...websites, await res.json()]
      newWebUrl = ''
    } catch(e) { webError = e.message }
    finally { webSaving = false }
  }

  async function setWebStatus(id, status) {
    const res = await authFetch(`/atelier/websites/${id}`, {
      method: 'PATCH', body: JSON.stringify({ status })
    })
    if (res.ok) {
      const updated = await res.json()
      websites = websites.map(w => w.id === id ? updated : w)
    }
  }

  async function deleteWebsite(id) {
    if (!confirm('Supprimer cette URL ?')) return
    const res = await authFetch(`/atelier/websites/${id}`, { method: 'DELETE' })
    if (res.ok) websites = websites.filter(w => w.id !== id)
  }

  function startEditRel(r) {
    editingRelId = r.id
    editRelForm  = { relation_type:r.relation_type, since:r.since??'', until:r.until??'', source:r.source??'manual', confidence:r.confidence??'verified' }
    relError = ''
  }
  function cancelEditRel() { editingRelId = null; relError = '' }

  async function saveRelation(relId) {
    relSaving = true; relError = ''
    try {
      const body = {}
      for (const [k, v] of Object.entries(editRelForm)) body[k] = v === '' ? null : v
      const res = await authFetch(`/atelier/relations/${relId}`, { method:'PUT', body:JSON.stringify(body) })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail||`${res.status}`) }
      const updated = await res.json()
      relations = relations.map(r => r.id === relId ? updated : r)
      editingRelId = null
    } catch(e) { relError = e.message }
    finally { relSaving = false }
  }

  async function deleteRelation(relId) {
    if (!confirm('Supprimer cette relation ?')) return
    const res = await authFetch(`/atelier/relations/${relId}`, { method:'DELETE' })
    if (res.ok) relations = relations.filter(r => r.id !== relId)
  }

  function onRelSearch() {
    clearTimeout(_searchTimer); relTarget = null
    if (relSearch.length < 2) { relSearchResults = []; relSearchOpen = false; return }
    _searchTimer = setTimeout(async () => {
      const r = await authFetch(`/search?q=${encodeURIComponent(relSearch)}&limit=8`)
      if (r.ok) { relSearchResults = await r.json(); relSearchOpen = relSearchResults.length > 0 }
    }, 280)
  }

  function selectTarget(e) { relTarget = e; relSearch = e.name; relSearchOpen = false }

  async function addRelation() {
    if (!relTarget) return
    relAdding = true; relError = ''
    try {
      const body = { direction:newRel.direction, other_entity_id:relTarget.id, relation_type:newRel.relation_type,
                     since:newRel.since||null, until:newRel.until||null, source:newRel.source||'manual', confidence:newRel.confidence }
      const res = await authFetch(`/atelier/entities/${entityId}/relations`, { method:'POST', body:JSON.stringify(body) })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail||`${res.status}`) }
      relations = [...relations, await res.json()]
      newRel = { direction:'from', relation_type:'dirigeant', since:'', until:'', source:'manual', confidence:'verified' }
      relTarget = null; relSearch = ''
    } catch(e) { relError = e.message }
    finally { relAdding = false }
  }
</script>

<svelte:head>
  <title>{entity ? entity.name : 'Éditeur'} — Atelier {COMMUNE}</title>
</svelte:head>

<div class="editor-page">
  <!-- Top bar -->
  <div class="topbar">
    <button class="back-btn" on:click={() => goto('/atelier')}>← File de travail</button>

    {#if entity}
      <div class="topbar-center">
        <span class="entity-id">#{entity.id}</span>
        <span class="entity-name">{entity.name}</span>
        <span class="type-badge type-{entity.type}">{entity.type}</span>
      </div>
    {/if}

    <div class="topbar-actions">
      {#if saveMsg}<span class="save-msg">{saveMsg}</span>{/if}
      {#if error}<span class="save-error">{error}</span>{/if}
      <button class="btn-save" on:click={save} disabled={saving || !dirty}>
        {saving ? 'Sauvegarde...' : 'Sauvegarder'}
      </button>
    </div>
  </div>

  {#if loading}
    <div class="center-msg">Chargement…</div>
  {:else if error && !entity}
    <div class="center-msg error">{error}</div>
  {:else if entity}
    <div class="editor-body">

      <!-- Section : Identité -->
      <section class="card">
        <h2>Identité</h2>
        <div class="grid2">
          <label>
            Nom complet
            <input bind:value={form.name} on:input={markDirty} />
          </label>
          <label>
            Nom court / abrégé
            <input bind:value={form.short_name} on:input={markDirty} placeholder="optionnel" />
          </label>
          <label>
            Type
            <select bind:value={form.type} on:change={markDirty}>
              {#each ENTITY_TYPES as t}<option value={t}>{t}</option>{/each}
            </select>
          </label>
          <label>
            Responsable
            <input bind:value={form.responsible} on:input={markDirty}
                   placeholder="Nom du dirigeant / président" />
          </label>
          <label>
            Qualité source
            <select bind:value={form.confidence} on:change={markDirty}>
              {#each CONFIDENCES as c}
                <option value={c}>
                  {c === 'verified' ? 'verified — source officielle' :
                   c === 'probable' ? 'probable — déduit' : 'hypothesis — supposé'}
                </option>
              {/each}
            </select>
          </label>
          <label>
            Statut de validation
            <select bind:value={form.validation_status} on:change={markDirty}>
              {#each VALID_STATUSES as s}<option value={s}>{s}</option>{/each}
            </select>
          </label>
        </div>
      </section>

      <!-- Section : Localisation -->
      <section class="card">
        <h2>Localisation</h2>
        <div class="grid2">
          <label class="col2">
            Adresse
            <input bind:value={form.address} on:input={markDirty} />
          </label>
          <label>
            Latitude
            <input type="number" step="0.000001" bind:value={form.lat} on:input={markDirty}
                   placeholder="44.04..." />
          </label>
          <label>
            Longitude
            <input type="number" step="0.000001" bind:value={form.lng} on:input={markDirty}
                   placeholder="3.86..." />
          </label>
        </div>
        {#if form.lat && form.lng}
          <div class="coords-actions">
            <span class="coords-current">{(+form.lat).toFixed(5)}, {(+form.lng).toFixed(5)}</span>
            <a class="coords-osm-link" target="_blank" rel="noopener"
               href={`https://www.openstreetmap.org/?mlat=${form.lat}&mlon=${form.lng}#map=17/${form.lat}/${form.lng}`}>
              Voir sur OSM ↗
            </a>
          </div>
        {:else}
          <p class="muted coords-hint">Aucune coordonnée. Saisir lat/lng ci-dessus ou cliquer sur la carte.</p>
        {/if}
        {#if coordsMsg}<p class="coords-msg" class:err={coordsMsg.startsWith('⚠')}>{coordsMsg}</p>{/if}
        <MapEdit
          lat={form.lat ? +form.lat : null}
          lng={form.lng ? +form.lng : null}
          entityName={entity?.name}
          on:coords={e => saveCoords(e.detail.lat, e.detail.lng)}
        />
      </section>

      <!-- Section : Budget annexe -->
      <section class="card">
        <h2>Budget annexe</h2>
        {#if budgetLoading}
          <p class="muted">Chargement…</p>
        {:else if budgetAnnexe.length > 0}
          <table class="budget-table">
            <thead>
              <tr><th>Année</th><th>Section</th><th>Sens</th><th>Compte</th><th>Libellé</th><th class="num">Montant (€)</th><th>Source</th><th></th></tr>
            </thead>
            <tbody>
              {#each budgetAnnexe as b (b.id)}
                <tr class="budget-row sens-{b.sens}">
                  <td>{b.year}</td>
                  <td><span class="section-badge sec-{b.section}">{b.section}</span></td>
                  <td><span class="sens-badge sens-{b.sens}">{b.sens}</span></td>
                  <td class="muted">{b.compte ?? '—'}</td>
                  <td>{b.libelle}</td>
                  <td class="num" class:neg={b.montant < 0}>{b.montant.toLocaleString('fr-FR', {minimumFractionDigits:2})} €</td>
                  <td class="muted small">{b.source}</td>
                  <td><button class="icon-del" on:click={() => deleteBudgetLine(b.id)}>✕</button></td>
                </tr>
              {/each}
            </tbody>
          </table>
        {:else}
          <p class="muted">Aucune ligne de budget annexe.</p>
        {/if}

        {#if budgetError}<p class="rel-error">{budgetError}</p>{/if}

        <details class="add-budget">
          <summary>+ Ajouter une ligne</summary>
          <div class="budget-add-grid">
            <label>Année<input type="number" bind:value={newBudget.year} min="2015" max="2035" /></label>
            <label>Section
              <select bind:value={newBudget.section}>
                <option value="fonctionnement">fonctionnement</option>
                <option value="investissement">investissement</option>
                <option value="dette">dette</option>
              </select>
            </label>
            <label>Sens
              <select bind:value={newBudget.sens}>
                <option value="recette">recette</option>
                <option value="depense">dépense</option>
                <option value="solde">solde</option>
              </select>
            </label>
            <label>Compte M57<input bind:value={newBudget.compte} placeholder="64, 74…" /></label>
            <label class="col2">Libellé<input bind:value={newBudget.libelle} placeholder="Charges de personnel…" /></label>
            <label>Montant (€)<input type="number" step="0.01" bind:value={newBudget.montant} placeholder="44000.00" /></label>
            <label class="col2">Source<input bind:value={newBudget.source} placeholder="CM 27/04/2026, DGFiP…" /></label>
            <div class="col2">
              <button class="btn-add" on:click={addBudgetLine} disabled={addingBudget || !newBudget.libelle || !newBudget.montant}>
                {addingBudget ? 'Ajout…' : '+ Ajouter'}
              </button>
            </div>
          </div>
        </details>
      </section>

      <!-- Section : Contacts -->
      <section class="card">
        <h2>Contacts</h2>
        {#if contacts.length > 0}
          <ul class="contact-list">
            {#each contacts as c (c.id)}
              <li>
                <span class="contact-icon">{contactIcon(c.type)}</span>
                <span class="contact-type">{c.type}</span>
                {#if c.type === 'website'}
                  <a href={c.value} target="_blank" rel="noopener" class="contact-value">{c.value}</a>
                {:else}
                  <span class="contact-value">{c.value}</span>
                {/if}
                {#if c.label}<span class="contact-label">{c.label}</span>{/if}
                <button class="contact-del" on:click={() => removeContact(c.id)}>✕</button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">Aucun contact renseigné.</p>
        {/if}

        <div class="add-contact">
          <select bind:value={newContact.type}>
            {#each CONTACT_TYPES as t}<option value={t}>{t}</option>{/each}
          </select>
          <input bind:value={newContact.value} placeholder="Valeur (URL, numéro, email…)" />
          <input bind:value={newContact.label} placeholder="Étiquette (optionnel)" class="label-input" />
          <button class="btn-add" on:click={addContact} disabled={addingContact || !newContact.value.trim()}>
            {addingContact ? '…' : '+ Ajouter'}
          </button>
        </div>
      </section>

      <!-- Section : Champs type-spécifiques -->
      {#if form.type === 'person'}
        <section class="card">
          <h2>Personne</h2>
          <div class="grid2">
            <label>Prénom<input bind:value={form.firstname} on:input={markDirty} /></label>
            <label>Nom de famille<input bind:value={form.lastname} on:input={markDirty} /></label>
            <label>Année de naissance<input type="number" bind:value={form.birth_year} on:input={markDirty} placeholder="1970" /></label>
            <label>Mois de naissance<input type="number" min="1" max="12" bind:value={form.birth_month} on:input={markDirty} /></label>
            <label>
              Genre
              <select bind:value={form.gender} on:change={markDirty}>
                <option value="">—</option>
                <option value="M">Masculin</option>
                <option value="F">Féminin</option>
              </select>
            </label>
          </div>
        </section>

      {:else if form.type === 'business'}
        <section class="card">
          <h2>Entreprise</h2>
          <div class="grid2">
            <label>Code NAF<input bind:value={form.naf_code} on:input={markDirty} placeholder="ex: 6820B" /></label>
            <label>Libellé NAF<input bind:value={form.naf_label} on:input={markDirty} /></label>
            <label>Forme juridique<input bind:value={form.legal_form} on:input={markDirty} /></label>
            <label>
              Statut
              <select bind:value={form.biz_status} on:change={markDirty}>
                <option value="">—</option>
                <option value="A">Actif (A)</option>
                <option value="F">Fermé (F)</option>
              </select>
            </label>
            <label>Capital (€)<input type="number" bind:value={form.capital} on:input={markDirty} /></label>
            <label>Tranche effectif<input bind:value={form.employees_range} on:input={markDirty} placeholder="ex: 1-2" /></label>
            <label>Date création<input bind:value={form.biz_creation} on:input={markDirty} placeholder="AAAA-MM-JJ" /></label>
            <label>Date fermeture<input bind:value={form.closing_date} on:input={markDirty} placeholder="AAAA-MM-JJ" /></label>
          </div>
        </section>

      {:else if form.type === 'association'}
        <section class="card">
          <h2>Association</h2>
          <div class="grid2">
            <label>N° RNA<input bind:value={form.rna_id} on:input={markDirty} placeholder="W30..." /></label>
            <label>
              Statut
              <select bind:value={form.asso_status} on:change={markDirty}>
                <option value="">—</option>
                <option value="A">Active</option>
                <option value="D">Dissoute</option>
              </select>
            </label>
            <label class="col2">
              Objet social
              <textarea bind:value={form.asso_object} on:input={markDirty} rows="3"></textarea>
            </label>
            <label>Date création<input bind:value={form.asso_creation} on:input={markDirty} placeholder="AAAA-MM-JJ" /></label>
            <label>Date dissolution<input bind:value={form.dissolution_date} on:input={markDirty} placeholder="AAAA-MM-JJ" /></label>
          </div>
        </section>

      {:else if form.type === 'place'}
        <section class="card">
          <h2>Lieu</h2>
          <div class="grid2">
            <label>Catégorie OSM<input bind:value={form.osm_category} on:input={markDirty} placeholder="ex: amenity" /></label>
            <label>Valeur OSM<input bind:value={form.osm_value} on:input={markDirty} placeholder="ex: restaurant" /></label>
          </div>
        </section>

      {:else if form.type === 'service'}
        <section class="card">
          <h2>Service public</h2>
          <div class="grid2">
            <label>Catégorie<input bind:value={form.svc_category} on:input={markDirty} placeholder="santé, éducation…" /></label>
            <label>Opérateur<input bind:value={form.operator} on:input={markDirty} /></label>
            <label class="col2">Horaires<input bind:value={form.opening_hours} on:input={markDirty} placeholder="Mo-Fr 09:00-17:00" /></label>
          </div>
        </section>
      {/if}

      <!-- Section : Relations -->
      <section class="card">
        <h2>Relations <span class="count-badge">{relations.length}</span></h2>

        {#if relError}
          <p class="rel-error">{relError}</p>
        {/if}

        {#if relations.length === 0}
          <p class="muted">Aucune relation connue.</p>
        {:else}
          <ul class="relation-list">
            {#each relations as r (r.id)}
              <li class="rel-item" class:editing={editingRelId === r.id}>
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
                      <button class="btn-rel-save" on:click={() => saveRelation(r.id)} disabled={relSaving}>
                        {relSaving ? '…' : '✓ Sauvegarder'}
                      </button>
                      <button class="btn-rel-cancel" on:click={cancelEditRel}>Annuler</button>
                    </div>
                  </div>
                {:else}
                  <span class="rel-type">{r.relation_type}</span>
                  <span class="rel-dir">{relDir(r)}</span>
                  {#if r.since || r.until}
                    <span class="rel-dates">{r.since ?? '?'}{r.until ? ' → '+r.until : ''}</span>
                  {/if}
                  <span class="rel-src">{r.source}</span>
                  <span class="conf-dot" class:verified={r.confidence === 'verified'} title={r.confidence}></span>
                  <div class="rel-row-actions">
                    <button class="rel-btn rel-btn-edit" on:click={() => startEditRel(r)} title="Modifier">✏</button>
                    <button class="rel-btn rel-btn-del"  on:click={() => deleteRelation(r.id)} title="Supprimer">✕</button>
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}

        <!-- Ajouter une relation -->
        <div class="add-rel">
          <h3>Ajouter une relation</h3>
          <div class="add-rel-grid">

            <label class="col2">
              Direction
              <div class="dir-toggle">
                <button class="dir-btn" class:active={newRel.direction==='from'} on:click={() => newRel.direction='from'}>
                  Cette entité → cible
                </button>
                <button class="dir-btn" class:active={newRel.direction==='to'} on:click={() => newRel.direction='to'}>
                  Cible → cette entité
                </button>
              </div>
            </label>

            <label class="col2 search-wrap">
              Entité cible
              <input bind:value={relSearch} on:input={onRelSearch}
                     on:blur={() => setTimeout(() => relSearchOpen=false, 180)}
                     placeholder="Rechercher par nom…"
                     class:has-target={relTarget !== null} />
              {#if relSearchOpen && relSearchResults.length > 0}
                <ul class="search-dropdown">
                  {#each relSearchResults as e (e.id)}
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

          <button class="btn-add-rel" on:click={addRelation} disabled={relAdding || !relTarget}>
            {relAdding ? 'Ajout…' : '+ Ajouter la relation'}
          </button>
        </div>
      </section>

      <!-- Section : Websites -->
      <section class="card">
        <h2>Sites web <span class="count-badge">{websites.length}</span></h2>
        {#if webError}<p class="rel-error">{webError}</p>{/if}

        {#if websites.length > 0}
          <ul class="web-list">
            {#each websites as w (w.id)}
              <li class="web-item" class:validated={w.status==='validated'} class:rejected={w.status==='rejected'}>
                <span class="web-status-dot web-{w.status}" title={w.status}></span>
                <a href={w.url} target="_blank" rel="noopener" class="web-url">{w.url}</a>
                <span class="web-meta">{w.found_by} {w.score != null ? `(${w.score.toFixed(2)})` : ''}</span>
                <div class="web-actions">
                  {#if w.status !== 'validated'}
                    <button class="web-btn web-validate" on:click={() => setWebStatus(w.id,'validated')} title="Valider">✓</button>
                  {/if}
                  {#if w.status !== 'rejected'}
                    <button class="web-btn web-reject"   on:click={() => setWebStatus(w.id,'rejected')}  title="Rejeter">✕</button>
                  {/if}
                  <button class="web-btn web-del" on:click={() => deleteWebsite(w.id)} title="Supprimer">🗑</button>
                </div>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">Aucune URL connue.</p>
        {/if}

        <div class="add-web">
          <input bind:value={newWebUrl} placeholder="https://…" class="web-input" />
          <button class="btn-add-small" on:click={addWebsite} disabled={webSaving || !newWebUrl.trim()}>
            {webSaving ? '…' : '+ Ajouter'}
          </button>
        </div>
      </section>

      <!-- Section : Notes -->
      <section class="card">
        <h2>Notes <span class="count-badge">{notes.length}</span></h2>
        {#if noteError}<p class="rel-error">{noteError}</p>{/if}

        {#if notes.length > 0}
          <ul class="note-list">
            {#each notes as n (n.id)}
              <li class="note-item">
                {#if editingNoteId === n.id}
                  <div class="note-edit">
                    <textarea bind:value={editNoteText} rows="3"></textarea>
                    <div class="note-edit-meta">
                      <input bind:value={editNoteSrc} placeholder="source" />
                      <select bind:value={editNoteConf}>
                        <option value="verified">verified</option>
                        <option value="probable">probable</option>
                        <option value="hypothesis">hypothesis</option>
                        <option value="unverified">unverified</option>
                      </select>
                    </div>
                    <div class="rel-edit-actions">
                      <button class="btn-rel-save" on:click={() => saveNote(n.id)} disabled={noteSaving}>✓ Sauvegarder</button>
                      <button class="btn-rel-cancel" on:click={() => editingNoteId=null}>Annuler</button>
                    </div>
                  </div>
                {:else}
                  <div class="note-body">
                    <span class="note-date">{n.date ?? ''}</span>
                    <span class="conf-dot" class:verified={n.confidence==='verified'} title={n.confidence}></span>
                    <span class="note-src muted">{n.source}</span>
                    <p class="note-text">{n.note}</p>
                  </div>
                  <div class="note-actions">
                    <button class="rel-btn rel-btn-edit" on:click={() => startEditNote(n)} title="Modifier">✏</button>
                    <button class="rel-btn rel-btn-del"  on:click={() => deleteNote(n.id)} title="Supprimer">✕</button>
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">Aucune note.</p>
        {/if}

        <div class="add-note">
          <textarea bind:value={newNote.note} rows="2" placeholder="Nouvelle note…"></textarea>
          <div class="add-note-meta">
            <input bind:value={newNote.source} placeholder="source" />
            <select bind:value={newNote.confidence}>
              <option value="verified">verified</option>
              <option value="probable">probable</option>
              <option value="hypothesis">hypothesis</option>
              <option value="unverified">unverified</option>
            </select>
            <button class="btn-add-small" on:click={addNote} disabled={noteSaving || !newNote.note.trim()}>
              {noteSaving ? '…' : '+ Ajouter'}
            </button>
          </div>
        </div>
      </section>

      <!-- Section : Historique -->
      <section class="card">
        <h2>Historique des modifications</h2>
        {#if audit.length === 0}
          <p class="muted">Aucune modification enregistrée.</p>
        {:else}
          <table class="audit-table">
            <thead>
              <tr><th>Date</th><th>Utilisateur</th><th>Champ</th><th>Avant</th><th>Après</th></tr>
            </thead>
            <tbody>
              {#each audit as a}
                <tr>
                  <td>{a.at?.slice(0,16).replace('T',' ') ?? '—'}</td>
                  <td>{a.user_email ?? '—'}</td>
                  <td>{a.field ?? a.action}</td>
                  <td class="old-val">{a.old_value ?? '—'}</td>
                  <td class="new-val">{a.new_value ?? '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </section>

    </div>
  {/if}
</div>

<style>
  .editor-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ── Top bar ── */
  .topbar {
    display: flex;
    align-items: center;
    gap: .75rem;
    padding: .55rem 1rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .back-btn {
    font-size: .78rem;
    color: #60a5fa;
    cursor: pointer;
    white-space: nowrap;
  }
  .back-btn:hover { text-decoration: underline; }

  .topbar-center {
    display: flex;
    align-items: center;
    gap: .5rem;
    flex: 1;
    min-width: 0;
  }

  .entity-id  { font-size: .72rem; color: #64748b; }
  .entity-name { font-weight: 600; color: #e2e8f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .topbar-actions { display: flex; align-items: center; gap: .5rem; margin-left: auto; }

  .save-msg   { font-size: .78rem; color: #4ade80; }
  .save-error { font-size: .78rem; color: #f87171; }

  .btn-save {
    padding: .38rem .9rem;
    background: #2563eb;
    color: #fff;
    border-radius: 6px;
    font-size: .8rem;
    font-weight: 600;
    cursor: pointer;
    transition: background .12s;
  }
  .btn-save:hover:not(:disabled) { background: #1d4ed8; }
  .btn-save:disabled { opacity: .45; cursor: default; }

  /* ── Body ── */
  .editor-body {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }

  .center-msg {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #64748b;
    font-size: .9rem;
  }
  .center-msg.error { color: #f87171; }

  /* ── Cards ── */
  .card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 1rem;
  }

  .card h2 {
    font-size: .82rem;
    font-weight: 700;
    color: #93c5fd;
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: .75rem;
    display: flex;
    align-items: center;
    gap: .4rem;
  }

  .count-badge {
    background: #334155;
    color: #94a3b8;
    border-radius: 999px;
    padding: 0 6px;
    font-size: .7rem;
  }

  /* ── Form grid ── */
  .grid2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: .65rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: .3rem;
    font-size: .76rem;
    color: #94a3b8;
  }

  .col2 { grid-column: 1 / -1; }

  input, select, textarea {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 5px;
    color: #e2e8f0;
    padding: .42rem .55rem;
    font-size: .82rem;
    font-family: inherit;
    transition: border-color .12s;
  }
  input:focus, select:focus, textarea:focus { outline: none; border-color: #3b82f6; }

  textarea { resize: vertical; min-height: 70px; }

  /* ── Type badge (topbar) ── */
  .type-badge {
    font-size: .68rem;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 600;
    color: #fff;
  }
  .type-person      { background: #7f1d1d; }
  .type-business    { background: #1d4ed8; }
  .type-association { background: #065f46; }
  .type-place       { background: #4c1d95; }
  .type-service     { background: #92400e; }
  .type-property    { background: #334155; }

  /* ── Contacts ── */
  .contact-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: .3rem;
    margin-bottom: .75rem;
  }

  .contact-list li {
    display: flex;
    align-items: center;
    gap: .45rem;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 5px;
    padding: .38rem .6rem;
    font-size: .8rem;
  }

  .contact-icon { font-size: .9rem; }
  .contact-type { color: #64748b; font-size: .72rem; min-width: 52px; }
  .contact-value { flex: 1; color: #93c5fd; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .contact-value:is(a):hover { text-decoration: underline; }
  .contact-label { color: #64748b; font-size: .72rem; }
  .contact-del { margin-left: auto; color: #ef4444; font-size: .78rem; cursor: pointer; padding: 0 .2rem; }
  .contact-del:hover { color: #fca5a5; }

  .add-contact {
    display: flex;
    gap: .4rem;
    flex-wrap: wrap;
  }
  .add-contact select { width: 100px; }
  .add-contact input  { flex: 1; min-width: 120px; }
  .add-contact .label-input { max-width: 130px; }

  .btn-add {
    padding: .4rem .75rem;
    background: #1d4ed8;
    color: #fff;
    border-radius: 5px;
    font-size: .78rem;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn-add:disabled { opacity: .45; cursor: default; }

  /* ── Relations ── */
  .relation-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: .25rem;
  }

  .relation-list li {
    display: flex;
    align-items: center;
    gap: .5rem;
    font-size: .78rem;
    padding: .3rem 0;
    border-bottom: 1px solid #1e293b;
  }

  .rel-type  { background: #334155; color: #e2e8f0; border-radius: 3px; padding: 1px 6px; font-size: .7rem; white-space: nowrap; }
  .rel-dir   { flex: 1; color: #93c5fd; }
  .rel-dates { color: #64748b; font-size: .72rem; white-space: nowrap; }
  .rel-src   { color: #475569; font-size: .7rem; }

  .conf-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #475569;
    flex-shrink: 0;
  }
  .conf-dot.verified { background: #4ade80; }

  .small { font-size: .72rem; margin-top: .4rem; }

  /* ── Audit table ── */
  .audit-table {
    width: 100%;
    border-collapse: collapse;
    font-size: .76rem;
  }

  .audit-table th {
    text-align: left;
    padding: .3rem .5rem;
    color: #64748b;
    font-weight: 600;
    font-size: .7rem;
    text-transform: uppercase;
    letter-spacing: .04em;
    border-bottom: 1px solid #334155;
  }

  .audit-table td {
    padding: .32rem .5rem;
    color: #94a3b8;
    border-bottom: 1px solid #1e293b;
    vertical-align: top;
  }

  .old-val { color: #f87171; text-decoration: line-through; }
  .new-val { color: #4ade80; }

  .muted {
    color: #64748b;
    font-size: .8rem;
  }

  @media (max-width: 640px) {
    .grid2 { grid-template-columns: 1fr; }
    .col2  { grid-column: 1; }
  }

  /* ── Relations — édition ── */
  .rel-error {
    color: #f87171; font-size: .78rem; margin-bottom: .5rem;
    background: #450a0a; border: 1px solid #7f1d1d; border-radius: 4px; padding: .35rem .55rem;
  }

  .rel-item { border-bottom: 1px solid #1e293b; }
  .rel-item:last-child { border-bottom: none; }
  .rel-item:not(.editing) {
    display: flex; align-items: center; gap: .4rem;
    padding: .35rem 0; font-size: .78rem;
  }
  .rel-item.editing { padding: .55rem; margin: .25rem 0; background: #0f172a; border-radius: 6px; }

  .rel-row-actions { margin-left: auto; display: flex; gap: .2rem; }
  .rel-btn {
    width: 22px; height: 22px; border-radius: 3px; border: 1px solid #334155;
    font-size: .7rem; cursor: pointer; display: flex; align-items: center; justify-content: center;
    background: transparent; transition: all .12s;
  }
  .rel-btn-edit { color: #93c5fd; }
  .rel-btn-edit:hover { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
  .rel-btn-del  { color: #f87171; }
  .rel-btn-del:hover  { background: #7f1d1d; border-color: #7f1d1d; color: #fff; }

  .rel-edit-form { display: flex; flex-direction: column; gap: .4rem; }
  .rel-edit-row  { display: flex; gap: .45rem; flex-wrap: wrap; }
  .rel-edit-row label { flex: 1; min-width: 90px; }
  .rel-edit-actions { display: flex; gap: .35rem; padding-top: .2rem; }

  .btn-rel-save {
    padding: .3rem .65rem; background: #166534; color: #4ade80;
    border: 1px solid #166534; border-radius: 5px; font-size: .75rem; font-weight: 600; cursor: pointer;
  }
  .btn-rel-save:disabled { opacity:.45; cursor:default; }
  .btn-rel-save:hover:not(:disabled) { background: #15803d; }

  .btn-rel-cancel {
    padding: .3rem .65rem; background: transparent; color: #94a3b8;
    border: 1px solid #334155; border-radius: 5px; font-size: .75rem; cursor: pointer;
  }
  .btn-rel-cancel:hover { border-color: #475569; color: #e2e8f0; }

  /* ── Add relation form ── */
  .add-rel {
    margin-top: .85rem; padding-top: .85rem; border-top: 1px solid #334155;
  }
  .add-rel h3 {
    font-size: .72rem; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: .04em; margin-bottom: .6rem;
  }
  .add-rel-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; margin-bottom: .6rem;
  }

  .dir-toggle { display: flex; gap: .25rem; margin-top: .25rem; }
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
  .sd-addr  { color: #64748b; font-size: .7rem; white-space: nowrap; }

  .btn-add-rel {
    padding: .4rem .9rem; background: #1d4ed8; color: #fff;
    border: none; border-radius: 6px; font-size: .8rem; font-weight: 600; cursor: pointer;
    transition: background .12s;
  }
  .btn-add-rel:hover:not(:disabled) { background: #1e40af; }
  .btn-add-rel:disabled { opacity: .45; cursor: default; }

  /* ── Localisation coords ── */
  .coords-actions { display: flex; align-items: center; gap: .75rem; margin-top: .5rem; font-size: .78rem; }
  .coords-current { color: #64748b; }
  .coords-osm-link { color: #60a5fa; }
  .coords-hint { font-size: .75rem; }
  .coords-msg { font-size: .78rem; color: #4ade80; margin-top: .4rem; }
  .coords-msg.err { color: #f87171; }

  /* ── Budget annexe ── */
  .budget-table {
    width: 100%; border-collapse: collapse; font-size: .78rem;
    margin-bottom: .75rem;
  }
  .budget-table th {
    text-align: left; color: #64748b; font-weight: 600;
    border-bottom: 1px solid #334155; padding: .3rem .4rem;
  }
  .budget-table td { padding: .28rem .4rem; border-bottom: 1px solid #1e293b; }
  .budget-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .budget-table .neg { color: #f87171; }
  .budget-table .small { font-size: .7rem; }

  .section-badge {
    font-size: .68rem; padding: 1px 5px; border-radius: 3px; font-weight: 600;
  }
  .sec-fonctionnement { background: #1e3a5f; color: #93c5fd; }
  .sec-investissement { background: #1a3a1a; color: #4ade80; }
  .sec-dette          { background: #3a1a1a; color: #fca5a5; }

  .sens-badge {
    font-size: .68rem; padding: 1px 5px; border-radius: 3px; font-weight: 600;
  }
  .sens-recette { background: #14532d; color: #86efac; }
  .sens-depense { background: #7f1d1d; color: #fca5a5; }
  .sens-solde   { background: #44403c; color: #d4d4aa; }

  .add-budget summary {
    cursor: pointer; color: #60a5fa; font-size: .8rem; font-weight: 600;
    padding: .4rem 0; list-style: none; user-select: none;
  }
  .add-budget summary::-webkit-details-marker { display: none; }
  .budget-add-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: .5rem .75rem;
    margin-top: .6rem;
  }
  .budget-add-grid label { display: flex; flex-direction: column; gap: .2rem; font-size: .78rem; color: #94a3b8; }
  .budget-add-grid input, .budget-add-grid select {
    background: #0f172a; border: 1px solid #334155; color: #e2e8f0;
    border-radius: 5px; padding: .28rem .5rem; font-size: .78rem;
  }
  .icon-del {
    background: none; border: none; color: #ef4444; cursor: pointer;
    font-size: .8rem; padding: 2px 4px;
  }
  .icon-del:hover { color: #f87171; }

  /* ── Websites ── */
  .web-list { list-style: none; display: flex; flex-direction: column; gap: .35rem; margin-bottom: .6rem; }
  .web-item { display: flex; align-items: center; gap: .5rem; font-size: .78rem; padding: .3rem .4rem; border-radius: 5px; background: #0f172a; }
  .web-item.validated { border-left: 3px solid #22c55e; }
  .web-item.rejected  { opacity: .45; }
  .web-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .web-candidate  { background: #f59e0b; }
  .web-validated  { background: #22c55e; }
  .web-rejected   { background: #64748b; }
  .web-broken     { background: #ef4444; }
  .web-url { color: #60a5fa; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .web-url:hover { text-decoration: underline; }
  .web-meta { color: #64748b; font-size: .7rem; white-space: nowrap; }
  .web-actions { display: flex; gap: .2rem; margin-left: auto; flex-shrink: 0; }
  .web-btn { background: none; border: none; cursor: pointer; font-size: .8rem; padding: 2px 5px; border-radius: 3px; }
  .web-validate { color: #22c55e; } .web-validate:hover { background: #14532d44; }
  .web-reject   { color: #f87171; } .web-reject:hover   { background: #7f1d1d44; }
  .web-del      { color: #64748b; } .web-del:hover      { color: #ef4444; }
  .add-web { display: flex; gap: .4rem; margin-top: .4rem; }
  .web-input { flex: 1; }

  /* ── Notes ── */
  .note-list { list-style: none; display: flex; flex-direction: column; gap: .5rem; margin-bottom: .6rem; }
  .note-item { display: flex; align-items: flex-start; gap: .4rem; padding: .45rem .5rem; background: #0f172a; border-radius: 5px; }
  .note-body { flex: 1; min-width: 0; }
  .note-date { font-size: .7rem; color: #64748b; margin-right: .3rem; }
  .note-src  { font-size: .7rem; margin-left: .3rem; }
  .note-text { margin: .25rem 0 0; font-size: .8rem; color: #cbd5e1; white-space: pre-wrap; word-break: break-word; }
  .note-actions { display: flex; flex-direction: column; gap: .2rem; flex-shrink: 0; }
  .note-edit { flex: 1; display: flex; flex-direction: column; gap: .35rem; }
  .note-edit textarea { width: 100%; }
  .note-edit-meta { display: flex; gap: .4rem; }
  .note-edit-meta input  { flex: 1; }
  .note-edit-meta select { width: 110px; }
  .add-note { display: flex; flex-direction: column; gap: .4rem; margin-top: .4rem; }
  .add-note textarea { width: 100%; resize: vertical; }
  .add-note-meta { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
  .add-note-meta input  { flex: 1; min-width: 80px; }
  .add-note-meta select { width: 110px; }
  .btn-add-small {
    padding: .35rem .7rem; background: #1d4ed8; color: #fff;
    border: none; border-radius: 5px; font-size: .78rem; font-weight: 600;
    cursor: pointer; white-space: nowrap;
  }
  .btn-add-small:hover:not(:disabled) { background: #1e40af; }
  .btn-add-small:disabled { opacity: .45; cursor: default; }
</style>
