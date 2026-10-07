<script>
  import { onDestroy, onMount } from 'svelte'
  // Quatre gestes, dans l'ordre où on les fait : générer l'aperçu, le voir,
  // mettre en ligne, voir en ligne. Entre le deuxième et le troisième, la liste
  // de ce qui part — quoi, qui, quand, pourquoi — où chaque ligne se tranche.
  //
  // Avant le 22/08/2026, cette page portait un bouton unique, « Générer &
  // synchroniser le snapshot », qui construisait par-dessus le répertoire servi
  // et le poussait vers le site dans la foulée : le seul moyen de regarder ce
  // qu'on publiait, c'était de l'avoir publié. Puis elle en a porté sept —
  // générer, construire, ouvrir, publier, mettre en ligne, vérifier, revenir —
  // et il fallait connaître la mécanique pour savoir lequel venait ensuite
  // (07/10/2026). La promotion locale et la vérification en ligne existent
  // toujours : elles ne demandent plus de clic.
  import { SITE_NOM, SITE_NOM_ATELIER } from '$lib/instance.js'
  import { api } from '$lib/api.js'
  import { currentUser, authFetch } from '$lib/stores/auth.js'
  import { LIBELLE_ROLE, auMoins, messageErreur } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'
  import { LIBELLES } from '$lib/champs.js'

  const LIBELLE_ETAPE = {
    aucun_apercu:        { texte: 'Aucun aperçu',        ton: 'neutre' },
    pret_a_publier:      { texte: 'Prêt à mettre en ligne', ton: 'ok' },
    controles_en_echec:  { texte: 'Contrôles en échec',  ton: 'ko' },
    promu_localement:    { texte: 'Pas encore en ligne', ton: 'attente' },
    en_ligne:            { texte: 'En ligne, vérifié',   ton: 'ok' },
  }

  const LIENS_APERCU = [
    { chemin: '/deliberations', label: 'Délibérations' },
    { chemin: '/finances',      label: 'Finances' },
    { chemin: '/budgets',       label: 'Budgets' },
    { chemin: '/urbanisme',     label: 'Urbanisme' },
    { chemin: '/couverture',    label: 'Couverture' },
  ]

  const NATURE = { fiche: 'Fiche', coords: 'Point sur la carte', relation: 'Relation',
                   correction: 'Chiffre corrigé' }
  const VERDICT = {
    jamais_relu: { texte: 'jamais relu', ton: 'neutre' },
    retenu:      { texte: 'retenu',      ton: 'ok' },
    a_revoir:    { texte: 'à revoir',    ton: 'attente' },
    ecarte:      { texte: 'écarté',      ton: 'ko' },
  }
  const ORIGINE = { institutionnel: 'collecte (registre)', verbatim: 'collecte (document)',
                    atelier: 'atelier' }

  let etat = null
  let aRelire = null
  let loading = false
  let generating = false
  let publishing = false
  let verifying = false
  let deploying = false
  let serveurEnCours = false
  let error = ''
  let autoTried = false

  // L'API tient le droit ; ceci évite seulement d'afficher une page qui
  // refuserait tout, à qui est arrivé par l'adresse.
  $: admis = auMoins($currentUser, 'validator')
  $: role = etat?.role || $currentUser?.role || null
  $: peutAgir = etat?.peut_agir === true
  $: peutApercevoir = etat?.peut_apercevoir === true
  $: etape = etat?.etape || 'aucun_apercu'
  $: badge = LIBELLE_ETAPE[etape] || LIBELLE_ETAPE.aucun_apercu
  $: brouillon = etat?.brouillon || {}
  $: publie = etat?.publie || {}
  $: controle = brouillon.controle || null
  $: apercu = etat?.apercu || {}
  $: project = etat?.project || {}
  $: enLigne = etat?.en_ligne || {}
  $: deploiement = etat?.mise_en_ligne || {}
  $: urlPublique = etat?.site?.url || null
  // Le serveur d'aperçu est commun à l'atelier : qu'il tourne ne dit pas que
  // CE compte a un site à montrer, ni que ce site est celui du dernier aperçu.
  const pret = (a) => !!a?.actif && a.build?.existe !== false && !a.build?.perime
  const lien = (a, chemin) => `${a.url}${chemin}${a.parametre ? `?${a.parametre}` : ''}`
  $: apercuPret = pret(apercu)
  // Un aperçu en construction et la mise en ligne écrivent au même endroit
  // (`public/.svelte-kit`) : l'une attend l'autre.
  $: apercuEnConstruction = deploiement.build?.genre === 'apercu'
  $: if (apercuEnConstruction && !suivi) suivre()
  $: enCours = deploying || deploiement.actif
  $: occupe = generating || serveurEnCours || publishing || enCours || apercuEnConstruction
  $: aMettreEnLigne = etape === 'pret_a_publier' || etape === 'promu_localement'
  $: estAdmin = role === 'admin'

  // Le store d'auth se réhydrate de façon asynchrone : l'utilisateur peut
  // arriver après le montage.
  $: if (admis && !autoTried) charger()

  // `postAdmin` remonte ses échecs en « 409 {"detail": …} ». Le détail est
  // parfois un objet — message + rapport de contrôle. On rend le contenu, pas
  // l'enveloppe : un contrôle illisible finit ignoré.
  function lireErreur(message) {
    const m = String(message).match(/^\d{3}\s+([[{][\s\S]*)$/)
    if (!m) return { texte: String(message), controle: null }
    try {
      const d = JSON.parse(m[1]).detail
      if (typeof d === 'string') return { texte: d, controle: null }
      return { texte: d?.message || String(message), controle: d?.controle || null }
    } catch {
      return { texte: String(message), controle: null }
    }
  }

  let controleEchec = null

  async function appeler(fn, drapeau) {
    error = ''
    controleEchec = null
    try {
      etat = await fn()
      await chargerARelire()
    } catch (e) {
      const lu = lireErreur(e.message)
      error = lu.texte
      controleEchec = lu.controle
      // L'état a pu changer malgré l'échec (un aperçu rouge EST un aperçu) :
      // on le relit plutôt que de laisser la page mentir.
      await charger({ silencieux: true })
    } finally {
      drapeau()
    }
  }

  async function charger({ silencieux = false } = {}) {
    if (loading) return
    autoTried = true
    loading = true
    if (!silencieux) error = ''
    try {
      etat = await api.publicationEtat()
      await chargerARelire()
    } catch (e) {
      if (!silencieux) error = lireErreur(e.message).texte
    } finally {
      loading = false
    }
  }

  // ─── ① Générer l'aperçu ─────────────────────────────────────────────────
  async function genererApercu() {
    generating = true
    await appeler(api.publicationApercu, () => (generating = false))
    // Un aperçu doit se REGARDER : le site est construit dans la foulée, pour
    // que « Voir l'aperçu » n'ait plus qu'à l'ouvrir.
    if (!error && etat?.brouillon?.existe && etat?.apercu?.installe) {
      await serveurApercu('demarrer')
    }
    if (!error) aRegenerer = false
  }

  async function serveurApercu(action) {
    serveurEnCours = true
    error = ''
    try {
      const r = await api.publicationServeurApercu(action)
      etat = { ...etat, apercu: r }
    } catch (e) {
      error = lireErreur(e.message).texte
    } finally {
      serveurEnCours = false
    }
  }

  // ─── ② Voir l'aperçu ────────────────────────────────────────────────────
  // Prêt, c'est un lien. Sinon (serveur arrêté, site plus ancien que l'aperçu)
  // le site est reconstruit puis ouvert : l'onglet est ouvert DANS le clic, un
  // navigateur refuse celui qu'on ouvre après dix secondes d'attente.
  async function voirApercu() {
    const onglet = window.open('', '_blank')
    await serveurApercu('demarrer')
    if (!error && pret(etat?.apercu)) {
      if (onglet) onglet.location = lien(etat.apercu, '/')
    } else {
      onglet?.close()
    }
  }

  // ─── ③ Mettre en ligne ──────────────────────────────────────────────────
  // Deux gestes côté serveur, un seul ici : promouvoir l'aperçu contrôlé, puis
  // construire le site et le téléverser. Le premier sans le second ne changeait
  // rien pour le public, et la page affichait « publié ».
  let aVerifier = false
  async function mettreEnLigne() {
    if (!confirm(
      `Mettre en ligne sur ${urlPublique || 'le site public'} ?\n\n`
      + "Votre aperçu contrôlé devient la version servie : le site est construit "
      + "puis téléversé chez l'hébergeur. C'est le seul geste de l'atelier qui "
      + 'change ce que le public voit. Compter plusieurs minutes.')) return
    deploying = true
    if (etat?.etape === 'pret_a_publier') {
      await appeler(api.publicationPublier, () => {})
      if (error) { deploying = false; return }
    }
    await appeler(api.publicationMettreEnLigne, () => (deploying = false))
    if (!error) { aVerifier = true; suivre() }
  }

  // Tant que le déploiement tourne, l'état est relu régulièrement. Quand il
  // finit sans erreur, le site est interrogé d'office : « terminé » ne dit pas
  // « en ligne », et personne ne pensait à cliquer « Vérifier ».
  let suivi = null
  function suivre() {
    clearInterval(suivi)
    suivi = setInterval(async () => {
      await charger({ silencieux: true })
      if (!etat?.mise_en_ligne?.actif && !etat?.mise_en_ligne?.build) {
        clearInterval(suivi); suivi = null
        if (aVerifier) {
          aVerifier = false
          if (etat?.mise_en_ligne?.ok) await verifierEnLigne()
        }
      }
    }, 5000)
  }
  onDestroy(() => clearInterval(suivi))

  async function verifierEnLigne() {
    verifying = true
    await appeler(api.publicationVerifierEnLigne, () => (verifying = false))
  }

  async function revenir() {
    if (!confirm(
      'Remettre en service la version précédente ?\n\n'
      + 'Les deux emplacements servis repassent au snapshot d’avant la dernière '
      + 'publication. Le site public, lui, ne changera qu’après « Mettre en ligne ».')) return
    publishing = true
    await appeler(api.publicationRevenir, () => (publishing = false))
  }

  // ─── Ce qui part : quoi, qui, quand, pourquoi ───────────────────────────
  let onglet = 'propositions'
  let pourquoi = {}        // clé de ligne → motif ou note saisis
  let tranche = null       // clé de la ligne en cours d'écriture
  let erreurListe = ''
  // Une décision change la base, pas l'aperçu déjà généré : le dire, sinon on
  // met en ligne un aperçu qui ne porte pas ce qu'on vient de trancher.
  let aRegenerer = false
  let ongletChoisi = false

  $: listes = aRelire ? [
    ['propositions',  'Propositions',  aRelire.propositions.length],
    ['contributions', 'Contributions', aRelire.contributions.length],
    ['nouvelles',     'Nouvelles fiches', aRelire.total_nouvelles],
  ] : []

  async function chargerARelire() {
    try {
      aRelire = await api.publicationModifications()
      for (const l of [...aRelire.contributions, ...aRelire.nouvelles]) {
        if (!(`f${l.id}` in pourquoi)) pourquoi[`f${l.id}`] = l.note || ''
      }
      if (!ongletChoisi) {
        ongletChoisi = true
        onglet = ['propositions', 'contributions', 'nouvelles']
          .find(c => aRelire[c].length) || 'propositions'
      }
    } catch {
      aRelire = null       // liste d'appoint : son absence ne casse pas la page
    }
  }

  const dire = (v) => (v == null || v === '' ? '—' : String(v))
  // Le journal note une décision sous « entity/12 » : c'est le verdict.
  const champ = (c) => (c.includes('/') ? 'verdict' : (LIBELLES[c] ?? c))
  const champs = (liste) => [...new Set((liste || '').split(',').filter(Boolean).map(champ))].join(', ')

  async function trancherProposition(p, accepter) {
    const motif = (pourquoi[`p${p.id}`] || '').trim()
    if (!accepter && !motif) {
      erreurListe = 'Écarter une proposition demande de dire pourquoi : la personne qui a proposé doit savoir quoi corriger.'
      return
    }
    tranche = `p${p.id}`; erreurListe = ''
    try {
      const r = await authFetch(`/atelier/propositions/${p.id}/decision`, {
        method: 'POST', body: JSON.stringify({ accepter, motif, corrections: {} }),
      })
      if (!r.ok) { erreurListe = messageErreur((await r.json()).detail); return }
      aRegenerer = true
      await chargerARelire()
    } finally { tranche = null }
  }

  async function trancherFiche(l, verdict) {
    tranche = `f${l.id}`; erreurListe = ''
    const note = (pourquoi[`f${l.id}`] || '').trim()
    try {
      const r = await authFetch(`/atelier/entities/${l.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ verdict, statut_lu: l.verdict,
                               ...(note !== (l.note || '') ? { note } : {}) }),
      })
      if (!r.ok) { erreurListe = messageErreur((await r.json()).detail); return }
      aRegenerer = true
      await chargerARelire()
    } finally { tranche = null }
  }

  function fmt(n) {
    if (n === null || n === undefined || n === '') return '—'
    return Number(n).toLocaleString('fr-FR')
  }

  function date(iso) {
    if (!iso) return '—'
    const d = new Date(iso)
    return isNaN(d) ? iso : d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
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
  let occupeDecisions = ''

  async function etatDecisions() {
    try { decisions = await api.decisionsEtat() } catch { decisions = null }
  }
  onMount(etatDecisions)

  async function exporter() {
    occupeDecisions = 'export'; error = ''; rapport = null
    try {
      const r = await api.decisionsExporter(sansPersonnes)
      rapport = { type: 'export', ...r }
      await etatDecisions()
    } catch (e) { error = e.message } finally { occupeDecisions = '' }
  }

  // Deux temps, toujours : on lit le rapport, ensuite seulement on écrit.
  // Un import contredit parfois ses propres arbitrages, et c'est irréversible.
  async function importer(appliquer) {
    occupeDecisions = appliquer ? 'import' : 'blanc'; error = ''
    try {
      rapport = { type: appliquer ? 'import' : 'blanc',
                  ...(await api.decisionsImporter(appliquer)) }
    } catch (e) { error = e.message } finally { occupeDecisions = '' }
  }
</script>

<svelte:head>
  <title>Publication — {SITE_NOM}</title>
</svelte:head>

<div class="page">
  <section class="topbar">
    <div>
      <p class="eyebrow">{project.private_name || SITE_NOM_ATELIER}</p>
      <h1>Publication {#if etat}<span class="badge {badge.ton}">{badge.texte}</span>{/if}</h1>
    </div>
    {#if admis}
      <div class="auth">
        <span class="muted">{LIBELLE_ROLE[role] ?? role}{peutAgir ? '' : ' — aperçu et relecture, sans mise en ligne'}</span>
        <button class="secondary" on:click={() => charger()} disabled={loading}>
          {loading ? 'Lecture…' : 'Actualiser'}
        </button>
      </div>
    {/if}
  </section>

  {#if error}
    <div class="error">
      <p>{error}</p>
      {#if controleEchec?.rapport}
        <pre>{controleEchec.rapport}</pre>
      {/if}
    </div>
  {/if}

  {#if $currentUser && !admis}
    <section class="carte">
      <p class="ligne">
        Cette page est réservée aux validateurs et aux administrateurs. Vos
        corrections et vos propositions y sont relues avant de partir en ligne.
      </p>
    </section>
  {:else if !etat}
    <section class="carte"><p class="muted">{loading ? 'Lecture de l’état…' : 'État de publication indisponible.'}</p></section>
  {:else}

  <!-- Les quatre gestes, dans l'ordre. Sous chaque bouton, l'état en une ligne :
       un bouton grisé sans phrase laisse chercher ce qui manque. -->
  <ol class="gestes">
    <li class:fait={brouillon.existe && !aRegenerer}>
      <button class="primary" on:click={genererApercu} disabled={!peutApercevoir || occupe}>
        <span class="num">1</span>
        {generating ? 'Génération…' : serveurEnCours ? 'Construction du site…' : 'Générer l’aperçu'}
      </button>
      <p>
        {#if aRegenerer}
          <strong class="txt-attente">À regénérer</strong> — vous avez tranché depuis le dernier aperçu.
        {:else if !brouillon.existe}
          Le site tel qu’il serait avec la base d’aujourd’hui. Rien en ligne ne bouge.
        {:else}
          Généré le {date(brouillon.genere_le)} ·
          {#if !controle}contrôles non passés
          {:else if controle.ok}<span class="txt-ok">contrôles verts</span>
          {:else}<strong class="txt-ko">{fmt(controle.compte_erreurs)} violation(s)</strong>{/if}
        {/if}
      </p>
    </li>

    <li class:fait={apercuPret}>
      {#if apercuPret}
        <a class="bouton secondary" href={lien(apercu, '/')} target="_blank" rel="noreferrer">
          <span class="num">2</span>Voir l’aperçu ↗
        </a>
      {:else}
        <button class="secondary" on:click={voirApercu}
                disabled={!brouillon.existe || !apercu.installe || !peutApercevoir || occupe}>
          <span class="num">2</span>{serveurEnCours ? 'Construction…' : 'Voir l’aperçu ↗'}
        </button>
      {/if}
      <p>
        {#if !brouillon.existe}Générer l’aperçu d’abord.
        {:else if !apercu.installe}Dépendances du site absentes (<code>cd public &amp;&amp; npm install</code>).
        {:else if apercuPret}
          {#if apercu.build?.pages}{fmt(apercu.build.pages)} pages · {/if}s’ouvre dans un onglet, non publié.
        {:else}Le site sera reconstruit sur l’aperçu, puis ouvert.{/if}
      </p>
    </li>

    <li class:fait={etape === 'en_ligne'}>
      <button class="danger" on:click={mettreEnLigne}
              disabled={!peutAgir || !aMettreEnLigne || aRegenerer || enCours
                        || generating || publishing || serveurEnCours || apercuEnConstruction}>
        <span class="num">3</span>{enCours ? 'Mise en ligne…' : 'Mettre en ligne'}
      </button>
      <p>
        {#if !peutAgir}Réservé aux administrateurs.
        {:else if enCours && apercuEnConstruction}En attente : un aperçu se construit, la mise en ligne commencera ensuite.
        {:else if enCours}En cours vers <code>{deploiement.destination_visee || deploiement.destination}</code> — plusieurs minutes.
        {:else if serveurEnCours || apercuEnConstruction}
          « Mettre en ligne » attend : un aperçu se construit, et deux builds du
          site écrivent au même endroit. Le bouton revient dès qu’il a fini.
        {:else if etape === 'aucun_apercu'}Générer l’aperçu d’abord.
        {:else if etape === 'controles_en_echec'}<strong class="txt-ko">Bloqué</strong> : contrôles rouges. Corriger, puis regénérer.
        {:else if aRegenerer}Regénérer l’aperçu d’abord.
        {:else if deploiement.code_retour !== undefined && !deploiement.ok}
          <strong class="txt-ko">Dernier déploiement en échec</strong> (code {deploiement.code_retour}) — le site n’a pas changé.
        {:else if etape === 'en_ligne'}Cette version est en ligne.
        {:else if !deploiement.destination}
          <span class="txt-attente">Aucune destination déclarée</span> (bloc <code>publication</code> de <code>config/instance.json</code>).
        {:else}Votre aperçu du {date(brouillon.genere_le)} part vers <code>{deploiement.destination}</code>.{/if}
      </p>
    </li>

    <li class:fait={enLigne.ok}>
      {#if urlPublique}
        <a class="bouton secondary" href={urlPublique} target="_blank" rel="noreferrer">
          <span class="num">4</span>Voir en ligne ↗
        </a>
      {:else}
        <button class="secondary" disabled><span class="num">4</span>Voir en ligne ↗</button>
      {/if}
      <p>
        {#if !urlPublique}Aucune adresse déclarée (<code>site_url</code>).
        {:else if verifying}Vérification du site…
        {:else if enLigne.ok && !enLigne.perimee}<span class="txt-ok">À jour</span>, vérifié le {date(enLigne.verifie_le)}.
        {:else if enLigne.verifie_le && !enLigne.perimee}<strong class="txt-ko">Pas à jour</strong> : {enLigne.motif}
        {:else if publie.existe}Sert la version du {date(publie.publie_le)} — non vérifié depuis.
        {:else}Rien n’a encore été mis en ligne d’ici.{/if}
      </p>
    </li>
  </ol>

  <!-- Ce qui part ----------------------------------------------------------- -->
  <section class="carte">
    <header>
      <h2>Ce qui part avec la prochaine mise en ligne</h2>
      <span class="muted">
        {#if aRelire?.depuis}depuis la publication du {date(aRelire.depuis)}{:else}jamais publié d’ici{/if}
      </span>
    </header>

    {#if !aRelire}
      <p class="muted">Liste indisponible.</p>
    {:else}
      <div class="onglets">
        {#each listes as [cle, titre, n]}
          <button class:actif={onglet === cle} on:click={() => { onglet = cle; erreurListe = '' }}>
            {titre} <span class="compte" class:plein={n > 0}>{fmt(n)}</span>
          </button>
        {/each}
      </div>

      {#if erreurListe}<p class="alerte">{erreurListe}</p>{/if}

      {#if onglet === 'propositions'}
        <p class="muted">
          Ce qu’un contributeur a voulu écrire sur une donnée déjà publiée. Rien
          n’est appliqué tant qu’un validateur ne l’a pas validé.
          {#if aRelire.marches_a_relire}
            <a class="lien" href="/atelier/propositions?nature=marche">
              + {fmt(aRelire.marches_a_relire)} marché(s) lus dans des procès-verbaux, à relire l’acte sous les yeux →</a>
          {/if}
        </p>
        {#if !aRelire.propositions.length}
          <p class="vide">Aucune proposition en attente.</p>
        {:else}
          <div class="table"><table>
            <thead><tr><th>Quoi</th><th>Qui</th><th>Quand</th><th>Pourquoi</th><th></th></tr></thead>
            <tbody>
              {#each aRelire.propositions as p (p.id)}
                <tr>
                  <td>
                    <span class="nature">{NATURE[p.nature] ?? p.nature}</span>
                    {#if p.entity_id}
                      <a class="lien" href="/atelier/entite/{p.entity_id}">{p.fiche ?? `fiche ${p.entity_id}`}</a>
                    {:else}
                      <a class="lien" href="/atelier/propositions">{p.object_type} n° {p.object_id}</a>
                    {/if}
                    {#each entries(p.charge) as [c, v]}
                      <div class="change">
                        <span class="muted">{LIBELLES[c] ?? c} :</span>
                        <span class="avant">{dire(p.avant?.[c])}</span> → <strong>{dire(v)}</strong>
                      </div>
                    {/each}
                  </td>
                  <td>{p.propose_par ?? '—'}</td>
                  <td class="quand">{heureLocale(p.propose_le)}</td>
                  <td><input bind:value={pourquoi[`p${p.id}`]} placeholder="Motif (requis pour écarter)" /></td>
                  <td class="gestes-ligne">
                    <button class="valider" on:click={() => trancherProposition(p, true)} disabled={tranche}>Valider</button>
                    <button class="ecarter" on:click={() => trancherProposition(p, false)} disabled={tranche}>Écarter</button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table></div>
        {/if}
      {:else}
        {@const lignes = onglet === 'contributions' ? aRelire.contributions : aRelire.nouvelles}
        <p class="muted">
          {#if onglet === 'contributions'}
            Les fiches modifiées dans l’atelier depuis la dernière publication.
          {:else}
            Les fiches entrées en base depuis la dernière publication, par la collecte ou par l’atelier.
            {#if aRelire.total_nouvelles > lignes.length}Les {lignes.length} plus récentes sur {fmt(aRelire.total_nouvelles)} —
              <a class="lien" href="/atelier/fiches">toutes les fiches →</a>{/if}
          {/if}
          Le nom ouvre la fiche, où tout se corrige. Valider la retient pour le
          site, écarter l’en retire.
        </p>
        {#if !lignes.length}
          <p class="vide">{onglet === 'contributions' ? 'Aucune fiche modifiée.' : 'Aucune fiche nouvelle.'}</p>
        {:else}
          <div class="table"><table>
            <thead><tr><th>Quoi</th><th>Qui</th><th>Quand</th><th>Pourquoi</th><th></th></tr></thead>
            <tbody>
              {#each lignes as l (l.id)}
                <tr>
                  <td>
                    <a class="lien" href="/atelier/entite/{l.id}">{l.name}</a>
                    <span class="tag {VERDICT[l.verdict]?.ton ?? 'neutre'}">{VERDICT[l.verdict]?.texte ?? l.verdict}</span>
                    {#if l.champs}<div class="change muted">{fmt(l.modifications)} écriture(s) : {champs(l.champs)}</div>{/if}
                    {#if l.dans_apercu && apercuPret}
                      <a class="lien" href={lien(apercu, `/entite/${l.id}`)} target="_blank" rel="noreferrer">dans l’aperçu ↗</a>
                    {:else if !l.dans_apercu && brouillon.existe}
                      <span class="muted">absente de l’aperçu</span>
                    {/if}
                  </td>
                  <td>{l.par ?? ORIGINE[l.origine] ?? 'collecte'}</td>
                  <td class="quand">{heureLocale(l.derniere)}</td>
                  <td><input bind:value={pourquoi[`f${l.id}`]} placeholder="Note de décision" /></td>
                  <td class="gestes-ligne">
                    <button class="valider" on:click={() => trancherFiche(l, 'retenu')}
                            disabled={tranche || (l.verdict === 'retenu' && (pourquoi[`f${l.id}`] || '') === (l.note || ''))}>Valider</button>
                    <button class="ecarter" on:click={() => trancherFiche(l, 'ecarte')}
                            disabled={tranche || (l.verdict === 'ecarte' && (pourquoi[`f${l.id}`] || '') === (l.note || ''))}>Écarter</button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table></div>
        {/if}
      {/if}
    {/if}
  </section>

  <!-- Le détail, replié : ce qu'on ne lit que quand quelque chose cloche. -->
  <details class="carte" open={controle && !controle.ok}>
    <summary>
      <h2>Contrôles d’étanchéité</h2>
      {#if !controle}<span class="tag neutre">pas encore passés</span>
      {:else if controle.ok}<span class="tag ok">verts</span>
      {:else}<span class="tag ko">{fmt(controle.compte_erreurs)} violation(s)</span>{/if}
    </summary>
    {#if !controle}
      <p class="muted">Générer un aperçu lance <code>scripts/verify_snapshot.py</code> dessus.</p>
    {:else}
      <p class="ligne">
        {fmt(controle.fichiers)} fichiers inspectés ·
        {fmt(controle.compte_erreurs)} violation(s) bloquante(s) ·
        {fmt(controle.compte_avertissements)} avertissement(s)
        <span class="muted">— {date(controle.controle_le)}</span>
      </p>

      {#if !controle.ok}
        <p class="alerte">
          Mise en ligne bloquée. Ces violations sont ce que le contrôleur — écrit
          comme un adversaire du générateur — refuse de laisser sortir.
        </p>
      {/if}

      {#if controle.erreurs?.length || controle.avertissements?.length}
        {#each [['BLOQUANT', controle.erreurs], ['avertissement', controle.avertissements]] as [niveau, groupes]}
          {#each groupes || [] as g}
            <div class="regle" class:bloquante={niveau === 'BLOQUANT'}>
              <h3>{g.regle} <span class="muted">— {fmt(g.total)} cas</span></h3>
              <ul>
                {#each g.cas as cas}
                  <li>
                    {#if cas.fichier}<code>{cas.fichier}</code>{/if}
                    {#if cas.champ}<code class="champ">{cas.champ}</code>{/if}
                    <span>{cas.message}</span>
                    {#each cas.identifiants || [] as id}
                      {#if cas.objet === 'entite'}
                        <a class="lien" href="/atelier/entite/{id}">fiche #{id} ↗</a>
                      {/if}
                    {/each}
                  </li>
                {/each}
                {#if g.total > g.cas.length}
                  <li class="muted">… {fmt(g.total - g.cas.length)} autres, cf. le rapport complet</li>
                {/if}
              </ul>
            </div>
          {/each}
        {/each}
        <details class="bloc">
          <summary>Rapport complet de <code>verify_snapshot.py</code></summary>
          <pre>{controle.rapport}</pre>
        </details>
      {/if}
    {/if}
  </details>

  {#if brouillon.existe}
  <details class="carte">
    <summary>
      <h2>L’aperçu en chiffres</h2>
      <span class="muted">{fmt(brouillon.stats?.entities_public)} entités · {fmt(brouillon.stats?.events_public)} événements</span>
    </summary>
    <p class="muted">
      Généré le {date(brouillon.genere_le)}{#if brouillon.genere_par} par {brouillon.genere_par}{/if}.
      Il est remplacé par le prochain aperçu que vous générez{#if brouillon.expire_le}, et s’efface le {date(brouillon.expire_le)}{/if}.
    </p>
      <div class="metrics">
        <div class="metric">
          <span>{fmt(brouillon.stats?.entities_public)}</span><small>entités publiques</small>
          <em>{fmt(brouillon.stats?.entities_total_private)} en base</em>
        </div>
        <div class="metric">
          <span>{fmt(brouillon.stats?.events_public)}</span><small>événements publics</small>
          <em>{fmt(brouillon.stats?.events_total_private)} en base</em>
        </div>
        <div class="metric">
          <span>{fmt(brouillon.stats?.relations_public)}</span><small>relations publiques</small>
          <em>{fmt(brouillon.stats?.relations_total_private)} en base</em>
        </div>
        <div class="metric">
          <span>{fmt(brouillon.stats?.map_features_public)}</span><small>points carte</small>
          <em>{fmt(brouillon.stats?.urls_public_confirmed)} URLs confirmées</em>
        </div>
      </div>

      <details class="bloc">
        <summary>Exclusions du filtre de publication</summary>
        <div class="grille">
          {#each entries(brouillon.exclusions) as [section, valeurs]}
            <div>
              <h3>{section}</h3>
              <table>
                <tbody>
                  {#each entries(valeurs) as [motif, n]}
                    <tr><td>{motif}</td><td>{fmt(n)}</td></tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/each}
        </div>
      </details>
    {#if apercuPret}
      <div class="apercu-liens">
        <span class="separateur">ouvrir l’aperçu sur :</span>
        {#each LIENS_APERCU as l}
          <a class="puce" href={lien(apercu, l.chemin)} target="_blank" rel="noreferrer">{l.label} ↗</a>
        {/each}
      </div>
    {/if}
    {#if peutAgir && apercu.actif}
      <!-- Le serveur montre les aperçus de tout l'atelier : l'arrêter les coupe tous. -->
      <button class="secondary" on:click={() => serveurApercu('arreter')} disabled={serveurEnCours}>
        Arrêter le serveur d’aperçu
      </button>
    {/if}
  </details>
  {/if}

  <details class="carte">
    <summary>
      <h2>En ligne — le détail</h2>
      {#if enLigne.ok && !enLigne.perimee}<span class="tag ok">vérifié</span>
      {:else if enLigne.verifie_le && !enLigne.perimee}<span class="tag ko">pas à jour</span>
      {:else}<span class="tag attente">non vérifié</span>{/if}
    </summary>

    {#if publie.existe}
      <p class="ligne">
        Version servie par l’atelier : promue le <strong>{date(publie.publie_le)}</strong>
        {#if publie.publie_par}par <strong>{publie.publie_par}</strong>{/if}
        — {fmt(publie.stats?.entities_public)} entités, {fmt(publie.stats?.events_public)} événements,
        {fmt(publie.stats?.relations_public)} relations, {fmt(publie.stats?.map_features_public)} points carte.
      </p>
      {#if entries(publie.differences).length}
        <p class="alerte">
          Écart entre l’aperçu contrôlé et la copie publiée :
          {#each entries(publie.differences) as [cle, v]}
            <code>{cle}</code> {fmt(v.apercu)} → {fmt(v.publie)}{' '}
          {/each}
          — à regarder, une copie ne doit rien changer.
        </p>
      {/if}
    {:else}
      <p class="muted">Rien n’a encore été promu depuis cet atelier.</p>
    {/if}

    <div class="ligne">
      <span class="etiq">Adresse publique</span>
      {#if urlPublique}
        <a class="lien" href={urlPublique} target="_blank" rel="noreferrer">{urlPublique} ↗</a>
      {:else}
        <em class="muted">aucune déclarée (<code>site_url</code> dans <code>config/instance.json</code>)</em>
      {/if}
    </div>
    <div class="ligne">
      <span class="etiq">Destination</span>
      {#if deploiement.destination}
        <code>{deploiement.destination}</code>
      {:else if deploiement.destination_erreur}
        <span class="alerte">{deploiement.destination_erreur}</span>
      {:else}
        <em class="muted">aucune déclarée (bloc <code>publication</code> dans <code>config/instance.json</code>)</em>
      {/if}
    </div>
    <div class="ligne">
      <span class="etiq">Empreinte promue</span>
      <code>{publie.empreinte || '—'}</code>
    </div>
    {#if enLigne.verifie_le}
      <div class="ligne">
        <span class="etiq">Empreinte servie</span>
        <code>{enLigne.empreinte || '—'}</code>
        {#if enLigne.http}<span class="muted">HTTP {enLigne.http}</span>{/if}
      </div>
      <p class:alerte={!enLigne.ok} class:muted={enLigne.ok}>
        {enLigne.perimee
          ? 'Cette vérification portait sur la version précédente — elle ne dit rien de ce qui vient d’être promu.'
          : enLigne.motif}
        <em class="muted">Vérifié le {date(enLigne.verifie_le)}.</em>
      </p>
    {:else}
      <p class="muted">Jamais vérifié depuis cette machine.</p>
    {/if}

    {#if deploiement.actif}
      <p class="ligne"><span class="tag attente">déploiement en cours</span>
        empreinte <code>{deploiement.empreinte_visee}</code> — journal : <code>{deploiement.journal}</code>
      </p>
    {:else if deploiement.code_retour !== undefined && !deploiement.ok && deploiement.fin_du_journal}
      <details><summary>Fin du journal du dernier déploiement (échec, code {deploiement.code_retour})</summary>
        <pre>{deploiement.fin_du_journal}</pre></details>
    {/if}

    <div class="actions">
      <button class="secondary" on:click={verifierEnLigne} disabled={verifying || !publie.existe}>
        {verifying ? 'Vérification…' : 'Revérifier ce qui est en ligne'}
      </button>
      {#if peutAgir && publie.existe}
        <button class="secondary" on:click={revenir} disabled={occupe}>
          Revenir à la version précédente
        </button>
      {/if}
    </div>
  </details>

  <details class="carte regles">
    <summary><h2>Règles de publication actives</h2></summary>
    <div class="puces">
      <span>confiance : {(etat.rules?.public_confidence || []).join(', ') || '—'}</span>
      <span>relations : {(etat.rules?.public_relation_types || []).length}</span>
      <span>rôles personnes : {(etat.rules?.public_person_relation_types || []).length}</span>
      <span>sources événements : {(etat.rules?.public_event_sources || []).join(', ') || '—'}</span>
      <span>règles : <code>{etat.rules_path}</code></span>
    </div>
  </details>

  {#if estAdmin}
  <details class="carte decisions">
    <summary><h2>Décisions — exporter, reprendre</h2></summary>
    <p class="muted">
      La base se refait toute seule avec le code et un code INSEE. Ce qui ne
      se refait pas, c'est le travail humain : les arbitrages, les
      corrections, les sites validés, les saisies. C'est ça qu'on transporte.
    </p>

    <div class="dec-actions">
      <label class="dec-opt">
        <input type="checkbox" bind:checked={sansPersonnes} />
        Retirer ce qui porte sur des personnes physiques
      </label>
      <button class="secondary" on:click={exporter} disabled={occupeDecisions || !estAdmin}>
        {occupeDecisions === 'export' ? 'Export…' : 'Exporter mes décisions'}
      </button>
      <button class="secondary" on:click={() => importer(false)} disabled={occupeDecisions || !estAdmin}>
        {occupeDecisions === 'blanc' ? 'Lecture…' : 'Lire un import (à blanc)'}
      </button>
      <button class="primary" on:click={() => importer(true)} disabled={occupeDecisions || !estAdmin}>
        {occupeDecisions === 'import' ? 'Import…' : 'Appliquer l\'import'}
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
  </details>
  {/if}
  {/if}
</div>

<style>
  .page {
    width: 100%;
    height: 100%;
    overflow-y: auto;
    padding: 1rem;
    background: var(--fond);
  }

  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: .9rem;
  }

  .eyebrow {
    font-size: .72rem;
    color: var(--texte-doux);
    text-transform: uppercase;
    letter-spacing: .04em;
    margin-bottom: .25rem;
  }

  h1 { font-size: 1.25rem; font-weight: 700; display: flex; align-items: center; gap: .55rem; }
  h2 { font-size: .95rem; font-weight: 700; }
  h3 { font-size: .78rem; color: var(--info); margin: .55rem 0 .25rem; }

  .auth { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; justify-content: flex-end; }

  input {
    width: 200px;
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 6px;
    color: var(--texte);
    padding: .42rem .55rem;
    font-size: .82rem;
  }

  button {
    border-radius: 6px;
    padding: .42rem .7rem;
    font-size: .8rem;
    font-weight: 650;
  }

  button:disabled { opacity: .45; cursor: default; }
  .primary { background: var(--bouton); color: var(--sur-accent); }
  .secondary { background: var(--surface-2); color: var(--texte); }
  .danger { background: var(--danger-bordure); color: var(--danger-texte); }

  .badge, .tag {
    font-size: .7rem;
    font-weight: 700;
    border-radius: 999px;
    padding: .15rem .6rem;
    text-transform: uppercase;
    letter-spacing: .03em;
  }

  .neutre { background: var(--surface); color: var(--texte-doux); border: 1px solid var(--bordure); }
  .ok { background: var(--succes-doux); color: var(--succes-texte); border: 1px solid var(--succes-bordure); }
  .ko { background: var(--danger-doux); color: var(--danger-texte); border: 1px solid var(--danger-bordure); }

  .carte {
    background: var(--surface);
    border: 1px solid var(--bordure);
    border-radius: 8px;
    padding: .9rem;
    margin-bottom: .8rem;
  }

  .carte > header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: .6rem;
    margin-bottom: .55rem;
    flex-wrap: wrap;
  }

  .actions { display: flex; gap: .4rem; }

  .ligne { font-size: .84rem; color: var(--texte-2); margin-bottom: .5rem; }
  .muted { color: var(--texte-doux); font-size: .8rem; }

  .alerte {
    background: var(--danger-doux);
    border: 1px solid var(--danger-bordure);
    color: var(--danger-texte);
    border-radius: 6px;
    padding: .5rem .65rem;
    font-size: .82rem;
    margin: .5rem 0;
  }

  .error {
    background: var(--danger-bordure);
    color: var(--danger-texte);
    border: 1px solid var(--danger-bordure);
    border-radius: 6px;
    padding: .55rem .7rem;
    margin-bottom: .8rem;
    font-size: .82rem;
  }

  .error pre, .bloc pre {
    white-space: pre-wrap;
    background: var(--fond);
    border-radius: 6px;
    padding: .5rem;
    margin-top: .5rem;
    font-size: .74rem;
    color: var(--texte-2);
    max-height: 22rem;
    overflow: auto;
  }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .6rem;
    margin: .6rem 0;
  }

  .metric { background: var(--fond); border: 1px solid var(--bordure); border-radius: 8px; padding: .7rem; }
  .metric span { display: block; font-size: 1.35rem; font-weight: 750; color: var(--info); }
  .metric small { display: block; color: var(--texte); font-size: .76rem; }
  .metric em { display: block; color: var(--texte-doux); font-size: .7rem; font-style: normal; margin-top: .2rem; }

  .bloc { margin-top: .6rem; }
  .bloc summary { cursor: pointer; color: var(--info); font-size: .8rem; }

  .grille { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: .6rem; }
  table { width: 100%; border-collapse: collapse; }
  td { border-bottom: 1px solid var(--bordure); padding: .3rem 0; font-size: .76rem; color: var(--texte-2); }
  td:first-child { color: var(--texte-doux); padding-right: .6rem; }
  td:last-child { text-align: right; font-weight: 700; }

  code {
    background: var(--fond);
    padding: 1px 5px;
    border-radius: 4px;
    color: var(--texte-2);
    font-size: .75rem;
  }

  .champ { color: var(--alerte); }

  .regle { border-left: 2px solid var(--bordure); padding-left: .7rem; margin: .7rem 0; }
  .regle.bloquante { border-left-color: var(--danger-bordure); }
  .regle ul { list-style: none; padding: 0; margin: 0; }
  .regle li {
    font-size: .78rem;
    color: var(--texte-2);
    padding: .22rem 0;
    border-bottom: 1px solid var(--bordure-douce);
    display: flex;
    gap: .4rem;
    flex-wrap: wrap;
    align-items: baseline;
  }

  .lien { color: var(--info); font-size: .76rem; text-decoration: underline; }

  .apercu-liens { display: flex; gap: .35rem; flex-wrap: wrap; margin-bottom: .5rem; align-items: center; }

  .puce {
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 999px;
    padding: .2rem .6rem;
    color: var(--texte-2);
    font-size: .74rem;
    font-weight: 600;
  }

  .puce { text-decoration: none; }

  /* Promu localement sans constatation en ligne : ni vert (ce serait affirmer
     un déploiement), ni rouge (rien n'a échoué). */
  .attente { background: var(--alerte-doux); color: var(--alerte); border: 1px solid var(--alerte-bordure); }
  .etiq { display: inline-block; min-width: 11rem; color: var(--texte-doux); font-size: .8rem; }
  .separateur { color: var(--texte-doux); font-size: .72rem; margin-left: .35rem; }

  .regles .puces { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .4rem; }

  .regles .puces span {
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 999px;
    padding: .2rem .55rem;
    color: var(--texte-2);
    font-size: .74rem;
  }

  @media (max-width: 900px) {
    .topbar { align-items: stretch; flex-direction: column; }
    .auth { justify-content: flex-start; }
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  .sync-ok { color: var(--succes-texte); margin: 0 0 .35rem; font-size: .9rem; }

  .dec-actions { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap;
                 margin: .8rem 0 .5rem; }
  .dec-opt { display: flex; align-items: center; gap: .35rem; font-size: .8rem;
             color: var(--texte-doux); margin-right: auto; }
  .dec-opt input { width: auto; }
  .dec-alerte { color: var(--alerte); font-size: .8rem; line-height: 1.5; margin: .4rem 0; }
  .dec-rapport { margin-top: .7rem; border-top: 1px solid var(--bordure-douce); padding-top: .6rem; }
  .dec-liste { margin: .3rem 0 0; padding-left: 1.1rem; color: var(--texte-doux); font-size: .78rem; }
  .decisions code { background: var(--fond); padding: 1px 6px; border-radius: 4px;
                    color: var(--texte-2); font-size: .78rem; }

  /* Les quatre gestes : une rangée, un bouton et sa phrase d'état. */
  .gestes { list-style: none; margin: 0 0 .9rem; padding: 0; display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; }
  .gestes li { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px;
               padding: .7rem; display: flex; flex-direction: column; gap: .45rem; }
  .gestes li.fait { border-color: var(--succes-bordure); }
  .gestes li > button, .gestes .bouton {
    display: flex; align-items: center; justify-content: center; gap: .45rem;
    border-radius: 6px; padding: .6rem .7rem; font-size: .88rem; font-weight: 650;
    text-decoration: none; text-align: center;
  }
  .gestes p { font-size: .76rem; color: var(--texte-doux); line-height: 1.4; margin: 0; }
  .gestes .num { display: inline-grid; place-items: center; width: 1.25rem; height: 1.25rem;
                 border-radius: 999px; background: var(--fond); color: var(--texte);
                 font-size: .7rem; font-weight: 700; flex-shrink: 0; }
  .txt-ok { color: var(--succes-texte); }
  .txt-ko { color: var(--danger-texte); }
  .txt-attente { color: var(--alerte); }

  .onglets { display: flex; gap: .3rem; flex-wrap: wrap; margin-bottom: .6rem;
             border-bottom: 1px solid var(--bordure); }
  .onglets button { border-radius: 6px 6px 0 0; color: var(--texte-doux); font-weight: 600;
                    border-bottom: 2px solid transparent; }
  .onglets button.actif { color: var(--texte); border-bottom-color: var(--bouton); }
  .compte { font-size: .7rem; padding: 0 .4rem; border-radius: 999px; background: var(--fond);
            color: var(--texte-doux); margin-left: .2rem; }
  .compte.plein { background: var(--info-doux); color: var(--info); }

  .table { overflow-x: auto; margin-top: .5rem; }
  th { text-align: left; color: var(--texte-doux); font-weight: 500; font-size: .74rem;
       padding: .35rem .5rem; border-bottom: 1px solid var(--bordure); }
  .table td { padding: .5rem; vertical-align: top; font-size: .8rem; color: var(--texte);
              text-align: left; font-weight: 400; }
  .table td:first-child { color: var(--texte); min-width: 16rem; }
  .table td input { width: 100%; min-width: 11rem; }
  .table .lien { font-size: .82rem; font-weight: 600; }
  .quand { white-space: nowrap; }
  .nature { font-size: .68rem; text-transform: uppercase; letter-spacing: .03em;
            color: var(--texte-doux); margin-right: .3rem; }
  .change { font-size: .76rem; margin-top: .15rem; overflow-wrap: anywhere; }
  .avant { color: var(--danger-texte); text-decoration: line-through; }
  .gestes-ligne { white-space: nowrap; text-align: right; }
  .valider { background: var(--succes-doux); color: var(--succes-texte); border: 1px solid var(--succes-bordure); }
  .ecarter { background: var(--danger-doux); color: var(--danger-texte); border: 1px solid var(--danger-bordure); }
  .vide { color: var(--texte-doux); font-size: .82rem; padding: .6rem 0; }

  details.carte > summary { display: flex; align-items: center; gap: .6rem; cursor: pointer;
                            list-style: none; }
  details.carte > summary::before { content: '▸'; color: var(--texte-doux); font-size: .8rem; }
  details.carte[open] > summary::before { content: '▾'; }
  details.carte[open] > summary { margin-bottom: .6rem; }
  details.carte .actions { flex-wrap: wrap; margin-top: .6rem; }

  @media (max-width: 900px) {
    .gestes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 520px) {
    .gestes { grid-template-columns: 1fr; }
  }
</style>
