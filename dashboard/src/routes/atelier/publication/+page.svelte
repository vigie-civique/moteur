<script>
  // Publication en quatre temps : ce qui est en ligne, un aperçu, ses contrôles,
  // puis — et seulement si tout est vert — la publication.
  //
  // Avant le 22/08/2026, cette page portait un bouton unique, « Générer &
  // synchroniser le snapshot », qui construisait par-dessus le répertoire servi
  // et le poussait vers le site dans la foulée. Le contrôle d'étanchéité
  // arrivait bien avant la synchro, mais le mal était déjà fait côté atelier :
  // le seul moyen de regarder ce qu'on publiait, c'était de l'avoir publié.
  import { SITE_NOM, SITE_NOM_ATELIER } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { currentUser } from '$lib/stores/auth.js'

  const KEY_STORAGE = 'vigie-admin-key'

  const ETAPES = [
    { cle: 'publie_actuel', titre: 'État publié' },
    { cle: 'apercu',        titre: 'Aperçu brouillon' },
    { cle: 'controles',     titre: 'Contrôles' },
    { cle: 'publication',   titre: 'Publication' },
  ]

  // Les cinq états du flux, nommés. Un bouton grisé sans phrase laisse chercher
  // ce qui manque ; ici l'état se lit.
  // `publie` disait deux choses à la fois : « l'atelier a promu le snapshot »
  // et « le site public le sert ». Entre les deux il y a un build et un
  // déploiement que l'atelier ne fait pas — et la page l'écrivait plus bas,
  // après avoir affiché « Publié » en tête. Qui lit le badge et ferme l'onglet
  // croit son site à jour.
  const LIBELLE_ETAPE = {
    aucun_apercu:        { texte: 'Aucun aperçu',        ton: 'neutre' },
    pret_a_publier:      { texte: 'Prêt à publier',      ton: 'ok' },
    controles_en_echec:  { texte: 'Contrôles en échec',  ton: 'ko' },
    promu_localement:    { texte: 'Promu localement',    ton: 'attente' },
    en_ligne:            { texte: 'En ligne, vérifié',   ton: 'ok' },
  }

  const LIENS_APERCU = [
    { chemin: '/',              label: 'Accueil' },
    { chemin: '/deliberations', label: 'Délibérations' },
    { chemin: '/finances',      label: 'Finances' },
    { chemin: '/budgets',       label: 'Budgets' },
    { chemin: '/urbanisme',     label: 'Urbanisme' },
    { chemin: '/couverture',    label: 'Couverture' },
  ]

  let adminKey = ''
  let etat = null
  let modifications = null
  let loading = false
  let generating = false
  let publishing = false
  let verifying = false
  let serveurEnCours = false
  let error = ''
  let controleDeplie = false
  let autoTried = false

  $: role = etat?.role || $currentUser?.role || null
  $: peutAgir = etat?.peut_agir === true
  $: etape = etat?.etape || 'aucun_apercu'
  $: badge = LIBELLE_ETAPE[etape] || LIBELLE_ETAPE.aucun_apercu
  $: brouillon = etat?.brouillon || {}
  $: publie = etat?.publie || {}
  $: controle = brouillon.controle || null
  $: apercu = etat?.apercu || {}
  $: project = etat?.project || {}
  $: enLigne = etat?.en_ligne || {}
  $: urlPublique = etat?.site?.url || null
  $: promu = etape === 'promu_localement' || etape === 'en_ligne'
  $: peutPublier = peutAgir && etape === 'pret_a_publier'
  // Exporter ou importer des décisions passe par `require_role("admin")` :
  // une clé admin ne suffit pas, il faut une session au bon rôle.
  $: estAdmin = role === 'admin'

  // Un utilisateur connecté charge l'état sans rien saisir : il est en lecture
  // seule de toute façon, et la clé n'ouvre que les actions. Le store d'auth se
  // réhydrate de façon asynchrone, donc l'utilisateur peut arriver après le
  // montage — d'où les deux déclencheurs, et le garde-fou dans `charger()` pour
  // qu'ils ne tirent pas deux requêtes.
  $: if ($currentUser && !autoTried) charger()

  onMount(() => {
    adminKey = sessionStorage.getItem(KEY_STORAGE) || ''
    if (adminKey || $currentUser) charger()
  })

  function rememberKey() {
    if (adminKey.trim()) sessionStorage.setItem(KEY_STORAGE, adminKey.trim())
  }

  function forgetKey() {
    sessionStorage.removeItem(KEY_STORAGE)
    adminKey = ''
  }

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
      rememberKey()
      etat = await fn(adminKey.trim())
      await chargerModifications()
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
      rememberKey()
      etat = await api.publicationEtat(adminKey.trim())
      await chargerModifications()
    } catch (e) {
      if (!silencieux) error = lireErreur(e.message).texte
    } finally {
      loading = false
    }
  }

  async function chargerModifications() {
    try {
      modifications = await api.publicationModifications(adminKey.trim())
    } catch {
      modifications = null   // liste d'appoint : son absence ne casse pas la page
    }
  }

  async function genererApercu() {
    generating = true
    controleDeplie = false
    await appeler(api.publicationApercu, () => (generating = false))
  }

  async function publier() {
    publishing = true
    await appeler(api.publicationPublier, () => (publishing = false))
  }

  async function verifierEnLigne() {
    verifying = true
    await appeler(api.publicationVerifierEnLigne, () => (verifying = false))
  }

  async function revenir() {
    if (!confirm(
      'Remettre en service la version précédente ?\n\n'
      + 'Les deux emplacements servis repassent au snapshot d’avant la dernière '
      + 'publication. Le site public, lui, ne changera qu’après un nouveau build '
      + 'et un nouveau déploiement.')) return
    publishing = true
    await appeler(api.publicationRevenir, () => (publishing = false))
  }

  async function serveurApercu(action) {
    serveurEnCours = true
    error = ''
    try {
      rememberKey()
      const r = await api.publicationServeurApercu(action, adminKey.trim())
      etat = { ...etat, apercu: r }
    } catch (e) {
      error = lireErreur(e.message).texte
    } finally {
      serveurEnCours = false
    }
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
  <title>Publication — {SITE_NOM}</title>
</svelte:head>

<div class="page">
  <section class="topbar">
    <div>
      <p class="eyebrow">{project.private_name || SITE_NOM_ATELIER}</p>
      <h1>Publication <span class="badge {badge.ton}">{badge.texte}</span></h1>
    </div>
    <div class="auth">
      {#if peutAgir}
        <span class="muted">Admin — clé facultative</span>
      {:else if role}
        <span class="muted">Rôle {role} — lecture seule</span>
      {/if}
      <input
        type="password"
        bind:value={adminKey}
        placeholder="Clé admin (facultative)"
        on:keydown={(e) => e.key === 'Enter' && charger()}
      />
      <button class="secondary" on:click={() => charger()} disabled={loading}>
        {loading ? 'Lecture…' : 'Recharger'}
      </button>
      <button class="ghost" on:click={forgetKey}>Oublier la clé</button>
    </div>
  </section>

  <ol class="pipeline">
    {#each ETAPES as e, i}
      <li class:courant={
        (e.cle === 'apercu' && etape === 'aucun_apercu') ||
        (e.cle === 'controles' && etape === 'controles_en_echec') ||
        (e.cle === 'publication' && (etape === 'pret_a_publier' || promu))
      }>
        <span class="num">{i + 1}</span>{e.titre}
      </li>
    {/each}
  </ol>

  {#if error}
    <div class="error">
      <p>{error}</p>
      {#if controleEchec?.rapport}
        <pre>{controleEchec.rapport}</pre>
      {/if}
    </div>
  {/if}

  {#if !etat}
    <section class="carte">
      <p class="muted">Se connecter à l’atelier, ou saisir la clé admin, pour lire l’état de publication.</p>
    </section>
  {:else}

  <!-- ① Ce qui est en ligne ------------------------------------------------ -->
  <section class="carte">
    <header>
      <h2>① Ce que l’atelier sert</h2>
      {#if publie.existe}
        <span class="tag ok">promu localement</span>
      {:else}
        <span class="tag neutre">rien de promu</span>
      {/if}
    </header>

    {#if publie.existe}
      <p class="ligne">
        Publié le <strong>{date(publie.publie_le)}</strong>
        {#if publie.publie_par}par <strong>{publie.publie_par}</strong>{:else}
          <em class="muted">— auteur inconnu, publication antérieure au journal</em>{/if}
      </p>
      <div class="metrics">
        <div class="metric"><span>{fmt(publie.stats?.entities_public)}</span><small>entités</small></div>
        <div class="metric"><span>{fmt(publie.stats?.events_public)}</span><small>événements</small></div>
        <div class="metric"><span>{fmt(publie.stats?.relations_public)}</span><small>relations</small></div>
        <div class="metric"><span>{fmt(publie.stats?.map_features_public)}</span><small>points carte</small></div>
      </div>
      {#if publie.synchro}
        <p class="muted">
          {fmt(publie.synchro.count)} fichiers vers <code>{publie.synchro.dest}</code>
          {#if publie.synchro.fichiers_retires?.length}
            · {publie.synchro.fichiers_retires.length} fichier(s) retiré(s)
          {/if}
        </p>
      {/if}
      {#if entries(publie.differences).length}
        <p class="alerte">
          Écart entre l’aperçu contrôlé et la copie publiée :
          {#each entries(publie.differences) as [cle, v]}
            <code>{cle}</code> {fmt(v.apercu)} → {fmt(v.publie)}{' '}
          {/each}
          — à regarder, une copie ne doit rien changer.
        </p>
      {/if}
      <p class="muted">
        Prochaine étape, hors atelier : <code>cd public &amp;&amp; npm run build</code>, puis mise en ligne.
      </p>
    {:else}
      <p class="muted">
        Aucun snapshot dans <code>{publie.repertoire}</code>. Générer un aperçu, puis publier.
      </p>
    {/if}
  </section>

  <!-- ② L'aperçu ----------------------------------------------------------- -->
  <section class="carte">
    <header>
      <h2>② Aperçu brouillon</h2>
      <div class="actions">
        {#if brouillon.existe}
          <span class="tag ok">aperçu généré</span>
        {:else}
          <span class="tag neutre">aucun aperçu</span>
        {/if}
        {#if peutAgir}
          <button class="primary" on:click={genererApercu} disabled={generating || publishing}>
            {generating ? 'Génération…' : 'Générer un aperçu'}
          </button>
        {/if}
      </div>
    </header>

    <p class="muted">
      Construit dans <code>{brouillon.repertoire}</code> — rien de servi n’est touché
      à cette étape.
    </p>

    {#if !brouillon.existe}
      <p class="muted">Aucun aperçu pour l’instant.</p>
    {:else}
      <p class="ligne">
        Généré le <strong>{date(brouillon.genere_le)}</strong>
        {#if brouillon.genere_par}par <strong>{brouillon.genere_par}</strong>{/if}
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

      <!-- Le site public lui-même, branché sur le brouillon. -->
      <div class="apercu">
        <div class="apercu-barre">
          <strong>Prévisualisation</strong>
          {#if apercu.actif}
            <span class="tag ok">en marche · {apercu.url}</span>
          {:else if !apercu.installe}
            <span class="tag ko">dépendances du site absentes</span>
          {:else}
            <span class="tag neutre">arrêtée</span>
          {/if}
          {#if peutAgir}
            {#if apercu.actif}
              <button class="secondary" on:click={() => serveurApercu('arreter')} disabled={serveurEnCours}>
                Arrêter
              </button>
            {:else}
              <button class="secondary" on:click={() => serveurApercu('demarrer')}
                      disabled={serveurEnCours || !apercu.installe}>
                {serveurEnCours ? 'Construction…' : 'Construire et ouvrir l’aperçu'}
              </button>
            {/if}
          {/if}
          {#if apercu.actif}
            <a class="lien" href={apercu.url} target="_blank" rel="noreferrer">
              Ouvrir l’aperçu ↗
            </a>
          {/if}
        </div>

        {#if !apercu.installe}
          <p class="muted">
            L’aperçu fait tourner le site public lui-même :
            <code>cd public &amp;&amp; npm install</code> une fois, puis il démarre d’ici.
          </p>
        {:else if apercu.actif}
          <!-- L'aperçu s'ouvre dans un onglet, il ne s'encadre plus.
               L'iframe était pilotée des DEUX côtés : les puces changeaient son
               `src`, mais naviguer dans le site embarqué ne les mettait pas à
               jour — impossible, l'aperçu tourne sur un autre port, donc une
               autre origine. Cliquer sur « Où va l'argent » dans le site laissait
               la puce sur « Accueil », « Ouvrir dans un onglet » pointait
               toujours la racine, et recliquer sur Accueil ne faisait rien
               puisque la valeur était déjà `/`. Le cadre et son contenu ne
               racontaient plus la même chose.

               Un onglet à part règle les trois : la navigation appartient au
               site, l'atelier n'en garde que les portes d'entrée. -->
          <p class="cadre-bandeau">
            APERÇU ATELIER — snapshot brouillon, non publié. C’est le
            <strong>build statique</strong> du site, celui qui partira en ligne,
            construit sur <code>{brouillon.repertoire}</code>.
            {#if apercu.build?.pages}({apercu.build.pages} pages, construites le
            {date(apercu.build.construit_le)}){/if}
            Il s’ouvre dans un onglet séparé : la navigation y appartient au site.
          </p>
          <div class="apercu-liens">
            {#each LIENS_APERCU as l}
              <a class="puce" href={apercu.url + l.chemin} target="_blank"
                 rel="noreferrer">{l.label} ↗</a>
            {/each}
            {#if modifications?.modifications?.length}
              <span class="separateur">fiches modifiées :</span>
              {#each modifications.modifications.slice(0, 8) as m}
                {#if m.dans_apercu}
                  <a class="puce" href={`${apercu.url}/entite/${m.id}`} target="_blank"
                     rel="noreferrer"
                     title="{m.modifications} modification(s), dernière le {m.derniere}">
                    {m.name} ↗
                  </a>
                {/if}
              {/each}
            {/if}
          </div>
        {:else}
          <p class="muted">
            La prévisualisation <strong>construit</strong> le site public sur le
            brouillon — les mêmes pages que celles qui partiront en ligne, passées
            par le même contrôle de build — puis les sert sur son propre port.
            Compter une poignée de secondes. Rien n’est copié.
          </p>
        {/if}
      </div>
    {/if}
  </section>

  <!-- ③ Les contrôles ------------------------------------------------------ -->
  <section class="carte">
    <header>
      <h2>③ Contrôles d’étanchéité</h2>
      {#if !controle}
        <span class="tag neutre">pas encore passés</span>
      {:else if controle.ok}
        <span class="tag ok">verts</span>
      {:else}
        <span class="tag ko">{fmt(controle.compte_erreurs)} violation(s)</span>
      {/if}
    </header>

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
          Publication bloquée. Ces violations sont ce que le contrôleur — écrit
          comme un adversaire du générateur — refuse de laisser sortir.
        </p>
      {/if}

      {#if controle.erreurs?.length || controle.avertissements?.length}
        <button class="secondary" on:click={() => (controleDeplie = !controleDeplie)}>
          {controleDeplie ? 'Masquer le détail' : 'Voir les erreurs'}
        </button>
      {/if}

      {#if controleDeplie}
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
  </section>

  <!-- ④ Publier ------------------------------------------------------------ -->
  <section class="carte">
    <header>
      <h2>④ Publier</h2>
      {#if etape === 'en_ligne'}<span class="tag ok">en ligne, vérifié</span>
      {:else if promu}<span class="tag attente">promu, pas encore vérifié en ligne</span>{/if}
    </header>

    {#if !peutAgir}
      <p class="muted">
        Publier est réservé au rôle admin. L’état ci-dessus et l’aperçu restent
        consultables.
      </p>
    {:else if etape === 'aucun_apercu'}
      <p class="muted">Générer un aperçu d’abord.</p>
    {:else if etape === 'controles_en_echec'}
      <p class="alerte">
        Contrôles rouges — le bouton n’est pas proposé. Corriger dans l’atelier,
        puis regénérer un aperçu.
      </p>
    {:else if promu}
      <p class="muted">
        Cet aperçu est en place dans <code>{publie.repertoire}</code> et dans
        <code>{etat.site?.repertoire}</code>. Regénérer un aperçu pour prendre en
        compte des corrections plus récentes.
      </p>
    {:else}
      <p class="ligne">
        L’aperçu du {date(brouillon.genere_le)} est contrôlé. Publier construit
        chaque copie <em>à côté</em> de ce qui est servi, la contrôle, puis la met
        en service d’un seul geste — <code>{publie.repertoire}</code> puis
        <code>{etat.site?.repertoire}</code>. Un refus laisse la version
        précédente entière et servie.
      </p>
    {/if}

    {#if peutPublier}
      <button class="danger" on:click={publier} disabled={publishing || generating}>
        {publishing ? 'Publication…' : 'Publier ce snapshot'}
      </button>
    {/if}
  </section>

  <!-- ⑤ En ligne ----------------------------------------------------------- -->
  <!-- L'étape que l'atelier ne fait PAS, et qu'il ne peut donc que constater :
       entre la promotion locale et le site public il y a un build et un
       déploiement. Tant que personne n'a interrogé le site, « déployé » est une
       supposition — et la page l'affichait comme un fait. -->
  {#if promu}
  <section class="carte">
    <header>
      <h2>⑤ En ligne</h2>
      {#if enLigne.ok}<span class="tag ok">vérifié</span>
      {:else if enLigne.verifie_le}<span class="tag ko">pas à jour</span>
      {:else}<span class="tag attente">non vérifié</span>{/if}
    </header>

    <p class="ligne">
      Promouvoir écrit dans les répertoires de cette machine. Le site public,
      lui, sert ce que le dernier <strong>build</strong> et le dernier
      <strong>déploiement</strong> y ont mis. Ces deux gestes ne sont pas faits
      d’ici : cette carte se contente de constater.
    </p>

    <div class="ligne">
      <span class="etiq">Adresse publique</span>
      {#if urlPublique}
        <a class="lien" href={urlPublique} target="_blank" rel="noreferrer">{urlPublique} ↗</a>
      {:else}
        <em class="muted">aucune déclarée (<code>site_url</code> dans <code>config/instance.json</code>)</em>
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

    {#if peutAgir}
      <button class="secondary" on:click={verifierEnLigne} disabled={verifying}>
        {verifying ? 'Vérification…' : 'Vérifier ce qui est en ligne'}
      </button>
      {#if publie.existe}
        <button class="secondary" on:click={revenir} disabled={publishing || generating}>
          Revenir à la version précédente
        </button>
      {/if}
    {/if}
  </section>
  {/if}

  <section class="carte regles">
    <h2>Règles de publication actives</h2>
    <div class="puces">
      <span>confiance : {(etat.rules?.public_confidence || []).join(', ') || '—'}</span>
      <span>relations : {(etat.rules?.public_relation_types || []).length}</span>
      <span>rôles personnes : {(etat.rules?.public_person_relation_types || []).length}</span>
      <span>sources événements : {(etat.rules?.public_event_sources || []).join(', ') || '—'}</span>
      <span>règles : <code>{etat.rules_path}</code></span>
    </div>
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
      <button class="secondary" on:click={exporter} disabled={occupe || !estAdmin}>
        {occupe === 'export' ? 'Export…' : 'Exporter mes décisions'}
      </button>
      <button class="secondary" on:click={() => importer(false)} disabled={occupe || !estAdmin}>
        {occupe === 'blanc' ? 'Lecture…' : 'Lire un import (à blanc)'}
      </button>
      <button class="primary" on:click={() => importer(true)} disabled={occupe || !estAdmin}>
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

  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: .9rem;
  }

  .eyebrow {
    font-size: .72rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .04em;
    margin-bottom: .25rem;
  }

  h1 { font-size: 1.25rem; font-weight: 700; display: flex; align-items: center; gap: .55rem; }
  h2 { font-size: .95rem; font-weight: 700; }
  h3 { font-size: .78rem; color: #93c5fd; margin: .55rem 0 .25rem; }

  .auth { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; justify-content: flex-end; }

  input {
    width: 200px;
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

  button:disabled { opacity: .45; cursor: default; }
  .primary { background: #2563eb; color: white; }
  .secondary { background: #334155; color: #e2e8f0; }
  .danger { background: #b91c1c; color: #fee2e2; }
  .ghost { color: #94a3b8; }

  .badge, .tag {
    font-size: .7rem;
    font-weight: 700;
    border-radius: 999px;
    padding: .15rem .6rem;
    text-transform: uppercase;
    letter-spacing: .03em;
  }

  .neutre { background: #1e293b; color: #94a3b8; border: 1px solid #334155; }
  .ok { background: #052e1a; color: #6ee7b7; border: 1px solid #065f46; }
  .ko { background: #450a0a; color: #fecaca; border: 1px solid #991b1b; }

  .pipeline {
    display: flex;
    gap: .4rem;
    list-style: none;
    margin: 0 0 1rem;
    padding: 0;
    flex-wrap: wrap;
  }

  .pipeline li {
    flex: 1 1 160px;
    display: flex;
    align-items: center;
    gap: .45rem;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: .5rem .7rem;
    font-size: .8rem;
    color: #94a3b8;
  }

  .pipeline li.courant { border-color: #2563eb; color: #e2e8f0; background: #172554; }

  .pipeline .num {
    display: inline-grid;
    place-items: center;
    width: 1.2rem;
    height: 1.2rem;
    border-radius: 999px;
    background: #0f172a;
    font-size: .7rem;
    font-weight: 700;
  }

  .carte {
    background: #1e293b;
    border: 1px solid #334155;
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

  .ligne { font-size: .84rem; color: #cbd5e1; margin-bottom: .5rem; }
  .muted { color: #94a3b8; font-size: .8rem; }

  .alerte {
    background: #450a0a;
    border: 1px solid #991b1b;
    color: #fecaca;
    border-radius: 6px;
    padding: .5rem .65rem;
    font-size: .82rem;
    margin: .5rem 0;
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

  .error pre, .bloc pre {
    white-space: pre-wrap;
    background: #020617;
    border-radius: 6px;
    padding: .5rem;
    margin-top: .5rem;
    font-size: .74rem;
    color: #cbd5e1;
    max-height: 22rem;
    overflow: auto;
  }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .6rem;
    margin: .6rem 0;
  }

  .metric { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: .7rem; }
  .metric span { display: block; font-size: 1.35rem; font-weight: 750; color: #bfdbfe; }
  .metric small { display: block; color: #e2e8f0; font-size: .76rem; }
  .metric em { display: block; color: #64748b; font-size: .7rem; font-style: normal; margin-top: .2rem; }

  .bloc { margin-top: .6rem; }
  .bloc summary { cursor: pointer; color: #93c5fd; font-size: .8rem; }

  .grille { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: .6rem; }
  table { width: 100%; border-collapse: collapse; }
  td { border-bottom: 1px solid #334155; padding: .3rem 0; font-size: .76rem; color: #cbd5e1; }
  td:first-child { color: #94a3b8; padding-right: .6rem; }
  td:last-child { text-align: right; font-weight: 700; }

  code {
    background: #0f172a;
    padding: 1px 5px;
    border-radius: 4px;
    color: #cbd5e1;
    font-size: .75rem;
  }

  .champ { color: #fbbf24; }

  .regle { border-left: 2px solid #334155; padding-left: .7rem; margin: .7rem 0; }
  .regle.bloquante { border-left-color: #b91c1c; }
  .regle ul { list-style: none; padding: 0; margin: 0; }
  .regle li {
    font-size: .78rem;
    color: #cbd5e1;
    padding: .22rem 0;
    border-bottom: 1px solid #1e293b;
    display: flex;
    gap: .4rem;
    flex-wrap: wrap;
    align-items: baseline;
  }

  .lien { color: #93c5fd; font-size: .76rem; text-decoration: underline; }

  .apercu { margin-top: .8rem; border-top: 1px solid #334155; padding-top: .7rem; }

  .apercu-barre {
    display: flex;
    align-items: center;
    gap: .5rem;
    flex-wrap: wrap;
    margin-bottom: .5rem;
    font-size: .84rem;
    color: #e2e8f0;
  }

  .apercu-liens { display: flex; gap: .35rem; flex-wrap: wrap; margin-bottom: .5rem; align-items: center; }

  .puce {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 999px;
    padding: .2rem .6rem;
    color: #cbd5e1;
    font-size: .74rem;
    font-weight: 600;
  }

  .puce { text-decoration: none; }

  /* Promu localement sans constatation en ligne : ni vert (ce serait affirmer
     un déploiement), ni rouge (rien n'a échoué). */
  .attente { background: #422006; color: #fdba74; border: 1px solid #b45309; }
  .etiq { display: inline-block; min-width: 11rem; color: #94a3b8; font-size: .8rem; }
  .separateur { color: #64748b; font-size: .72rem; margin-left: .35rem; }

  /* Le bandeau reste dans l'ATELIER, jamais dans le site : l'aperçu doit
     montrer le site publié, pas un site décoré pour l'occasion. */
  .cadre-bandeau {
    background: #b45309;
    color: #fff7ed;
    font-size: .74rem;
    font-weight: 700;
    padding: .35rem .6rem;
    margin: 0 0 .5rem;
    border-radius: 6px;
    letter-spacing: .02em;
  }

  .cadre-bandeau code { background: #78350f; color: #fed7aa; }

  .regles .puces { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .4rem; }

  .regles .puces span {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 999px;
    padding: .2rem .55rem;
    color: #cbd5e1;
    font-size: .74rem;
  }

  @media (max-width: 900px) {
    .topbar { align-items: stretch; flex-direction: column; }
    .auth { justify-content: flex-start; }
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  .sync-ok { color: #6ee7b7; margin: 0 0 .35rem; font-size: .9rem; }

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
