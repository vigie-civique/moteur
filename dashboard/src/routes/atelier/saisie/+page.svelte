<script>
  // Saisie manuelle — ce qu'aucun collecteur ne peut deviner.
  //
  // 49 % des flux financiers de la production sont saisis à la main, dans onze
  // scripts Python écrits pour une commune et jamais rejoués ailleurs. Le budget
  // primitif voté n'existe que dans les comptes rendus du conseil : le détail
  // DGFiP s'arrête à 2023, les agrégats OFGL à 2024. Sans cette page, ce travail
  // se refait en écrivant du Python — ce qu'aucun repreneur ne fera.
  //
  // Ce qui est saisi ici part dans config/saisies.json et non directement en
  // base : le collecteur `saisies` le rejoue à chaque collecte, donc une
  // reconstruction complète de la base ne l'efface pas.
  import { api } from '$lib/api.js'

  let contrat = {}          // {objet: {champ*: [genre, aide]}}
  let confiances = []
  let objet = 'flux'
  let valeurs = {}
  let confidence = 'confirmed'
  let erreur = ''
  let succes = ''
  let envoi = false

  // ─── Source ────────────────────────────────────────────────────────────────
  // Obligatoire. Les procès-verbaux 2017-2019 de la commune ont disparu du site
  // de la mairie : une URL ne prouve plus rien une fois la page retirée. On
  // s'adosse donc à un document archivé sur le disque — ou l'on explique
  // pourquoi il n'y en a pas, et cette explication est publiée avec la ligne.
  let documents = []
  let rechercheDoc = ''
  let docChoisi = null
  let sansDocumentMotif = ''
  let citation = ''
  let fichierEnCours = false

  let saisies = []

  // ─── Extraction assistée ───────────────────────────────────────────────────
  // Le modèle ne saisit rien : il lit un acte déjà en base et propose des
  // lignes, que l'on reprend une par une dans le formulaire. Chaque proposition
  // porte la phrase du texte qui la justifie, et le serveur a vérifié que cette
  // phrase existe vraiment — une ligne marquée « citation introuvable » est le
  // signe qu'il a brodé.
  let iaDispo = { configuree: false }
  let actes = []
  let acteChoisi = null
  let rechercheActe = ''
  let propositions = null
  let iaEnCours = false

  $: actesFiltres = rechercheActe
      ? actes.filter(a => `${a.date} ${a.title || ''}`.toLowerCase()
                           .includes(rechercheActe.toLowerCase()))
      : actes
  $: objetExtractible = ['flux', 'acte', 'marche', 'budget_vote'].includes(objet)

  async function chargerActes() {
    try {
      const r = await api.donnees('deliberation', '', 300)
      actes = (r || []).filter(a => a.excerpt)
    } catch { actes = [] }
  }

  async function proposer() {
    if (!acteChoisi) return
    iaEnCours = true; erreur = ''; propositions = null
    try {
      propositions = await api.iaExtraire(objet, { event_id: acteChoisi.id })
      if (propositions.source?.raw_document_id && !docChoisi) {
        docChoisi = documents.find(d => d.id === propositions.source.raw_document_id)
            || { id: propositions.source.raw_document_id,
                 title: propositions.source.titre }
      }
    } catch (e) {
      erreur = e.message
    } finally {
      iaEnCours = false
    }
  }

  // Reprendre une proposition = remplir le formulaire, pas enregistrer. Le
  // dernier geste reste humain, y compris quand la citation est vérifiée.
  function reprendre(p) {
    const v = { ...p }
    delete v.citation
    delete v.citation_verifiee
    if (objet === 'flux' && v.tiers_nom) {
      // Le modèle donne un nom, jamais un type : « Champ contre Champ » existe
      // dans cette base en entreprise ET en association. On lance la recherche
      // et on laisse choisir.
      rechercheEntite['tiers'] = v.tiers_nom
      delete v.tiers_nom
      chercherEntite('tiers')
    }
    valeurs = v
    citation = p.citation || ''
    // Une ligne reprise d'un modèle n'est pas une ligne lue par un humain :
    // elle part en `probable` tant que personne n'a rouvert la source.
    confidence = p.citation_verifiee ? 'confirmed' : 'probable'
    succes = 'Proposition reprise — à relire avant d\'enregistrer.'
  }

  $: champsDuType = Object.entries(contrat[objet] || {})
      .filter(([cle]) => !cle.startsWith('_'))
  $: libelleObjet = (contrat[objet] || {})._libelle || objet
  $: sourceOk = !!docChoisi || sansDocumentMotif.trim().length > 2

  async function charger() {
    try {
      const c = await api.saisiesChamps()
      contrat = c.objets || {}
      confiances = c.confiances || []
      documents = await api.documents('', 30)
      await chargerSaisies()
      iaDispo = await api.iaConfig()
      if (iaDispo.configuree) chargerActes()
    } catch (e) {
      erreur = e.message
    }
  }

  async function chargerSaisies() {
    const r = await api.saisies()
    saisies = r.saisies || []
  }

  async function chercherDocs() {
    documents = await api.documents(rechercheDoc, 30)
  }

  async function deposer(event) {
    const fichier = event.target.files?.[0]
    if (!fichier) return
    fichierEnCours = true
    erreur = ''
    try {
      const r = await api.documentDeposer(fichier, fichier.name)
      documents = await api.documents('', 30)
      docChoisi = documents.find(d => d.id === r.id)
          || { id: r.id, title: fichier.name, source: 'atelier' }
      succes = r.deja_present
        ? 'Ce document était déjà archivé — il est réutilisé, pas dupliqué.'
        : 'Document archivé.'
    } catch (e) {
      erreur = e.message
    } finally {
      fichierEnCours = false
      event.target.value = ''
    }
  }

  // Le champ « entité » ne devine jamais le type d'après le nom : dans cette
  // base, « Champ contre Champ » existe deux fois, une fois en entreprise et
  // une fois en association. On choisit dans la recherche, ou on déclare.
  let rechercheEntite = {}
  let suggestions = {}

  async function chercherEntite(champ) {
    const q = (rechercheEntite[champ] || '').trim()
    if (q.length < 2) { suggestions[champ] = []; return }
    const r = await api.search(q, 8)
    suggestions[champ] = r.results || r || []
  }

  function choisirEntite(champ, e) {
    valeurs[champ] = { id: e.id }
    rechercheEntite[champ] = e.name
    suggestions[champ] = []
  }

  function declarerEntite(champ, type) {
    valeurs[champ] = { nom: rechercheEntite[champ], type }
    suggestions[champ] = []
  }

  function reinitialiser() {
    valeurs = {}
    citation = ''
    rechercheEntite = {}
    suggestions = {}
  }

  async function enregistrer() {
    envoi = true; erreur = ''; succes = ''
    try {
      const source = { citation }
      if (docChoisi) source.raw_document_id = docChoisi.id
      else source.sans_document_motif = sansDocumentMotif
      const r = await api.saisieCreer(objet, valeurs, source, confidence)
      succes = `${libelleObjet} enregistré — ${r.import?.ecrites ?? 0} ligne(s) écrite(s) en base.`
      reinitialiser()
      await chargerSaisies()
    } catch (e) {
      erreur = e.message
    } finally {
      envoi = false
    }
  }

  async function retirer(id) {
    erreur = ''
    try {
      await api.saisieRetirer(id)
      await chargerSaisies()
      succes = 'Saisie retirée — la ligne a disparu de la base.'
    } catch (e) {
      erreur = e.message
    }
  }

  function fmtOctets(n) {
    if (!n) return ''
    return n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.round(n / 1024)} Ko`
  }

  charger()
</script>

<div class="saisie">
  <header class="top">
    <h1>Saisir une donnée</h1>
    <p class="sub">
      Ce qu'aucun collecteur ne peut atteindre : un budget voté, une dotation
      notifiée, une subvention lue dans un compte rendu. La saisie n'écrase
      jamais une ligne existante — elle en ajoute une, marquée « atelier », et
      part dans <code>config/saisies.json</code> pour être rejouée à chaque
      collecte.
    </p>
  </header>

  {#if erreur}<div class="err">{erreur}</div>{/if}
  {#if succes}<div class="ok">{succes}</div>{/if}

  <div class="layout">
    <section class="form">
      <div class="tabs">
        {#each Object.entries(contrat) as [cle, def]}
          <button class:active={objet === cle}
                  on:click={() => { objet = cle; reinitialiser() }}>
            {def._libelle || cle}
          </button>
        {/each}
      </div>

      {#if iaDispo.configuree && objetExtractible}
        <details class="ia">
          <summary>
            Lire un compte rendu avec le modèle
            <em class="modele">
              {iaDispo.modele}
              {#if iaDispo.locale}· sur cette machine, rien ne sort{:else}· service distant{/if}
            </em>
          </summary>

          <p class="hint">
            Le modèle ne saisit rien : il propose des lignes, chacune avec la
            phrase du compte rendu qui la justifie. Le serveur vérifie que cette
            phrase existe vraiment dans le texte — c'est ce qui permet de repérer
            une invention sans rouvrir le PDF.
          </p>

          <div class="acte-choix">
            <input type="text" placeholder="chercher un compte rendu…"
                   bind:value={rechercheActe} />
            <button class="mini" on:click={proposer}
                    disabled={!acteChoisi || iaEnCours}>
              {iaEnCours ? 'Lecture…' : 'Proposer'}
            </button>
          </div>

          {#if acteChoisi}
            <p class="hint choisi">
              ↳ {acteChoisi.date} · {acteChoisi.title || 'sans titre'}
              <button class="mini" on:click={() => (acteChoisi = null)}>changer</button>
            </p>
          {:else}
            <ul class="documents">
              {#each actesFiltres.slice(0, 8) as a}
                <li><button on:click={() => (acteChoisi = a)}>
                  {a.date} — {(a.title || a.excerpt || '').slice(0, 70)}
                </button></li>
              {/each}
            </ul>
          {/if}

          {#if iaEnCours}
            <p class="hint">Un modèle local lit à son rythme — comptez une à
              plusieurs minutes par compte rendu.</p>
          {/if}

          {#if propositions}
            <div class="resultats">
              <p class="bilan">
                {propositions.propositions.length} proposition(s) ·
                <strong class="ok-c">{propositions.citations_verifiees} citation(s) retrouvée(s)</strong>
                {#if propositions.citations_introuvables}
                  · <strong class="ko-c">{propositions.citations_introuvables} introuvable(s)</strong>
                {/if}
                {#if propositions.reponses_illisibles}
                  · {propositions.reponses_illisibles} réponse(s) illisible(s)
                {/if}
              </p>
              {#if !propositions.propositions.length}
                <p class="hint">Rien trouvé dans ce compte rendu. Une liste vide
                  vaut mieux qu'une ligne incertaine — c'est ce qui est demandé
                  au modèle.</p>
              {/if}
              <ul class="propositions">
                {#each propositions.propositions as p}
                  <li class:doute={!p.citation_verifiee}>
                    <div class="prop-tete">
                      <span class="marque">{p.citation_verifiee ? '✓' : '✗ citation introuvable'}</span>
                      <button class="mini" on:click={() => reprendre(p)}>reprendre</button>
                    </div>
                    <p class="prop-corps">
                      {#each Object.entries(p) as [k, v]}
                        {#if !['citation', 'citation_verifiee'].includes(k)}
                          <span><b>{k}</b> {v}</span>
                        {/if}
                      {/each}
                    </p>
                    <p class="prop-citation">« {p.citation} »</p>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        </details>
      {/if}

      {#each champsDuType as [cle, spec]}
        {@const champ = cle.replace(/\*$/, '')}
        {@const genre = spec[0]}
        {@const aide = spec[1]}
        {@const requis = cle.endsWith('*')}
        <label class="field">
          <span>{aide}{#if requis}<em class="req">obligatoire</em>{/if}</span>

          {#if genre === 'entite'}
            <div class="entite">
              <input type="text" placeholder="chercher dans la base…"
                     bind:value={rechercheEntite[champ]}
                     on:input={() => chercherEntite(champ)} />
              {#if valeurs[champ]?.id}
                <p class="hint choisi">↳ entité existante #{valeurs[champ].id}</p>
              {:else if valeurs[champ]?.nom}
                <p class="hint choisi">↳ à créer : {valeurs[champ].nom} ({valeurs[champ].type})</p>
              {/if}
              {#if valeurs[champ]?.type === 'person'}
                <!-- Les aides aux particuliers (façades, ravalement) nomment des
                     personnes physiques. L'atelier les collecte — c'est sa
                     raison d'être — mais le site ne les publiera pas : ni la
                     fiche, ni le flux, ni le nom dans les libellés. Le dire
                     ici, sinon on croit avoir publié ce qu'on vient de saisir. -->
                <p class="hint prive">
                  ⚠ Personne physique : cette ligne restera dans l'atelier. Le
                  site ne publie ni sa fiche, ni le flux qui la nomme — seuls
                  les rôles civiques (élu, candidat, membre de commission)
                  ouvrent la publication.
                </p>
              {/if}
              {#if suggestions[champ]?.length}
                <ul class="suggestions">
                  {#each suggestions[champ] as s}
                    <li><button on:click={() => choisirEntite(champ, s)}>
                      {s.name} <em>{s.type}</em>
                    </button></li>
                  {/each}
                </ul>
              {:else if (rechercheEntite[champ] || '').length > 2 && !valeurs[champ]}
                <p class="hint">
                  Absente de la base ? La créer comme :
                  {#each ['association', 'business', 'person', 'service'] as t}
                    <button class="mini" on:click={() => declarerEntite(champ, t)}>{t}</button>
                  {/each}
                </p>
              {/if}
            </div>

          {:else if genre.startsWith('choix:')}
            <select bind:value={valeurs[champ]}>
              <option value="">— non renseigné</option>
              {#each genre.slice(6).split(',') as opt}
                <option value={opt}>{opt}</option>
              {/each}
            </select>

          {:else if genre === 'montant'}
            <input type="number" step="0.01" bind:value={valeurs[champ]} />
          {:else if genre === 'annee'}
            <input type="number" step="1" bind:value={valeurs[champ]} />
          {:else if genre === 'date'}
            <input type="date" bind:value={valeurs[champ]} />
          {:else if genre === 'texte'}
            <textarea rows="2" bind:value={valeurs[champ]}></textarea>
          {:else}
            <input type="text" bind:value={valeurs[champ]} />
          {/if}
        </label>
      {/each}

      <div class="field source" class:manque={!sourceOk}>
        <span>Source <em class="req">obligatoire</em></span>
        <p class="hint">
          Une saisie sans document n'est pas défendable : les PV 2017-2019 de la
          commune ont disparu du site de la mairie, et seule une copie locale les
          rend encore opposables.
        </p>

        <div class="doc-recherche">
          <input type="text" placeholder="chercher un document archivé…"
                 bind:value={rechercheDoc} on:input={chercherDocs} />
          <label class="depot">
            {fichierEnCours ? 'Dépôt…' : 'Déposer un fichier'}
            <input type="file" on:change={deposer} hidden />
          </label>
        </div>

        {#if docChoisi}
          <p class="hint choisi">
            ↳ {docChoisi.title || docChoisi.url || `document #${docChoisi.id}`}
            <a href={api.documentUrl(docChoisi.id)} target="_blank" rel="noopener">↗ relire</a>
            <button class="mini" on:click={() => (docChoisi = null)}>changer</button>
          </p>
        {:else}
          <ul class="documents">
            {#each documents.slice(0, 8) as d}
              <li>
                <button on:click={() => (docChoisi = d)}>
                  {d.title || d.url || `#${d.id}`}
                  <em>{d.doc_type} · {d.source} · {fmtOctets(d.byte_size)}</em>
                </button>
              </li>
            {/each}
          </ul>
          <label class="soupape">
            <span>Aucun document possible ? Dire pourquoi — ce motif sera publié avec la ligne.</span>
            <input type="text" bind:value={sansDocumentMotif}
                   placeholder="ex. registre consulté en mairie, non communiqué" />
          </label>
        {/if}

        <label class="citation">
          <span>Passage exact de la source (facultatif, mais c'est lui qui rend la ligne vérifiable)</span>
          <textarea rows="2" bind:value={citation}></textarea>
        </label>
      </div>

      <label class="field">
        <span>Fiabilité</span>
        <select bind:value={confidence}>
          {#each confiances as c}<option value={c}>{c}</option>{/each}
        </select>
        <p class="hint">
          <code>confirmed</code> est publié sur le site. <code>probable</code> reste
          dans l'atelier — pour un chiffre dont on doute encore.
        </p>
      </label>

      <button class="save" on:click={enregistrer} disabled={envoi || !sourceOk}>
        {envoi ? 'Enregistrement…' : `Enregistrer ce ${libelleObjet.toLowerCase()}`}
      </button>
      {#if !sourceOk}
        <p class="hint bloque">Choisir un document, en déposer un, ou expliquer son absence.</p>
      {/if}
    </section>

    <aside class="liste">
      <h2>Saisies enregistrées <span class="compte">{saisies.length}</span></h2>
      {#if !saisies.length}
        <p class="muted">Rien encore. Ce qui sera saisi ici survit à une
          reconstruction complète de la base.</p>
      {:else}
        <ul>
          {#each saisies as s (s.id)}
            <li>
              <div class="ligne">
                <strong>{(contrat[s.objet] || {})._libelle || s.objet}</strong>
                <button class="mini danger" on:click={() => retirer(s.id)}>retirer</button>
              </div>
              <p class="detail">
                {#each Object.entries(s.valeurs || {}).slice(0, 3) as [k, v]}
                  <span>{k} : {typeof v === 'object' ? (v.nom || `#${v.id}`) : v}</span>
                {/each}
              </p>
              <p class="meta">
                {s.saisi_par} · {(s.saisi_le || '').slice(0, 10)}
                {#if s.source?.sans_document_motif}
                  · <em class="sans-doc">sans document : {s.source.sans_document_motif}</em>
                {:else if s.source?.raw_document_id}
                  · <a href={api.documentUrl(s.source.raw_document_id)} target="_blank" rel="noopener">source</a>
                {/if}
              </p>
            </li>
          {/each}
        </ul>
      {/if}
    </aside>
  </div>
</div>

<style>
  .saisie { padding: 1.25rem 1.5rem; height: 100%; overflow-y: auto; color: #e2e8f0; }
  .top h1 { font-size: 1.4rem; margin: 0; }
  .sub { color: #94a3b8; font-size: .85rem; max-width: 78ch; margin: .35rem 0 1rem; line-height: 1.5; }
  code { background: #0f172a; padding: 0 .25rem; border-radius: 3px; font-size: .9em; }

  .err { background: #7f1d1d; color: #fecaca; padding: .5rem .75rem; border-radius: 6px; margin-bottom: .75rem; font-size: .85rem; }
  .ok  { background: #065f46; color: #d1fae5; padding: .5rem .75rem; border-radius: 6px; margin-bottom: .75rem; font-size: .85rem; }

  .layout { display: grid; grid-template-columns: 1fr 320px; gap: 1.25rem; align-items: start; }
  .form { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 1rem; }

  .tabs { display: flex; gap: .25rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .tabs button { padding: .4rem .8rem; border-radius: 6px; background: #1e293b; color: #94a3b8; font-size: .82rem; }
  .tabs button.active { background: #3b82f6; color: #fff; }

  .field { display: block; margin-bottom: .9rem; }
  .field > span { display: block; font-size: .78rem; color: #94a3b8; margin-bottom: .25rem; }
  .req { color: #f59e0b; font-style: normal; font-size: .68rem; text-transform: uppercase;
         letter-spacing: .03em; margin-left: .4rem; }
  input, select, textarea {
    width: 100%; background: #0b1220; border: 1px solid #334155; border-radius: 6px;
    color: #e2e8f0; padding: .4rem .55rem; font: inherit; font-size: .85rem;
  }
  input::placeholder, textarea::placeholder { color: #475569; }

  .hint { color: #64748b; font-size: .74rem; line-height: 1.45; margin: .3rem 0 0; }
  .hint.choisi { color: #34d399; }
  .hint.prive { color: #fbbf24; border-left: 2px solid #b45309;
                padding-left: .5rem; margin-top: .35rem; }
  .hint.bloque { color: #f59e0b; text-align: center; }

  .suggestions, .documents { list-style: none; margin: .35rem 0 0; padding: 0;
                             border: 1px solid #1e293b; border-radius: 6px; overflow: hidden; }
  .suggestions li button, .documents li button {
    display: block; width: 100%; text-align: left; padding: .35rem .55rem;
    background: #0b1220; color: #cbd5e1; font-size: .8rem;
  }
  .suggestions li button:hover, .documents li button:hover { background: #1e293b; }
  .suggestions em, .documents em { color: #64748b; font-style: normal; font-size: .72rem; margin-left: .4rem; }

  .mini { display: inline-block; width: auto; padding: .1rem .5rem; margin-left: .3rem;
          border-radius: 4px; background: #1e293b; color: #cbd5e1; font-size: .72rem; }
  .mini.danger { background: #7f1d1d; color: #fecaca; }

  .ia { border: 1px solid #334155; border-radius: 8px; padding: .6rem .7rem;
        background: #0b1220; margin-bottom: 1rem; }
  .ia summary { cursor: pointer; font-size: .85rem; color: #cbd5e1; }
  .modele { color: #64748b; font-style: normal; font-size: .72rem; margin-left: .4rem; }
  .acte-choix { display: flex; gap: .4rem; margin-top: .5rem; }
  .acte-choix input { flex: 1; }
  .resultats { margin-top: .7rem; border-top: 1px solid #1e293b; padding-top: .6rem; }
  .bilan { font-size: .78rem; color: #94a3b8; margin: 0 0 .5rem; }
  .ok-c { color: #34d399; } .ko-c { color: #f87171; }
  .propositions { list-style: none; margin: 0; padding: 0; }
  .propositions li { border: 1px solid #1e293b; border-radius: 6px; padding: .45rem .55rem;
                     margin-bottom: .4rem; }
  .propositions li.doute { border-color: #7f1d1d; background: #1a0f0f; }
  .prop-tete { display: flex; justify-content: space-between; align-items: center; }
  .prop-tete .marque { font-size: .72rem; color: #34d399; }
  .propositions li.doute .marque { color: #f87171; }
  .prop-corps { margin: .25rem 0; font-size: .78rem; color: #e2e8f0;
                display: flex; flex-wrap: wrap; gap: .1rem .8rem; }
  .prop-corps b { color: #64748b; font-weight: 600; font-size: .7rem;
                  text-transform: uppercase; letter-spacing: .03em; margin-right: .2rem; }
  .prop-citation { margin: 0; font-size: .74rem; color: #94a3b8; font-style: italic;
                   line-height: 1.4; }

  .source { border: 1px solid #334155; border-radius: 8px; padding: .7rem; background: #0b1220; }
  .source.manque { border-color: #b45309; }
  .doc-recherche { display: flex; gap: .4rem; align-items: center; }
  .depot { flex: 0 0 auto; padding: .4rem .7rem; border-radius: 6px; background: #1e293b;
           color: #cbd5e1; font-size: .78rem; cursor: pointer; white-space: nowrap; }
  .soupape { display: block; margin-top: .5rem; }
  .soupape span { display: block; font-size: .72rem; color: #64748b; margin-bottom: .2rem; }
  .citation { display: block; margin-top: .6rem; }
  .citation span { display: block; font-size: .72rem; color: #64748b; margin-bottom: .2rem; }

  .save { width: 100%; padding: .6rem; border-radius: 6px; background: #2563eb; color: #fff;
          font-weight: 600; margin-top: .5rem; }
  .save:disabled { opacity: .45; }

  .liste { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: .9rem;
           position: sticky; top: 0; max-height: 88vh; overflow-y: auto; }
  .liste h2 { font-size: .95rem; margin: 0 0 .6rem; }
  .compte { background: #334155; border-radius: 999px; padding: 0 .45rem; font-size: .72rem; }
  .liste ul { list-style: none; margin: 0; padding: 0; }
  .liste li { border-top: 1px solid #334155; padding: .5rem 0; }
  .ligne { display: flex; justify-content: space-between; align-items: center; font-size: .82rem; }
  .detail { margin: .2rem 0; font-size: .74rem; color: #94a3b8; display: flex; flex-direction: column; }
  .meta { margin: 0; font-size: .68rem; color: #64748b; }
  .sans-doc { color: #f59e0b; font-style: normal; }
  .muted { color: #64748b; font-size: .8rem; line-height: 1.5; }

  @media (max-width: 950px) { .layout { grid-template-columns: 1fr; } }
</style>
