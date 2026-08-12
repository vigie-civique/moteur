<script>
  import { onMount } from 'svelte'
  import { TYPE_LABELS, euros } from '$lib/data.js'

  // Fiche acteur. Jusqu'au 26/07/2026 elle n'affichait que nom, type, fiabilité
  // et un point sur la carte : les 6 154 liens acteur↔événement de la base
  // n'étaient pas exportés. Ils le sont désormais (event_links.json), ce qui
  // permet enfin de répondre à la seule question qui compte sur une fiche :
  // « qu'est-ce que cet acteur a à voir avec les affaires de la commune ? »

  // Données fournies par +page.server.js au prérendu : un seul bundle
  // `data/entite/<id>.json`, déjà filtré et résolu. Le composant téléchargeait
  // auparavant six JSON complets (~3 Mo) pour n'en afficher qu'une fraction, et
  // faisait tout le filtrage dans le navigateur.
  export let data

  $: ({ entity, relations, liens, flows, marches } = data)
  $: id = entity?.id

  // Chronologie — pour les personnes exerçant un rôle public.
  //
  // La fiche listait des mandats, des commissions et des versements dans des
  // blocs séparés, chacun trié pour son compte. Or ce qu'on cherche sur une
  // personne, c'est une trajectoire : quand elle entre au conseil, quand elle
  // prend une commission, quand une structure qu'elle dirige reçoit une
  // subvention. Ces faits ne prennent leur sens que remis dans l'ordre, les uns
  // à côté des autres.
  //
  // Rien de nouveau n'est affirmé ici : ce sont les mêmes données, remises en
  // ordre. Chaque entrée reste rattachée à ce qui l'atteste.
  const libelleRel = (r) => {
    const l = REL_LABELS[r.relation_type]
    if (!l) return r.relation_type
    return typeof l === 'string' ? l : (r.from_id === id ? l.from : l.to)
  }

  $: chronologie = entity?.type !== 'person' ? [] : [
    // Début et fin de chaque rôle : deux moments distincts, deux entrées.
    ...relations.flatMap((r) => {
      const autre = r.from_id === id ? r.to_name : r.from_name
      const out = []
      if (r.since) {
        out.push({ date: r.since, genre: 'debut',
                   texte: `${libelleRel(r)} — ${autre}` })
      }
      // Une relation dont le début et la fin tombent le même jour décrit un
      // fait ponctuel — une candidature à une élection — et non une période.
      // Afficher « Candidat·e » puis « Fin : Candidat·e » à la même date
      // n'apprenait rien et faisait douter des dates.
      if (r.until && r.until !== r.since) {
        out.push({ date: r.until, genre: 'fin',
                   texte: `Fin : ${libelleRel(r)} — ${autre}` })
      }
      return out
    }),
    // Versements où la personne ou sa structure est partie.
    ...flows.filter((f) => f.year).map((f) => ({
      date: String(f.year),
      genre: 'argent',
      texte: `${f.type_norm || f.type || 'Flux'} — ${f.to_id === id ? (f.from_name || '') : (f.to_name || '')}`,
      montant: f.amount,
    })),
  ].sort((a, b) => (b.date || '').localeCompare(a.date || ''))

  const anneeDe = (d) => (d || '').slice(0, 4)
  $: chronoParAnnee = chronologie.reduce((acc, e) => {
    const a = anneeDe(e.date) || '—'
    ;(acc[a] = acc[a] || []).push(e)
    return acc
  }, {})
  $: anneesChrono = Object.keys(chronoParAnnee).sort().reverse()

  const jourMois = (d) => {
    if (!d || d.length < 10) return ''
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' }) }
    catch { return '' }
  }

  let mapEl, map, L

  const ROLE_LABELS = {
    sujet: 'Concerné', 'mentionné': 'Cité', organisateur: 'Organisateur',
    lieu: 'Lieu', beneficiaire: 'Bénéficiaire', 'bénéficiaire': 'Bénéficiaire',
    votant: 'A voté', acheteur: 'Acheteur', vendeur: 'Vendeur', 'présent': 'Présent',
  }
  const TYPE_EVENT = {
    deliberation: 'Délibération', conseil_municipal: 'Conseil municipal',
    'délibérations_cc': 'Délibération intercommunale', pv_cc: 'PV intercommunal',
    'marché_public': 'Marché public', local_event: 'Événement',
    exposition: 'Exposition', evenement_culturel: 'Événement culturel',
    bodacc_creation: 'Création (BODACC)', bodacc_radiation: 'Radiation (BODACC)',
    bodacc_modification: 'Modification (BODACC)', bodacc_vente: 'Vente (BODACC)',
    bodacc_collective: 'Procédure collective (BODACC)', bodacc_divers: 'Annonce (BODACC)',
    'actualité_cc': 'Actualité intercommunale', article_local: 'Article',
  }
  // `confirmed` n'est jamais attribué en base (constat du 12/08/2026, cf.
  // /methode) : le libellé est conservé pour ne pas afficher un code brut si
  // la valeur réapparaissait, mais il n'y a rien à documenter de plus.
  const CONF_LABELS = { verified: 'Source publique identifiée', confirmed: 'Recoupée' }
  // Certains types de lien sont orientés (from = financeur, to = bénéficiaire).
  // Un libellé fixe inversait le sens réel : la fiche de la commune affichait
  // « Subventionné par <asso> » alors que c'est elle qui verse. Ces types-là
  // prennent donc deux formes, choisies selon la position de la fiche courante.
  const REL_LABELS = {
    maire: 'Maire', adjoint: 'Adjoint·e', 'élu_cm': 'Conseiller·ère municipal·e',
    'élu_cc': 'Conseiller·ère communautaire', 'délégué_cm': 'Délégué·e',
    'délégué_cc': 'Délégué·e communautaire', membre_commission: 'Membre de commission',
    candidat: 'Candidat·e', agent_communal: 'Agent communal',
    'subventionné': { from: 'Subventionne', to: 'Subventionné par' },
    prestataire: { from: 'Prestataire de', to: 'Prestataire' },
    prestataire_commune: { from: 'Prestataire de', to: 'Prestataire' },
    locataire_commune: { from: 'Locataire de', to: 'Loue à' },
    dirigeant: { from: 'Dirige', to: 'Dirigeant·e' },
    'gérant': { from: 'Gère', to: 'Gérant·e' },
    'président': { from: 'Préside', to: 'Président·e' },
    'propriétaire': { from: 'Propriétaire de', to: 'Propriétaire' },
  }

  // Seule la carte reste chargée côté client : Leaflet a besoin du DOM, et le
  // texte de la fiche doit partir dans le HTML prérendu sans attendre le JS.
  onMount(async () => {
    if (!entity?.lat || !entity?.lng) return
    L = (await import('leaflet')).default
    await import('leaflet/dist/leaflet.css')
    map = L.map(mapEl, { attributionControl: true, zoomControl: false }).setView([entity.lat, entity.lng], 15)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map)
    L.circleMarker([entity.lat, entity.lng], { radius: 8, color: '#fff', weight: 2, fillColor: '#2563eb', fillOpacity: .9 }).addTo(map)
  })

  const today = new Date().toISOString().slice(0, 10)
  const actif = (r) => !r.until || r.until > today
  $: relActives = relations.filter(actif)
  $: relPassees = relations.filter(r => !actif(r))

  // Synthèse : ce qu'il faut retenir avant de dérouler les listes.
  $: recu = flows.filter(f => f.to_id === id && f.statut !== 'demande')
                 .reduce((s, f) => s + (f.amount || 0), 0)
  $: verse = flows.filter(f => f.from_id === id && f.statut !== 'demande')
                  .reduce((s, f) => s + (f.amount || 0), 0)
  $: derniere = liens.find(e => e.date)?.date
  $: anneesFlux = [...new Set(flows.map(f => f.year).filter(Boolean))].sort()

  const fmt = (d) => d
    ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
    : '—'
  const relLabel = (r) => {
    const l = REL_LABELS[r.relation_type]
    if (!l) return (r.relation_type || '').replace(/_/g, ' ')
    if (typeof l === 'string') return l
    return r.from_id === id ? l.from : l.to
  }

  // Sur une fiche comme la Commune, la liste à plat répétait 15 fois
  // « Conseiller·ère municipal·e … depuis 2026 » : ni le rôle ni l'année ne
  // distinguaient quoi que ce soit. On regroupe par libellé (donc par type ET
  // par sens) et on ne date que ce qui se distingue. Au-delà de MAX_NOMS, le
  // reste passe dans un <details> — 121 bénéficiaires de subvention à la suite
  // formaient un pavé illisible.
  const MAX_NOMS = 12
  function grouperRels(list) {
    const m = new Map()
    for (const r of list) {
      const k = relLabel(r)
      if (!m.has(k)) m.set(k, [])
      m.get(k).push(r)
    }
    return [...m].map(([label, items]) => {
      const annees = new Set(items.map(r => r.since ? r.since.slice(0, 4) : null))
      return {
        label, items,
        visibles: items.slice(0, MAX_NOMS),
        reste: items.slice(MAX_NOMS),
        annee: annees.size === 1 ? [...annees][0] : null,
      }
    })
  }
  $: groupesActifs = grouperRels(relActives)
  const evLabel = (t) => TYPE_EVENT[t] || t
</script>

<!-- Maintenant que la page est prérendue, ces balises servent enfin à quelque
     chose : c'est ce qu'un moteur de recherche et un partage de lien affichent. -->
<svelte:head>
  <title>{entity?.name || 'Fiche'} — {entity?.commune || 'Lasalle'} | Vigie Civique Lasalle</title>
  <meta name="description" content={
    `${entity?.name || ''} — ${TYPE_LABELS[entity?.type] || ''}`
    + (entity?.commune ? ` à ${entity.commune}` : '')
    + `. ${liens.length} acte(s) public(s) le citant, ${relActives.length} lien(s) en cours`
    + (recu > 0 ? `, ${euros(recu)} reçus de fonds publics` : '')
    + '. Données publiques.'} />
</svelte:head>

<section>
  <a class="back" href="/acteurs-publics">← Qui agit&nbsp;?</a>

  {#if entity}
    <header>
      <span class="badge {entity.type}">{TYPE_LABELS[entity.type] || entity.type}</span>
      <h1>{entity.name}</h1>
      {#if entity.short_name}<p class="alias">{entity.short_name}</p>{/if}
    </header>

    <!-- Synthèse chiffrée : le résumé avant le détail. -->
    <div class="tiles">
      {#if recu > 0}
        <div class="tile"><span class="tval">{euros(recu)}</span><span class="tlabel">reçu</span></div>
      {/if}
      {#if verse > 0}
        <div class="tile"><span class="tval">{euros(verse)}</span><span class="tlabel">versé</span></div>
      {/if}
      {#if relActives.length}
        <div class="tile"><span class="tval">{relActives.length}</span><span class="tlabel">lien{relActives.length > 1 ? 's' : ''} en cours</span></div>
      {/if}
      {#if liens.length}
        <div class="tile"><span class="tval">{liens.length}</span><span class="tlabel">acte{liens.length > 1 ? 's' : ''} le citant</span></div>
      {/if}
      {#if derniere}
        <div class="tile"><span class="tval">{fmt(derniere)}</span><span class="tlabel">dernière apparition</span></div>
      {/if}
    </div>

    <div class="cols">
      <div class="info">
        <h2>Informations</h2>
        <dl>
          <dt>Type</dt><dd>{TYPE_LABELS[entity.type] || entity.type}</dd>
          {#if entity.commune}<dt>Commune</dt><dd>{entity.commune}</dd>{/if}
          <dt>Fiabilité</dt><dd>{CONF_LABELS[entity.confidence] || entity.confidence}</dd>
          {#if entity.naf_label}<dt>Activité</dt><dd>{entity.naf_label}</dd>{/if}
          {#if entity.siren}<dt>SIREN</dt><dd>{entity.siren}</dd>{/if}
          {#if entity.osm_category}<dt>Catégorie</dt><dd>{entity.osm_category} {entity.osm_value || ''}</dd>{/if}
          {#if entity.urls && entity.urls.length}
            <dt>Liens</dt>
            <dd>{#each entity.urls as u}<a href={u.url || u} target="_blank" rel="noopener">{u.label || u.domain || u}</a><br>{/each}</dd>
          {/if}
        </dl>

        {#if relActives.length || relPassees.length}
          <h2>Liens avec les autres acteurs</h2>
          <ul class="rels">
            {#each groupesActifs as g}
              <li>
                <span class="rel">{g.label}{#if g.items.length > 1}<span class="count">{g.items.length}</span>{/if}</span>
                <span class="noms">
                  {#each g.visibles as r, i}<a href="/entite/{r.autre_id}">{r.autre}</a>{#if !g.annee && r.since}<span class="since"> ({r.since.slice(0, 4)})</span>{/if}{#if i < g.visibles.length - 1}<span class="sep">·</span>{/if}{/each}
                  {#if g.reste.length}
                    <details>
                      <summary>et {g.reste.length} autre{g.reste.length > 1 ? 's' : ''}</summary>
                      {#each g.reste as r, i}<a href="/entite/{r.autre_id}">{r.autre}</a>{#if i < g.reste.length - 1}<span class="sep">·</span>{/if}{/each}
                    </details>
                  {/if}
                </span>
                {#if g.annee}<span class="since">depuis {g.annee}</span>{/if}
              </li>
            {/each}
            {#each relPassees as r}
              <li class="passe">
                <span class="rel">{relLabel(r)}</span>
                <a href="/entite/{r.autre_id}">{r.autre}</a>
                <span class="since">
                  {r.since ? r.since.slice(0, 4) : '?'}–{r.until ? r.until.slice(0, 4) : '?'} · terminé
                </span>
              </li>
            {/each}
          </ul>
        {/if}

        {#if flows.length}
          <h2>Flux financiers</h2>
          <p class="note">
            Montants constatés, hors agrégats comptables et hors subventions
            seulement sollicitées. {anneesFlux.length ? `Période ${anneesFlux[0]}–${anneesFlux[anneesFlux.length - 1]}.` : ''}
          </p>
          <table>
            <thead><tr><th>Année</th><th>Nature</th><th class="r">Montant</th></tr></thead>
            <tbody>
              {#each flows as f}
                <tr class:demande={f.statut === 'demande'}>
                  <td>{f.year || '—'}</td>
                  <td>
                    <span class="ftype">{(f.type_norm || f.type || '').replace(/_/g, ' ')}</span>
                    {#if f.statut === 'demande'}<span class="tag">demandé</span>{/if}
                    {#if f.description}<span class="fdesc">{f.description}</span>{/if}
                    <span class="fsens">{f.to_id === id ? `de ${f.from_name || '—'}` : `à ${f.to_name || '—'}`}</span>
                  </td>
                  <td class="r">{euros(f.amount)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if marches.length}
          <h2>Marchés publics</h2>
          <table>
            <thead><tr><th>Notifié</th><th>Objet</th><th class="r">Montant</th></tr></thead>
            <tbody>
              {#each marches as m}
                <tr>
                  <td>{m.date_notif || '—'}</td>
                  <td>{m.objet}<span class="fsens">{m.titulaire_id === id ? `pour ${m.acheteur_nom}` : `titulaire : ${m.titulaire_nom || '—'}`}</span></td>
                  <td class="r">{m.montant ? euros(m.montant) : '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        <!-- Deux entrées suffisent : c'est déjà une trajectoire. Le seuil plus
             haut masquait des fiches dont la chronologie tenait tout l'intérêt. -->
        {#if chronologie.length > 1}
          <h2>Chronologie <span class="count">{chronologie.length}</span></h2>
          <p class="note chrono-note">
            Les mêmes informations que ci-dessus, remises dans l'ordre. Une
            chronologie rapproche des faits&nbsp;; elle n'établit pas de lien de
            cause à effet entre eux.
          </p>
          <ol class="chrono">
            {#each anneesChrono as annee}
              <li class="an">
                <span class="an-label">{annee}</span>
                <ul>
                  {#each chronoParAnnee[annee] as e}
                    <li class={e.genre}>
                      {#if jourMois(e.date)}<span class="jour">{jourMois(e.date)}</span>{/if}
                      <span class="quoi">{e.texte}</span>
                      {#if e.montant != null}<span class="montant">{euros(e.montant)}</span>{/if}
                    </li>
                  {/each}
                </ul>
              </li>
            {/each}
          </ol>
        {/if}

        {#if liens.length}
          <h2>Actes et publications le concernant <span class="count">{liens.length}</span></h2>
          <ul class="events">
            {#each liens.slice(0, 60) as e}
              <li>
                <span class="date">{fmt(e.date)}</span>
                <span class="etype">{evLabel(e.type)}</span>
                <span class="etitle">
                  {e.title}
                  {#if e.role && ROLE_LABELS[e.role]}<em class="role">{ROLE_LABELS[e.role]}</em>{/if}
                </span>
                <span class="emeta">
                  {#if e.montant_principal}<b>{euros(e.montant_principal)}</b>{/if}
                  {#if e.vote}
                    <span class="vote">
                      {#if e.vote.unanimite}unanimité
                      {:else}{e.vote.pour ?? '?'} pour · {e.vote.contre ?? 0} contre{/if}
                    </span>
                  {/if}
                  {#if e.source_url}<a href={e.source_url} target="_blank" rel="noopener">source ↗</a>{/if}
                </span>
              </li>
            {/each}
          </ul>
          {#if liens.length > 60}
            <p class="note">Les 60 actes les plus récents sur {liens.length}.</p>
          {/if}
        {/if}

        {#if !flows.length && !liens.length && !relations.length && !marches.length}
          <p class="empty">
            Aucun acte public ni flux financier n'est rattaché à cet acteur dans
            les sources collectées à ce jour.
          </p>
        {/if}
      </div>

      {#if entity.lat && entity.lng}
        <div class="map" bind:this={mapEl}></div>
      {/if}
    </div>
  {/if}
</section>

<style>
  /* Chronologie : l'année sert de repère, les entrées s'y accrochent. Le trait
     vertical fait la trajectoire — c'est ce qui distingue une chronologie
     d'une liste triée par date. */
  .chrono { list-style: none; padding: 0; margin: .5rem 0 1.5rem; }
  .chrono .an { display: grid; grid-template-columns: 4rem 1fr; gap: .75rem; }
  .an-label { font-weight: 700; color: var(--ardoise); font-variant-numeric: tabular-nums;
              padding-top: .3rem; }
  .chrono .an > ul { list-style: none; margin: 0; padding: 0 0 .9rem 1rem;
                     border-left: 2px solid var(--trait); }
  .chrono .an > ul > li { position: relative; padding: .3rem 0;
                          display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline;
                          font-size: .9rem; color: var(--encre); }
  .chrono .an > ul > li::before {
    content: ''; position: absolute; left: -1.32rem; top: .72rem;
    width: 7px; height: 7px; border-radius: 50%; background: var(--gris-clair);
  }
  .chrono li.debut::before  { background: var(--recette); }
  .chrono li.fin::before    { background: var(--gris-clair); }
  .chrono li.argent::before { background: var(--ambre); }
  .chrono li.fin .quoi { color: var(--gris); }
  .chrono .jour { font-size: .76rem; color: var(--gris); font-variant-numeric: tabular-nums;
                  min-width: 4.2rem; }
  .chrono .montant { font-size: .85rem; color: var(--ambre); font-variant-numeric: tabular-nums; }
  .chrono-note { margin-bottom: .75rem; }
  @media (max-width: 680px) {
    .chrono .an { grid-template-columns: 1fr; gap: .2rem; }
  }

  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; }
  .back { font-size: .9rem; }
  header { margin: 1rem 0; }
  h1 { margin: .3rem 0 0; color: var(--encre); }
  .alias { color: var(--gris); margin: .2rem 0 0; }
  .badge { font-size: .75rem; padding: .15rem .6rem; border-radius: 99px; color: #fff; background: var(--gris); }
  .badge.service { background: var(--ardoise); } .badge.association { background: var(--recette); }
  .badge.business { background: var(--ambre); } .badge.place { background: var(--ardoise); } .badge.person { background: var(--depense); }

  .tiles { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 1.4rem; }
  .tile { background: var(--papier); border: 1px solid var(--trait); border-radius: 10px;
          padding: .6rem .9rem; display: flex; flex-direction: column; min-width: 8rem; }
  .tval { font-size: 1.15rem; font-weight: 600; color: var(--encre); }
  .tlabel { font-size: .75rem; color: var(--gris); text-transform: uppercase; letter-spacing: .03em; }

  .cols { display: grid; grid-template-columns: 1fr 380px; gap: 1.5rem; }
  h2 { font-size: 1.1rem; color: var(--encre); margin: 1.6rem 0 .5rem; }
  h2 .count { font-size: .8rem; color: var(--gris-clair); font-weight: 400; }
  dl { display: grid; grid-template-columns: 130px 1fr; gap: .4rem 1rem; margin: 0; }
  dt { color: var(--gris); } dd { margin: 0; }
  .note { color: var(--gris); font-size: .82rem; margin: .2rem 0 .6rem; }
  .empty { color: var(--gris); background: var(--papier); border: 1px solid var(--trait);
           border-radius: 8px; padding: .9rem; font-size: .9rem; }

  table { width: 100%; border-collapse: collapse; font-size: .9rem; }
  th, td { text-align: left; padding: .45rem .5rem; border-bottom: 1px solid var(--trait); vertical-align: top; }
  th { color: var(--gris); font-weight: 500; }
  .r { text-align: right; white-space: nowrap; }
  tr.demande td { color: #78716c; }
  .ftype { text-transform: capitalize; }
  .tag { font-size: .68rem; background: var(--ambre-pale); color: var(--ambre); padding: .05rem .4rem;
         border-radius: 99px; margin-left: .3rem; }
  .fdesc, .fsens { display: block; color: var(--gris); font-size: .8rem; }

  .rels { list-style: none; padding: 0; margin: 0; }
  .rels li { display: grid; grid-template-columns: 12rem 1fr auto; gap: .2rem .8rem; align-items: baseline;
             padding: .35rem 0; border-bottom: 1px solid var(--trait-pale); font-size: .92rem; }
  .rels .rel { color: var(--gris); }
  .rels .count { display: inline-block; margin-left: .35rem; padding: 0 .35rem; border-radius: 99px;
                 background: var(--trait-pale); color: var(--gris); font-size: .75rem; }
  .rels .noms { line-height: 1.6; }
  .rels .sep { color: var(--trait); margin: 0 .35rem; }
  .rels details { margin-top: .15rem; }
  .rels summary { cursor: pointer; color: var(--gris); font-size: .82rem; }
  .rels summary:hover { color: var(--ardoise); }
  .rels .since { color: var(--gris-clair); font-size: .8rem; white-space: nowrap; }
  .rels li.passe { opacity: .65; }

  .events { list-style: none; padding: 0; margin: 0; }
  .events li { display: grid; grid-template-columns: 6.5rem 9rem 1fr auto;
               gap: .6rem; align-items: baseline; padding: .45rem .2rem;
               border-bottom: 1px solid var(--trait-pale); font-size: .9rem; }
  .events .date { color: var(--ardoise); font-size: .82rem; white-space: nowrap; }
  .events .etype { color: var(--gris); font-size: .78rem; }
  .events .role { color: var(--gris-clair); font-style: normal; font-size: .75rem;
                  border: 1px solid var(--trait); border-radius: 99px; padding: 0 .4rem; margin-left: .35rem; }
  .events .emeta { text-align: right; white-space: nowrap; font-size: .8rem; color: var(--gris); }
  .events .vote { color: var(--gris); margin-left: .4rem; }
  .events a { font-size: .78rem; color: var(--gris); margin-left: .4rem; }

  .map { height: 320px; border-radius: 10px; border: 1px solid var(--trait); }
  .err { color: var(--depense); }
  @media (max-width: 760px) {
    .cols { grid-template-columns: 1fr; } .map { height: 260px; }
    .rels li { grid-template-columns: 1fr; gap: .1rem; }
    .events li { grid-template-columns: 1fr; gap: .15rem; }
    .events .emeta { text-align: left; }
  }
</style>
