<script>
  import { COMMUNE } from '$lib/instance.js'
  import { onMount, tick } from 'svelte'
  import { page } from '$app/stores'
  import { goto, beforeNavigate } from '$app/navigation'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'
  import { LIBELLES } from '$lib/champs.js'
  import { VERDICT } from '$lib/axes.js'
  import { brouillonVide, resumer, parOnglet, enumerer } from './brouillon.js'
  import BarreEnregistrement from './BarreEnregistrement.svelte'
  import Conflit from './Conflit.svelte'
  import Identite from './Identite.svelte'
  import ChampsDuType from './ChampsDuType.svelte'
  import Adresse from './Adresse.svelte'
  import Carte from './Carte.svelte'
  import Budget from './Budget.svelte'
  import Relations from './Relations.svelte'
  import Contacts from './Contacts.svelte'
  import Sites from './Sites.svelte'
  import Notes from './Notes.svelte'
  import Historique from './Historique.svelte'

  const ONGLETS = [
    { cle: 'essentiel',  titre: "L'essentiel" },
    { cle: 'liens',      titre: 'Les liens' },
    { cle: 'historique', titre: 'Historique et notes' },
  ]
  let onglet = 'essentiel'
  let corps                // la zone qui défile : remise en haut à chaque onglet

  function ouvrir(cle) { onglet = cle; if (corps) corps.scrollTop = 0 }

  let entity     = null
  let form       = {}
  let initial    = {}      // le formulaire tel que lu : ce qu'on compare pour savoir ce qui a changé
  let contacts   = []
  let relations  = []
  let audit      = []
  let notes      = []
  let websites   = []
  let loading    = true
  let error      = ''
  // Fiabilité, statut, verdict sur un site : trancher, réservé au validateur.
  $: tranche = auMoins($currentUser, 'validator')
  let conflit    = null    // détail d'un 409 : { message, par, le, champs, updated_at }

  // Tout ce qui n'est pas encore envoyé, hors champs du formulaire (brouillon.js).
  let brouillon      = brouillonVide()
  let enregistrement = false
  let bilan          = []  // [{ ok, texte }] du dernier enregistrement
  let carteVersion   = 0

  // Champs du formulaire que le PATCH de la fiche n'envoie pas : le type ne
  // change pas ici, les coordonnées ont leur propre appel.
  const NON_ENVOYES = new Set(['type', 'lat', 'lng'])

  // Ce que l'éditeur a réellement changé. On n'envoie QUE cela : renvoyer toute
  // la fiche réécrivait aussi les champs qu'un autre venait de corriger.
  $: modifies = Object.keys(form).filter(k =>
    !NON_ENVOYES.has(k) && String(form[k] ?? '') !== String(initial[k] ?? ''))

  // Le point déplacé (carte ou saisie) : seulement s'il est complet, l'API
  // n'accepte pas de coordonnées vides.
  $: coordsModifiees = coordsValides(form)
    && (String(form.lat) !== String(initial.lat ?? '') || String(form.lng) !== String(initial.lng ?? ''))

  $: aEnregistrer = resumer(modifies, coordsModifiees, brouillon)
  $: enAttente    = parOnglet(modifies, coordsModifiees, brouillon)

  function coordsValides(f) {
    return [f.lat, f.lng].every(v => v !== '' && v != null && !isNaN(+v))
  }

  beforeNavigate(({ cancel, type }) => {
    if (!aEnregistrer.length) return
    // Fermeture d'onglet ou lien externe : le navigateur pose lui-même la question.
    if (type === 'leave') { cancel(); return }
    if (!confirm('Des modifications ne sont pas enregistrées. Quitter la fiche quand même ?')) cancel()
  })

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
    form = formDepuis(entity)
    initial = { ...form }
    listesDepuis(entity)
    conflit = null
    carteVersion++
  }

  function listesDepuis(e) {
    contacts  = [...(e.contacts  ?? [])]
    relations = [...(e.relations ?? [])]
    audit     = [...(e.audit     ?? [])]
    notes     = [...(e.notes     ?? [])]
    websites  = [...(e.websites  ?? [])]
  }

  function formDepuis(entity) {
    // Copie tous les champs éditables
    return {
      name:        entity.name        ?? '',
      short_name:  entity.short_name  ?? '',
      type:        entity.type        ?? 'business',
      address:     entity.address     ?? '',
      lat:         entity.lat         ?? '',
      lng:         entity.lng         ?? '',
      confidence:  entity.confidence  ?? 'verified',
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
  }

  // ── Budget annexe (lu à part : ce n'est pas dans la fiche) ────────────────
  let budgetAnnexe  = []
  let budgetLoading = false

  async function loadBudgetAnnexe() {
    if (!entityId) return
    budgetLoading = true
    try {
      const res = await authFetch(`/budget-annexe?entity_id=${entityId}`)
      if (res.ok) budgetAnnexe = (await res.json()) ?? []
    } catch {} finally { budgetLoading = false }
  }

  // ── Enregistrer : un seul bouton, qui envoie tout le brouillon ────────────
  // Chaque changement part par son propre appel, comme avant ; ce qui réussit
  // sort du brouillon, ce qui échoue y reste, avec la raison dans le bilan.

  function noter(ok, texte) { bilan = [...bilan, { ok, texte }] }

  async function echec(res) {
    let d = {}
    try { d = await res.json() } catch {}
    const msg = typeof d.detail === 'object' ? d.detail?.message : d.detail
    return new Error(msg || `${res.status}`)
  }

  // Un appel du brouillon : { ok, d } ; l'échec est noté au bilan.
  async function executer(libelle, requete) {
    try {
      const res = await requete()
      if (!res.ok) throw await echec(res)
      const d = res.status === 204 ? null : await res.json().catch(() => null)
      return { ok: true, d }
    } catch (e) {
      noter(false, `${libelle} : ${e.message}`)
      return { ok: false }
    }
  }

  async function enregistrer() {
    if (!aEnregistrer.length || enregistrement) return
    const annonce = enumerer(aEnregistrer)
    enregistrement = true; bilan = []; error = ''
    try {
      if (brouillon.verdict) await envoyerVerdict()
      if (modifies.length)   await envoyerChamps()
      const coords = coordsModifiees
      if (coords)            await envoyerCoords()
      await envoyerRelations()
      await envoyerContacts()
      await envoyerSites()
      await envoyerNotes()
      const budget = brouillon.budget.ajouts.length + brouillon.budget.suppr.length
      await envoyerBudget()
      await relire()
      if (budget) await loadBudgetAnnexe()
      if (coords) carteVersion++
      await tick()               // aEnregistrer à jour de ce qui reste
      if (bilan.some(b => !b.ok)) {
        noter(false, aEnregistrer.length
          ? `Reste à enregistrer : ${enumerer(aEnregistrer)}.`
          : 'Rien n\'est resté en attente.')
      } else {
        bilan = [{ ok: true, texte: `Enregistré : ${annonce}.` }, ...bilan]
      }
    } finally {
      enregistrement = false
    }
  }

  // Le verdict n'est pas un champ du formulaire : c'est une DÉCISION, posée à
  // part et lue par la publication (collectors/verdict.py). Il ne touche pas à
  // la fiche — donc pas à son verrou : un conflit sur les champs ne l'empêche pas.
  async function envoyerVerdict() {
    const verdict = brouillon.verdict
    let res
    try {
      res = await authFetch(`/atelier/entities/${entityId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ verdict, statut_lu: entity.verdict || 'jamais_relu' }),
      })
    } catch (e) { noter(false, `Verdict : ${e.message}`); return }
    if (res.ok) {
      const r = await res.json()
      entity = { ...entity, verdict: r.verdict, verdict_par: r.reviewed_by,
                 verdict_le: r.reviewed_at }
      brouillon.verdict = null
      noter(true, `Verdict : ${VERDICT[r.verdict].libelle}. ${VERDICT[r.verdict].effet}`)
    } else if (res.status === 409) {
      const d = (await res.json()).detail || {}
      brouillon.verdict = null
      noter(false, 'Verdict : ' + (d.message || 'Le verdict a changé entre-temps.')
        + (d.par ? ` Par ${d.par}` : '') + (d.le ? `, le ${heureLocale(d.le)}` : '')
        + '. Rien n\'a été écrasé.')
      if (d.actuel) entity = { ...entity, verdict: d.actuel, verdict_par: d.par, verdict_le: d.le }
    } else {
      noter(false, `Verdict : l'enregistrement a échoué (${res.status}).`)
    }
  }

  async function envoyerChamps() {
    const champs = [...modifies]
    const noms = champs.map(c => LIBELLES[c] ?? c).join(', ')
    // Verrou optimiste : envoyer updated_at lu au chargement. Un champ vidé
    // part en `null`, que l'API traite comme un effacement.
    const body = { updated_at: entity.updated_at ?? '' }
    for (const k of champs) body[k] = form[k] === '' ? null : form[k]
    let res
    try {
      res = await authFetch(`/atelier/entities/${entityId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
    } catch (e) { noter(false, `${noms} : ${e.message}`); return }
    if (res.status === 409) {
      const d = await res.json()
      conflit = typeof d.detail === 'object' && d.detail
        ? d.detail
        : { message: 'Cette fiche a été modifiée pendant que vous l\'éditiez.' }
      noter(false, `${noms} : la fiche a changé entre-temps, voir l'encadré en haut.`)
      return
    }
    if (!res.ok) { noter(false, `${noms} : ${(await echec(res)).message}`); return }
    const saved = await res.json()
    const valeurs = src => Object.fromEntries(champs.map(k => [k, src[k]]))
    // Fiche publiée, compte contributeur : rien n'est écrit, c'est une
    // PROPOSITION (202). Le formulaire revient à ce que la fiche vaut
    // vraiment — afficher la valeur proposée ferait croire qu'elle est posée.
    if (saved.propose) {
      const proposes = (saved.proposes || []).map(c => LIBELLES[c] ?? c).join(', ')
      form = { ...form, ...valeurs(initial) }
      noter(true, `Proposition envoyée (${proposes}). Cette fiche est publiée : un `
                + `validateur doit l'accepter avant que ce soit appliqué.`)
      return
    }
    // Mettre à jour updated_at local pour le prochain envoi
    if (saved.updated_at) entity = { ...entity, updated_at: saved.updated_at }
    initial = { ...initial, ...valeurs(form) }
  }

  async function envoyerCoords() {
    const lat = +form.lat, lng = +form.lng
    const { ok, d } = await executer('Position sur la carte', () =>
      authFetch(`/atelier/entities/${entityId}/coords`, {
        method: 'PATCH',
        body: JSON.stringify({ lat, lng })
      }))
    if (!ok) return
    if (d?.propose) {
      form = { ...form, lat: initial.lat, lng: initial.lng }
      noter(true, 'Déplacement proposé : cette fiche est publiée, un validateur doit '
                + "l'accepter. Le point reste à sa place d'ici là.")
      return
    }
    initial = { ...initial, lat, lng }
  }

  async function envoyerRelations() {
    const b = brouillon.relations
    const reste = { ajouts: [], modifs: {}, suppr: [] }
    const nom = id => `Relation « ${relations.find(r => r.id === +id)?.relation_type ?? id} »`
    for (const id of b.suppr) {
      const { ok } = await executer(`${nom(id)} (suppression)`, () =>
        authFetch(`/atelier/relations/${id}`, { method:'DELETE' }))
      if (ok) relations = relations.filter(r => r.id !== id)
      else reste.suppr.push(id)
    }
    for (const [id, champs] of Object.entries(b.modifs)) {
      const body = {}
      for (const [k, v] of Object.entries(champs)) body[k] = v === '' ? null : v
      const { ok, d } = await executer(nom(id), () =>
        authFetch(`/atelier/relations/${id}`, { method:'PUT', body:JSON.stringify(body) }))
      if (!ok) { reste.modifs[id] = champs; continue }
      // Relation publiée, compte contributeur : la ligne garde sa valeur.
      if (d.propose) noter(true, d.message)
      else relations = relations.map(r => r.id === +id ? d : r)
    }
    for (const a of b.ajouts) {
      const c = a.corps
      const body = { direction:c.direction, other_entity_id:a.cible.id, relation_type:c.relation_type,
                     since:c.since||null, until:c.until||null, source:c.source||'manual', confidence:c.confidence }
      const { ok, d } = await executer(`Relation « ${c.relation_type} » avec ${a.cible.name}`, () =>
        authFetch(`/atelier/entities/${entityId}/relations`, { method:'POST', body:JSON.stringify(body) }))
      if (ok) relations = [...relations, d]
      else reste.ajouts.push(a)
    }
    brouillon.relations = reste
  }

  async function envoyerContacts() {
    const b = brouillon.contacts
    const reste = { ajouts: [], suppr: [] }
    for (const id of b.suppr) {
      const c = contacts.find(x => x.id === id)
      const { ok } = await executer(`Contact ${c?.value ?? id} (suppression)`, () =>
        authFetch(`/atelier/contacts/${id}`, { method: 'DELETE' }))
      if (ok) contacts = contacts.filter(x => x.id !== id)
      else reste.suppr.push(id)
    }
    for (const a of b.ajouts) {
      const { ok, d } = await executer(`Contact ${a.corps.value}`, () =>
        authFetch(`/atelier/entities/${entityId}/contacts`, {
          method: 'POST',
          body: JSON.stringify(a.corps),
        }))
      if (ok) contacts = [...contacts, d]
      else reste.ajouts.push(a)
    }
    brouillon.contacts = reste
  }

  async function envoyerSites() {
    const b = brouillon.sites
    const reste = { ajouts: [], statuts: {}, suppr: [] }
    const url = id => websites.find(w => w.id === +id)?.url ?? id
    for (const id of b.suppr) {
      const { ok } = await executer(`Site ${url(id)} (suppression)`, () =>
        authFetch(`/atelier/websites/${id}`, { method: 'DELETE' }))
      if (ok) websites = websites.filter(w => w.id !== id)
      else reste.suppr.push(id)
    }
    for (const [id, status] of Object.entries(b.statuts)) {
      const { ok, d } = await executer(`Site ${url(id)}`, () =>
        authFetch(`/atelier/websites/${id}`, {
          method: 'PATCH', body: JSON.stringify({ status })
        }))
      if (ok) websites = websites.map(w => w.id === +id ? d : w)
      else reste.statuts[id] = status
    }
    for (const a of b.ajouts) {
      const { ok, d } = await executer(`Site ${a.corps.url}`, () =>
        authFetch(`/atelier/entities/${entityId}/websites`, {
          method: 'POST', body: JSON.stringify({ url: a.corps.url, found_by: 'manual', score: 1.0 })
        }))
      if (ok) websites = [...websites, d]
      else reste.ajouts.push(a)
    }
    brouillon.sites = reste
  }

  async function envoyerNotes() {
    const b = brouillon.notes
    const reste = { ajouts: [], modifs: {}, suppr: [] }
    for (const id of b.suppr) {
      const { ok } = await executer('Note (suppression)', () =>
        authFetch(`/atelier/notes/${id}`, { method: 'DELETE' }))
      if (ok) notes = notes.filter(n => n.id !== id)
      else reste.suppr.push(id)
    }
    for (const [id, n] of Object.entries(b.modifs)) {
      const { ok, d } = await executer('Note modifiée', () =>
        authFetch(`/atelier/notes/${id}`, {
          method: 'PUT', body: JSON.stringify({ note: n.note, source: n.source, confidence: n.confidence })
        }))
      if (ok) notes = notes.map(x => x.id === +id ? d : x)
      else reste.modifs[id] = n
    }
    for (const a of b.ajouts) {
      const { ok, d } = await executer('Nouvelle note', () =>
        authFetch(`/atelier/entities/${entityId}/notes`, {
          method: 'POST', body: JSON.stringify(a.corps)
        }))
      if (ok) notes = [d, ...notes]
      else reste.ajouts.push(a)
    }
    brouillon.notes = reste
  }

  async function envoyerBudget() {
    const b = brouillon.budget
    const reste = { ajouts: [], suppr: [] }
    for (const id of b.suppr) {
      const { ok } = await executer('Ligne de budget (suppression)', () =>
        authFetch(`/atelier/budget-annexe/${id}`, { method:'DELETE' }))
      if (ok) budgetAnnexe = budgetAnnexe.filter(x => x.id !== id)
      else reste.suppr.push(id)
    }
    for (const a of b.ajouts) {
      const body = { ...a.corps, entity_id: parseInt(entityId), montant: parseFloat(a.corps.montant) }
      const { ok, d } = await executer(`Ligne de budget « ${a.corps.libelle} »`, () =>
        authFetch('/atelier/budget-annexe', { method:'POST', body:JSON.stringify(body) }))
      if (ok) budgetAnnexe = [...budgetAnnexe, d]
      else reste.ajouts.push(a)
    }
    brouillon.budget = reste
  }

  // Après l'envoi : relire la fiche (historique, updated_at, listes). Un champ
  // qui n'est pas passé garde la valeur tapée. Pendant un conflit, la fiche
  // n'est pas relue : c'est l'encadré qui décide de la suite.
  async function relire() {
    const res = await authFetch(`/atelier/entities/${entityId}`)
    if (!res.ok) return
    const frais = await res.json()
    listesDepuis(frais)
    if (conflit) return
    const aGarder = champsAGarder()
    entity = frais
    initial = formDepuis(frais)
    form = { ...initial, ...aGarder }
  }

  function champsAGarder() {
    const cles = [...modifies, ...(coordsModifiees ? ['lat', 'lng'] : [])]
    return Object.fromEntries(cles.map(k => [k, form[k]]))
  }

  function annulerTout() {
    if (!confirm(`Annuler sans enregistrer : ${enumerer(aEnregistrer)} ?`)) return
    brouillon = brouillonVide()
    form = { ...initial }
    bilan = []
    carteVersion++
  }

  // Après un conflit : relire la fiche à jour SANS perdre ce que l'éditeur a
  // tapé. Les champs qu'il n'a pas touchés prennent la version de l'autre ; les
  // siens restent, et rien n'est enregistré tant qu'il ne l'a pas relu.
  async function reprendre() {
    error = ''
    const res = await authFetch(`/atelier/entities/${entityId}`)
    if (!res.ok) { error = `Relecture impossible (${res.status})`; return }
    const frais = await res.json()
    const aGarder = champsAGarder()
    entity = frais
    initial = formDepuis(frais)
    form = { ...initial, ...aGarder }
    audit = [...(frais.audit ?? [])]
    conflit = null
    bilan = [{ ok: true, texte: 'Version à jour chargée — vos modifications sont gardées : relisez, puis enregistrez.' }]
  }

  function abandonner() {
    initial = { ...form }        // rien à protéger : on repart de la base
    load()
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

    {#if error && entity}<span class="save-error">{error}</span>{/if}
  </div>

  {#if conflit}
    <Conflit {conflit} {modifies} on:reprendre={reprendre} on:abandonner={abandonner} />
  {/if}

  {#if loading}
    <div class="center-msg">Chargement…</div>
  {:else if error && !entity}
    <div class="center-msg error">{error}</div>
  {:else if entity}
    <div class="onglets" role="tablist">
      {#each ONGLETS as o}
        <button role="tab" id="onglet-{o.cle}" aria-controls="panneau-{o.cle}"
                aria-selected={onglet === o.cle} class:actif={onglet === o.cle}
                on:click={() => ouvrir(o.cle)}>
          {o.titre}
          {#if enAttente[o.cle]}
            <span class="pastille" title="Changements à enregistrer dans cet onglet">{enAttente[o.cle]}</span>
          {/if}
        </button>
      {/each}
    </div>

    <div class="editor-body" bind:this={corps} class:occupe={enregistrement} aria-busy={enregistrement}
         role="tabpanel" id="panneau-{onglet}" aria-labelledby="onglet-{onglet}">
      {#if onglet === 'essentiel'}
        <Identite bind:form bind:verdict={brouillon.verdict} {entity} {modifies} {tranche} />
        <ChampsDuType bind:form {modifies} />
        <Adresse bind:form {modifies} />
        <Carte bind:form entityName={entity.name} modifiee={coordsModifiees} version={carteVersion} />
        <Budget lignes={budgetAnnexe} chargement={budgetLoading} bind:brouillon={brouillon.budget} />
      {:else if onglet === 'liens'}
        <Relations {relations} entityId={entity.id} bind:brouillon={brouillon.relations} />
        <Contacts {contacts} bind:brouillon={brouillon.contacts} />
        <Sites sites={websites} {tranche} bind:brouillon={brouillon.sites} />
      {:else}
        <Notes {notes} bind:brouillon={brouillon.notes} />
        <Historique {audit} />
      {/if}
    </div>

    <BarreEnregistrement resume={aEnregistrer} {enregistrement} {bilan}
                         bloque={!!conflit}
                         on:enregistrer={enregistrer} on:annuler={annulerTout} />
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
    background: var(--surface);
    border-bottom: 1px solid var(--bordure);
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .back-btn {
    font-size: .78rem;
    color: var(--lien);
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

  .entity-id  { font-size: .72rem; color: var(--texte-doux); }
  .entity-name { font-weight: 600; color: var(--texte); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .save-error { font-size: .78rem; color: var(--danger); }

  /* ── Type badge (topbar) ── */
  .type-badge {
    font-size: .68rem;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 600;
    color: var(--sur-accent);
  }
  .type-person      { background: var(--type-personne); }
  .type-business    { background: var(--type-entreprise); }
  .type-association { background: var(--type-association); }
  .type-place       { background: var(--type-lieu); }
  .type-service     { background: var(--type-service); }
  .type-property    { background: var(--surface-2); }

  /* ── Onglets ── */
  .onglets {
    display: flex;
    gap: .25rem;
    padding: .5rem 1rem 0;
    border-bottom: 1px solid var(--bordure);
    flex-shrink: 0;
    overflow-x: auto;
  }
  .onglets button {
    display: flex; align-items: center; gap: .4rem;
    padding: .45rem .9rem;
    border: 1px solid transparent; border-bottom: none;
    border-radius: 6px 6px 0 0;
    font-size: .82rem; color: var(--texte-doux);
    cursor: pointer; white-space: nowrap;
    margin-bottom: -1px;
  }
  .onglets button:hover { color: var(--texte); }
  .onglets button.actif {
    background: var(--surface); color: var(--texte); font-weight: 600;
    border-color: var(--bordure); border-bottom: 1px solid var(--bordure-douce);
  }
  .pastille {
    background: var(--alerte-bordure); color: var(--sur-accent);
    border-radius: 999px; padding: 0 6px;
    font-size: .68rem; font-weight: 700;
  }

  /* ── Body ── */
  .editor-body {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }
  .editor-body.occupe { pointer-events: none; opacity: .6; }

  .center-msg {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--texte-doux);
    font-size: .9rem;
  }
  .center-msg.error { color: var(--danger); }

  /* ── Commun aux blocs de la fiche (composants voisins) ── */
  .editor-page :global(.card) {
    background: var(--surface);
    border: 1px solid var(--bordure);
    border-radius: 8px;
    padding: 1rem;
  }
  .editor-page :global(.card h2) {
    font-size: .82rem;
    font-weight: 700;
    color: var(--info);
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: .75rem;
    display: flex;
    align-items: center;
    gap: .4rem;
  }
  .editor-page :global(.count-badge) {
    background: var(--surface-2);
    color: var(--texte-doux);
    border-radius: 999px;
    padding: 0 6px;
    font-size: .7rem;
  }

  .editor-page :global(.grid2) {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: .65rem;
  }
  .editor-page :global(.col2) { grid-column: 1 / -1; }
  .editor-page :global(label) {
    display: flex;
    flex-direction: column;
    gap: .3rem;
    font-size: .76rem;
    color: var(--texte-doux);
  }
  .editor-page :global(input),
  .editor-page :global(select),
  .editor-page :global(textarea) {
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 5px;
    color: var(--texte);
    padding: .42rem .55rem;
    font-size: .82rem;
    font-family: inherit;
    transition: border-color .12s;
  }
  .editor-page :global(input:focus),
  .editor-page :global(select:focus),
  .editor-page :global(textarea:focus) { outline: none; border-color: var(--focus); }
  .editor-page :global(input:disabled) { opacity: .6; }
  .editor-page :global(textarea) { resize: vertical; min-height: 70px; }

  .editor-page :global(.muted) { color: var(--texte-doux); font-size: .8rem; }

  .editor-page :global(.conf-dot) {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--bordure-forte);
    flex-shrink: 0;
  }
  .editor-page :global(.conf-dot.verified) { background: var(--succes); }

  .editor-page :global(.btn-add-small) {
    padding: .35rem .7rem; background: var(--accent-fort); color: var(--sur-accent);
    border: none; border-radius: 5px; font-size: .78rem; font-weight: 600;
    cursor: pointer; white-space: nowrap;
  }
  .editor-page :global(.btn-add-small:hover:not(:disabled)) { background: var(--accent-fort); }
  .editor-page :global(.btn-add-small:disabled) { opacity: .45; cursor: default; }

  .editor-page :global(.rel-btn) {
    width: 22px; height: 22px; border-radius: 3px; border: 1px solid var(--bordure);
    font-size: .7rem; cursor: pointer; display: flex; align-items: center; justify-content: center;
    background: transparent; transition: all .12s;
  }
  .editor-page :global(.rel-btn-edit) { color: var(--info); }
  .editor-page :global(.rel-btn-edit:hover) { background: var(--accent-fort); border-color: var(--accent-fort); color: var(--sur-accent); }
  .editor-page :global(.rel-btn-del) { color: var(--danger); }
  .editor-page :global(.rel-btn-del:hover) { background: var(--danger-bordure); border-color: var(--danger-bordure); color: var(--danger-texte); }

  .editor-page :global(.rel-edit-actions) { display: flex; gap: .35rem; padding-top: .2rem; }
  .editor-page :global(.btn-rel-save) {
    padding: .3rem .65rem; background: var(--succes-bordure); color: var(--succes-texte);
    border: 1px solid var(--succes-bordure); border-radius: 5px; font-size: .75rem; font-weight: 600; cursor: pointer;
  }
  .editor-page :global(.btn-rel-save:hover) { background: var(--succes-bordure); border-color: var(--succes); }
  .editor-page :global(.btn-rel-cancel) {
    padding: .3rem .65rem; background: transparent; color: var(--texte-doux);
    border: 1px solid var(--bordure); border-radius: 5px; font-size: .75rem; cursor: pointer;
  }
  .editor-page :global(.btn-rel-cancel:hover) { border-color: var(--bordure-forte); color: var(--texte); }

  /* ── Ce qui attend le bouton « Enregistrer » ── */
  .editor-page :global(.modifie input),
  .editor-page :global(.modifie select),
  .editor-page :global(.modifie textarea) { border-color: var(--alerte-bordure); }
  .editor-page :global(.a-enregistrer) { box-shadow: inset 3px 0 0 var(--alerte-bordure); }
  .editor-page :global(.a-modifier)    { box-shadow: inset 3px 0 0 var(--alerte-bordure); }
  .editor-page :global(.a-supprimer)   { opacity: .55; }
  .editor-page :global(.a-supprimer :is(.contact-value, .rel-dir, .web-url, .note-text, td)) {
    text-decoration: line-through;
  }
  .editor-page :global(.tag-attente) {
    font-size: .68rem; color: var(--alerte); white-space: nowrap;
  }
  .editor-page :global(.lien-annuler) {
    font-size: .72rem; color: var(--lien); cursor: pointer; text-decoration: underline;
    background: none; border: none; padding: 0 .2rem; white-space: nowrap;
  }

  @media (max-width: 640px) {
    .editor-page :global(.grid2) { grid-template-columns: 1fr; }
    .editor-page :global(.col2)  { grid-column: 1; }
  }
</style>
