<script>
  import { COMMUNE } from '$lib/instance.js'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins, messageErreur } from '$lib/roles.js'
  import { onMount } from 'svelte'

  let question  = ''
  let loading   = false
  let answer    = null
  let error     = ''
  let sources   = []
  let mode      = 'search'  // search | ask — la recherche d'abord, cf. plus bas
  let config    = null      // {enabled, embed_model, chat_model, chunks}

  // L'interface annonçait « nomic-embed-text + Gemma 3 » en dur et proposait la
  // recherche quel que soit l'état réel : fonction désactivée, index jamais
  // construit et index prêt donnaient la même page, et la même erreur de
  // connexion incompréhensible. Les trois états sont maintenant distingués.
  async function lireConfig() {
    try {
      const r = await authFetch('/rag/config')
      if (r.ok) config = await r.json()
    } catch { /* API muette : la page le dira */ }
  }
  onMount(lireConfig)

  // ─── Brancher une IA (admin) ────────────────────────────────────────────
  // Un modèle LOCAL seulement, choisi dans la liste que l'Ollama de la machine
  // annonce : ni adresse ni clé à saisir. Un service distant enverrait des
  // extraits de la base de travail chez un tiers — décision de serveur.
  let branchement = null    // état rendu par /admin/ia
  let choix = { modele: '', recherche: false }
  let enregistrement = false
  let avisBranchement = ''
  $: estAdmin = auMoins($currentUser, 'admin')
  $: if (estAdmin && branchement === null) lireBranchement()

  function recevoir(d) {
    branchement = d
    choix = { modele: d.reglage.modele || '', recherche: !!d.reglage.recherche }
  }
  async function lireBranchement() {
    branchement = undefined
    try {
      const r = await authFetch('/admin/ia')
      if (r.ok) recevoir(await r.json())
    } catch { /* la carte ne s'affiche pas */ }
  }
  async function brancher() {
    enregistrement = true; avisBranchement = ''
    try {
      const r = await authFetch('/admin/ia', {
        method: 'PUT',
        body: JSON.stringify({ modele: choix.modele || null, recherche: choix.recherche }),
      })
      const d = await r.json()
      if (!r.ok) { avisBranchement = messageErreur(d.detail); return }
      recevoir(d)
      avisBranchement = 'Enregistré.'
      await lireConfig()
    } finally { enregistrement = false }
  }

  const SOURCE_LABELS = {
    entity_notes:    'Note',
    events:          'Événement',
    financial_flows: 'Flux financier',
    entities:        'Entité',
  }

  function sourceLabel(s) { return SOURCE_LABELS[s] ?? s }

  async function submit() {
    if (!question.trim()) return
    loading = true; error = ''; answer = null; sources = []
    try {
      if (mode === 'ask') {
        const res = await authFetch('/rag/ask', {
          method: 'POST',
          body: JSON.stringify({ question, limit: 6 }),
        })
        if (!res.ok) throw new Error(await res.text())
        const data = await res.json()
        answer  = data.answer
        sources = data.sources ?? []
        if (data.error) error = data.error
      } else {
        const res = await authFetch(`/rag/search?q=${encodeURIComponent(question)}&limit=10`)
        if (!res.ok) throw new Error(await res.text())
        sources = await res.json()
      }
    } catch(e) { error = e.message }
    finally { loading = false }
  }

  function scoreColor(s) {
    if (s >= 0.85) return 'var(--succes)'
    if (s >= 0.70) return 'var(--alerte)'
    return 'var(--texte-doux)'
  }

  function onKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }
</script>

<svelte:head><title>IA — Atelier {COMMUNE}</title></svelte:head>

<div class="ia-page">
  <div class="page-header">
    <h1>Recherche par sens</h1>
    {#if config}
      <span class="muted">
        {config.embed_model}{#if config.chunks} · {config.chunks.toLocaleString('fr-FR')} extraits indexés{/if}
      </span>
    {/if}
  </div>

  {#if estAdmin && branchement}
    <details class="branchement" open={!config?.enabled && !branchement.ia.configuree}>
      <summary>
        Brancher une IA
        <span class="muted">
          {#if branchement.ia.configuree}{branchement.ia.modele}{:else}aucun modèle{/if}
          · recherche par sens {config?.enabled ? 'active' : 'éteinte'}
        </span>
      </summary>
      <p class="muted">
        Seul un modèle <strong>local</strong> se branche d'ici : il tourne sur la
        machine de l'atelier, rien n'en sort. Un service distant recevrait des
        extraits de la base de travail — des noms, des pistes non établies : cela
        se décide sur le serveur (<code>IA_URL</code> et <code>IA_HORS_MACHINE=1</code>
        dans <code>.env</code>), pas depuis cette page.
      </p>
      {#if !branchement.ollama.joignable}
        <p class="garde">
          Aucun Ollama ne répond sur cette machine (<code>{branchement.ollama.url}</code>) :
          il n'y a pas de modèle à brancher. Sur un serveur qui n'en porte pas, le
          travail du modèle se fait depuis un poste qui en a un, et arrive ici
          sous forme de propositions à relire.
        </p>
      {:else}
        <div class="champ">Modèle
          {#if branchement.serveur.ia}
            <span class="muted">réglé par le serveur : {branchement.ia.modele}</span>
          {:else}
            <select bind:value={choix.modele} aria-label="Modèle">
              <option value="">— aucun —</option>
              {#each branchement.ollama.modeles as m}<option value={m}>{m}</option>{/each}
            </select>
          {/if}
          <span class="muted">propose des lignes à la saisie d'un procès-verbal, et résume ici</span>
        </div>
        <label class="champ">
          <input type="checkbox" bind:checked={choix.recherche}
                 disabled={branchement.serveur.recherche || !branchement.recherche.embed_present} />
          Recherche par sens
          <span class="muted">
            {#if branchement.serveur.recherche}activée par le serveur
            {:else if !branchement.recherche.embed_present}demande <code>ollama pull {branchement.recherche.embed_model}</code>
            {:else}{(branchement.recherche.chunks || 0).toLocaleString('fr-FR')} extraits indexés{/if}
          </span>
        </label>
        <button class="btn-submit" on:click={brancher} disabled={enregistrement}>
          {enregistrement ? 'Enregistrement…' : 'Enregistrer'}
        </button>
      {/if}
      {#if avisBranchement}<span class="muted">{avisBranchement}</span>{/if}
    </details>
  {/if}

  <div class="mode-toggle">
    <button class:active={mode === 'search'} on:click={() => mode='search'}>Chercher</button>
    <button class:active={mode === 'ask'}    on:click={() => mode='ask'}>Faire résumer</button>
  </div>
  {#if mode === 'ask'}
    <!-- Mesuré le 15/08/2026 : à « combien la commune a-t-elle versé de
         subventions en 2024 », le modèle a répondu 350 € en résumant fidèlement
         les six extraits qu'on lui avait donnés. La base en comptait 56, pour
         445 213 €. Le résumé n'était pas faux, la question ne se répondait pas
         par ressemblance. L'avertissement est dans l'interface parce que la
         réponse, elle, a l'air sûre d'elle. -->
    <p class="garde">
      Un résumé de quelques extraits, pas une réponse. Sur une question qui
      demande un compte ou un total, il sera faux&nbsp;: le modèle ne voit que
      les extraits les plus ressemblants, jamais toutes les lignes. Pour compter,
      passer par les pages chiffrées.
    </p>
  {/if}

  <div class="search-box">
    <textarea
      bind:value={question}
      on:keydown={onKey}
      placeholder={mode === 'ask'
        ? "Ex : Quels élus ont des liens avec des associations subventionnées ?"
        : "Ex : Floutier vélo association"}
      rows="3"
      disabled={loading}
    ></textarea>
    <button class="btn-submit" on:click={submit} disabled={loading || !question.trim()}>
      {loading ? '…' : (mode === 'ask' ? 'Demander' : 'Chercher')}
    </button>
  </div>

  {#if error}
    <p class="err">{error}</p>
  {/if}

  {#if answer}
    <div class="answer-block">
      <div class="answer-header">Réponse {config?.chat_model ?? 'du modèle'} — à vérifier</div>
      <div class="answer-text">{answer}</div>
    </div>
  {/if}

  {#if sources.length > 0}
    <div class="sources-section">
      <h3 class="sources-title">
        {mode === 'ask' ? 'Sources utilisées' : 'Résultats'}
        <span class="count">{sources.length}</span>
      </h3>
      <div class="sources-list">
        {#each sources as s}
          <div class="source-row">
            <span class="score" style="color:{scoreColor(s.score)}">{s.score.toFixed(3)}</span>
            <span class="source-badge">{sourceLabel(s.source_table)}</span>
            <span class="chunk">{s.chunk_text}</span>
            {#if s.entity_id}
              <a href="/atelier/entite/{s.entity_id}" class="ent-link" target="_blank">→</a>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if config && !config.enabled}
    <p class="hint muted">
      La recherche par sens est éteinte sur cet atelier.<br>
      Elle demande un Ollama sur la machine de l'atelier&nbsp;: un administrateur la branche depuis cette page.
    </p>
  {:else if config && config.chunks === 0}
    <p class="hint muted">
      L'index n'a pas encore été construit&nbsp;: il n'y a rien à chercher.<br>
      <code>python3 scripts/build_rag_index.py</code>
    </p>
  {:else if !loading && sources.length === 0 && !answer && !error}
    <p class="hint muted">
      La recherche par sens retrouve une notion même quand le mot n'y est
      pas&nbsp;: «&nbsp;conflit d'intérêt&nbsp;» ramène les récusations au conseil.<br>
      Pour un mot qui s'écrit tel quel, la recherche ordinaire est plus sûre.
    </p>
  {/if}
</div>

<style>
  .ia-page { padding: 1.2rem; max-width: 900px; }
  .page-header { display: flex; align-items: baseline; gap: 1rem; margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: var(--texte); margin: 0; }
  .muted { color: var(--texte-doux); font-size: .75rem; }

  .branchement { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px;
                 padding: .7rem .9rem; margin-bottom: .9rem; font-size: .82rem; color: var(--texte); }
  .branchement summary { cursor: pointer; font-weight: 700; }
  .branchement summary .muted { font-weight: 400; margin-left: .5rem; }
  .branchement p { margin: .6rem 0; line-height: 1.5; }
  .branchement .champ { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin: .5rem 0; }
  .branchement select { background: var(--fond); border: 1px solid var(--bordure); color: var(--texte);
                        border-radius: 5px; padding: .3rem .45rem; }

  .mode-toggle { display: flex; gap: .4rem; margin-bottom: .75rem; }
  .mode-toggle button {
    background: var(--surface); border: 1px solid var(--bordure); color: var(--texte-doux);
    border-radius: 5px; padding: .3rem .65rem; font-size: .78rem; cursor: pointer;
  }
  .mode-toggle button.active { border-color: var(--accent); color: var(--lien); background: var(--info-doux); }

  .search-box { display: flex; gap: .5rem; align-items: flex-start; margin-bottom: .75rem; }
  textarea {
    flex: 1; background: var(--surface); border: 1px solid var(--bordure); color: var(--texte);
    border-radius: 6px; padding: .5rem .65rem; font-size: .82rem; resize: vertical;
    font-family: inherit; line-height: 1.4;
  }
  textarea:focus { outline: none; border-color: var(--focus); }
  .btn-submit {
    background: var(--accent-fort); color: var(--sur-accent); border: none; border-radius: 6px;
    padding: .5rem 1rem; font-size: .82rem; font-weight: 600; cursor: pointer;
    white-space: nowrap; align-self: stretch;
  }
  .btn-submit:hover:not(:disabled) { background: var(--bouton); }
  .btn-submit:disabled { opacity: .5; cursor: default; }

  .err { color: var(--danger); font-size: .8rem; margin-bottom: .5rem; }
  .garde { font-size: .74rem; color: var(--alerte); background: var(--alerte-doux); border: 1px solid var(--alerte-bordure);
    border-radius: 6px; padding: .45rem .65rem; margin: 0 0 .6rem; line-height: 1.5; }

  .answer-block {
    background: var(--succes-doux); border: 1px solid var(--succes-bordure); border-radius: 8px;
    margin-bottom: 1rem; overflow: hidden;
  }
  .answer-header { background: var(--succes-bordure); color: var(--succes-texte); font-size: .72rem; font-weight: 700;
    padding: .3rem .75rem; text-transform: uppercase; letter-spacing: .05em; }
  .answer-text { padding: .75rem; font-size: .82rem; color: var(--succes-texte); line-height: 1.6; white-space: pre-wrap; }

  .sources-title {
    font-size: .8rem; font-weight: 600; color: var(--texte-doux); margin-bottom: .4rem;
    display: flex; align-items: center; gap: .4rem;
  }
  .count { font-size: .68rem; background: var(--surface-2); color: var(--texte-doux); border-radius: 999px; padding: 1px 5px; }

  .sources-list { display: flex; flex-direction: column; gap: .25rem; }
  .source-row {
    display: grid; grid-template-columns: 44px 90px 1fr 20px;
    align-items: center; gap: .5rem;
    background: var(--surface); border-radius: 5px; padding: .35rem .6rem;
    font-size: .75rem;
  }
  .score { font-weight: 700; font-size: .72rem; }
  .source-badge { font-size: .65rem; background: var(--surface-2); color: var(--texte-doux);
    border-radius: 3px; padding: 1px 5px; text-align: center; }
  .chunk { color: var(--texte-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ent-link { color: var(--lien); font-size: .8rem; }
  .ent-link:hover { text-decoration: underline; }

  .hint { font-size: .78rem; margin-top: 2rem; text-align: center; line-height: 1.8; }
  code { background: var(--surface); border-radius: 4px; padding: 2px 6px; font-size: .75rem; color: var(--info); }
</style>
