<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
  import { euros } from '$lib/data.js'

  // Le site n'avait aucune page de nouveautés : rien ne donnait envie d'y
  // revenir, et rien ne signalait qu'il était vivant. Le flux est construit sur
  // les dates des actes publiés — pas sur les changements de notre base : un
  // habitant veut savoir ce qui s'est passé dans sa commune, pas ce que nous
  // avons collecté.
  //
  // Trois blocs distincts plutôt qu'une frise unique : mélanger un concert du
  // mois prochain, une délibération de juin et une subvention datée « 2026 »
  // dans le même ordre chronologique donnait une page qui commençait au
  // 31 décembre 2026 — soit cinq mois après l'arrêt des données.
  // Rendu au build par +page.server.js.
  export let data
  $: items = data.items
  $: genere = data.genere
  $: arreteLe = data.arreteLe
  let filtre = ''

  const GENRES = {
    acte: { label: 'Actes et décisions', emoji: '📜' },
    'marché': { label: 'Marchés publics', emoji: '📋' },
    argent: { label: 'Argent public', emoji: '💶' },
    'légal': { label: 'Annonces légales', emoji: '⚖️' },
    vie: { label: 'Vie locale', emoji: '📅' },
  }
  const TYPES = {
    deliberation: 'Délibération', conseil_municipal: 'Conseil municipal',
    'délibérations_cc': 'Délibération intercommunale', pv_cc: 'PV intercommunal',
    autorisation_urbanisme: 'Urbanisme', election: 'Élection',
    'marché_public': 'Marché public', local_event: 'Vie locale',
    bodacc_creation: 'Création d\'entreprise', bodacc_radiation: 'Radiation',
    bodacc_collective: 'Procédure collective', bodacc_divers: 'Annonce légale',
    bodacc_modification: 'Modification', bodacc_vente: 'Vente',
    subvention: 'Subvention', subvention_versee: 'Subvention versée',
    subvention_recue: 'Subvention', dotation_etat: 'Dotation de l\'État',
    dotations_subventions: 'Dotations et subventions',
    concours_etat: 'Concours de l\'État', fonds_de_concours: 'Fonds de concours',
    cession_patrimoine: 'Cession de patrimoine', cession_privee: 'Cession privée',
    marche: 'Marché', bail: 'Bail', reversement: 'Reversement',
    participation: 'Participation', emprunt: 'Emprunt',
    arrete_catnat: 'Arrêté catastrophe naturelle',
  }
  // Le statut et le sens portaient jusqu'ici sur rien : une demande de Fonds
  // Vert de 240 600 € s'affichait comme une subvention reçue, et la DGF
  // encaissée par la commune comme un versement de la commune.
  const STATUTS = {
    demande: { label: 'demandé, non acquis', classe: 'demande' },
    engage: { label: 'voté, non exécuté', classe: 'engage' },
  }
  const SENS = { entrant: '↓ reçu', sortant: '↑ versé' }

  $: retenus = filtre ? items.filter(i => i.genre === filtre) : items

  // 1. À venir : daté après l'arrêt des données. Ce n'est pas « ce qui a
  //    changé », mais le masquer ferait disparaître l'agenda du mois.
  $: aVenir = retenus
    .filter(i => !i.date_approx && i.date > arreteLe)
    .sort((a, b) => a.date.localeCompare(b.date))

  // 2. La frise : uniquement ce qui porte une date réelle et déjà passée.
  $: passes = retenus
    .filter(i => !i.date_approx && i.date <= arreteLe)
    .slice(0, 150)
  $: parMois = passes.reduce((acc, i) => {
    const mois = (i.date || '').slice(0, 7)
    ;(acc[mois] ||= []).push(i)
    return acc
  }, {})

  // 3. Les flux financiers, qui n'ont qu'un millésime : regroupés par année,
  //    hors de la frise. Les dater au 31 décembre les projetait dans le futur.
  $: approx = retenus.filter(i => i.date_approx)
  $: parAnnee = approx.reduce((acc, i) => {
    ;(acc[i.annee] ||= []).push(i)
    return acc
  }, {})
  $: annees = Object.keys(parAnnee).sort((a, b) => b - a)

  const moisLabel = (m) => {
    if (!m) return '—'
    const [a, mo] = m.split('-')
    return new Date(`${a}-${mo}-01T00:00:00`)
      .toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })
  }
  const jour = (d) => d ? new Date(d + 'T00:00:00').getDate() : ''
  const dateLongue = (d) => d
    ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR',
        { day: 'numeric', month: 'long', year: 'numeric' })
    : ''
  const typeLabel = (t) => TYPES[t] || (t || '').replace(/_/g, ' ')
  const compte = (n) => `${n} ${n > 1 ? 'éléments' : 'élément'}`
  // Le jour n'est répété que quand il change : 26 lignes marquées « 31 » à la
  // suite, c'était du bruit typographique, pas de l'information.
  const memeJour = (liste, idx) => idx > 0 && liste[idx - 1].date === liste[idx].date
</script>

<svelte:head>
  <title>Ce qui a changé — {SITE_NOM}</title>
  <meta name="description" content="Les dernières décisions, marchés publics, permis et versements publics {COMMUNE_A} et dans son intercommunalité." />
</svelte:head>

<section class="page">
  <header>
    <h1 class="avec-icone"><Icon name="recent" size={26} />Ce qui a changé</h1>
    <p class="chapeau">
      Les décisions, marchés, permis et versements les plus récents, dans l'ordre
      où ils sont datés.
    </p>
    {#if arreteLe}
      <p class="source">Données arrêtées au {dateLongue(arreteLe)}</p>
    {/if}
  </header>

  <div class="filtres">
    <button class:actif={!filtre} on:click={() => filtre = ''}>Tout</button>
    {#each Object.entries(GENRES) as [k, g]}
      <button class:actif={filtre === k} on:click={() => filtre = k}>
        {g.emoji} {g.label}
      </button>
    {/each}
  </div>

  {#if !items.length}<p class="etat">Aucune nouveauté.</p>
  {:else if !retenus.length}<p class="etat">Rien à afficher.</p>
  {:else}

    {#if aVenir.length}
      <details class="avenir">
        <summary>📅 À venir <span class="compte">{compte(aVenir.length)}</span></summary>
        <ul class="flux">
          {#each aVenir as i, idx}
            <li>
              <span class="jour" class:masque={memeJour(aVenir, idx)}>{jour(i.date)}</span>
              <div class="corps">
                <p class="titre">
                  {#if i.url}<a href={i.url} target="_blank" rel="noopener">{i.titre}</a>
                  {:else}{i.titre}{/if}
                </p>
                <p class="meta">
                  <span class="badge">{typeLabel(i.type)}</span>
                  <span class="quand">{dateLongue(i.date)}</span>
                </p>
              </div>
            </li>
          {/each}
        </ul>
      </details>
    {/if}

    {#each Object.entries(parMois) as [mois, liste]}
      <h2>{moisLabel(mois)} <span class="compte">{compte(liste.length)}</span></h2>
      <ul class="flux">
        {#each liste as i, idx}
          <li>
            <span class="jour" class:masque={memeJour(liste, idx)}>{jour(i.date)}</span>
            <div class="corps">
              <p class="titre">
                {#if i.url}
                  <a href={i.url} target="_blank" rel="noopener">{i.titre || '(sans titre)'}</a>
                {:else if i.acteur_id}
                  <a href="/entite/{i.acteur_id}">{i.titre || '(sans titre)'}</a>
                {:else}{i.titre || '(sans titre)'}{/if}
              </p>
              <p class="meta">
                <span class="badge">{typeLabel(i.type)}</span>
                {#if i.montant}
                  <strong>{euros(i.montant)}</strong>
                  {#if i.montant_indicatif}
                    <em title="Montant le plus élevé cité dans le document, qui peut en porter plusieurs">
                      montant le plus élevé cité
                    </em>
                  {/if}
                {/if}
                <!-- Une donnée rectifiée après contrôle le dit, et dit pourquoi :
                     corriger en silence un chiffre issu d'une source publique
                     serait indéfendable sur un site de veille citoyenne. -->
                {#if i.corrige}
                  <span class="corrige" title={i.note_revue || 'Donnée rectifiée après contrôle'}>
                    ✎ rectifié
                  </span>
                {/if}
                {#if i.acteur_nom && i.acteur_id}
                  · <a href="/entite/{i.acteur_id}">{i.acteur_nom}</a>
                {:else if i.acteur_nom}
                  · {i.acteur_nom}
                {/if}
              </p>
            </div>
          </li>
        {/each}
      </ul>
    {/each}

    {#if annees.length}
      <h2 class="section-annee">💶 Flux financiers par année</h2>
      <p class="note">
        Ces montants ne sont connus qu'au millésime : la source ne donne pas de
        jour. Ils sont donc classés par année plutôt que placés dans la frise.
      </p>
      {#each annees as an}
        <h3>{an} <span class="compte">{compte(parAnnee[an].length)}</span></h3>
        <ul class="flux">
          {#each parAnnee[an] as i}
            <li class:conditionnel={i.statut && STATUTS[i.statut]}>
              <span class="sens" class:entrant={i.sens === 'entrant'}>
                {SENS[i.sens] || ''}
              </span>
              <div class="corps">
                <p class="titre">
                  {#if i.acteur_id}
                    <a href="/entite/{i.acteur_id}">{i.titre}</a>
                  {:else}{i.titre}{/if}
                </p>
                <p class="meta">
                  <span class="badge">{typeLabel(i.type)}</span>
                  {#if i.montant}<strong>{euros(i.montant)}</strong>{/if}
                  {#if STATUTS[i.statut]}
                    <span class="statut {STATUTS[i.statut].classe}">
                      {STATUTS[i.statut].label}
                    </span>
                  {/if}
                  {#if i.perimetre === 'agregat'}
                    <em>montant agrégé</em>
                  {/if}
                  {#if i.corrige}
                    <span class="corrige" title={i.note_revue || 'Donnée rectifiée après contrôle'}>
                      ✎ rectifié
                    </span>
                  {/if}
                  {#if i.acteur_nom && i.acteur_id}
                    · <a href="/entite/{i.acteur_id}">{i.acteur_nom}</a>
                  {:else if i.acteur_nom}
                    · {i.acteur_nom}
                  {/if}
                </p>
              </div>
            </li>
          {/each}
        </ul>
      {/each}
    {/if}
  {/if}
</section>

<style>
  .page { max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
  h1 { font-size: 1.8rem; margin: 0 0 .5rem; color: var(--encre); }
  .chapeau { color: var(--gris); max-width: 60ch; line-height: 1.55; margin: 0 0 .4rem; }
  .source { font-size: .8rem; color: var(--gris-clair); margin: 0 0 1.25rem; }
  .etat { color: var(--gris); }
  .etat.err { color: var(--depense); }
  .note { font-size: .78rem; color: var(--gris); max-width: 62ch; margin: .1rem 0 .9rem;
          line-height: 1.5; }

  .filtres { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
  .filtres button {
    font-size: .8rem; padding: .35rem .7rem; cursor: pointer; color: var(--gris);
    background: #fff; border: 1px solid var(--trait); border-radius: 999px;
  }
  .filtres button:hover { border-color: var(--trait); }
  .filtres button.actif { background: var(--ardoise); color: #fff; border-color: var(--ardoise); }

  h2 { font-size: 1rem; margin: 1.75rem 0 .5rem; color: var(--encre);
       display: flex; align-items: baseline; gap: .5rem; text-transform: capitalize; }
  h2.section-annee { margin-top: 2.5rem; padding-top: 1.25rem;
                     border-top: 1px solid var(--trait); text-transform: none; }
  h3 { font-size: .9rem; margin: 1.25rem 0 .4rem; color: var(--gris);
       display: flex; align-items: baseline; gap: .5rem; }
  .compte { font-size: .72rem; color: var(--gris-clair); font-weight: 400; text-transform: none; }

  .avenir { margin-bottom: 1rem; border: 1px solid var(--trait); border-radius: 9px;
            padding: .6rem .8rem; background: var(--papier); }
  .avenir summary { cursor: pointer; font-size: .9rem; font-weight: 600;
                    color: var(--gris); display: flex; align-items: baseline; gap: .5rem; }
  .avenir .flux { margin-top: .6rem; }

  .flux { list-style: none; margin: 0; padding: 0; display: grid; gap: .3rem; }
  .flux li { display: flex; gap: .8rem; padding: .55rem .7rem; background: #fff;
             border: 1px solid var(--ardoise-pale); border-radius: 9px; }
  .flux li.conditionnel { border-style: dashed; border-color: #e2d5b8; }
  .jour { flex: 0 0 1.7rem; text-align: center; font-size: 1rem; font-weight: 700;
          color: var(--trait); font-variant-numeric: tabular-nums; line-height: 1.4; }
  .jour.masque { visibility: hidden; }
  .sens { flex: 0 0 3.6rem; text-align: right; font-size: .7rem; font-weight: 600;
          color: var(--ambre); line-height: 1.7; white-space: nowrap; }
  .sens.entrant { color: var(--recette); }
  .corps { min-width: 0; }
  .titre { margin: 0; font-size: .9rem; line-height: 1.4; color: var(--encre); }
  .meta { margin: .2rem 0 0; font-size: .76rem; color: var(--gris); display: flex;
          flex-wrap: wrap; gap: .35rem; align-items: baseline; }
  .meta strong { color: var(--encre); font-variant-numeric: tabular-nums; }
  .meta em { font-style: normal; color: var(--gris-clair); }
  .quand { color: var(--gris-clair); }
  .badge { background: var(--trait-pale); color: var(--gris); padding: .08rem .4rem;
           border-radius: 5px; font-size: .7rem; }
  .statut { padding: .08rem .4rem; border-radius: 5px; font-size: .7rem;
            font-weight: 600; }
  .corrige { background: #e7f0ea; color: #047857; padding: .08rem .4rem;
             border-radius: 5px; font-size: .7rem; cursor: help; }
  .statut.demande { background: var(--ambre-pale); color: var(--ambre); }
  .statut.engage { background: #e0e7ff; color: var(--ardoise-fonce); }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
