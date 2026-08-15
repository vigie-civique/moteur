<script>
  import { COMMUNE } from '$lib/instance.js'
  import { authFetch } from '$lib/stores/auth.js'
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
  onMount(async () => {
    try {
      const r = await authFetch('/rag/config')
      if (r.ok) config = await r.json()
    } catch { /* API muette : la page le dira */ }
  })

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
    if (s >= 0.85) return '#22c55e'
    if (s >= 0.70) return '#f59e0b'
    return '#94a3b8'
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
      L'assistance par modèle est désactivée sur cet atelier.<br>
      Elle demande un Ollama joignable en local&nbsp;: <code>RAG_ENABLED=1</code> dans <code>.env</code>.
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
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .muted { color: #64748b; font-size: .75rem; }

  .mode-toggle { display: flex; gap: .4rem; margin-bottom: .75rem; }
  .mode-toggle button {
    background: #1e293b; border: 1px solid #334155; color: #94a3b8;
    border-radius: 5px; padding: .3rem .65rem; font-size: .78rem; cursor: pointer;
  }
  .mode-toggle button.active { border-color: #3b82f6; color: #60a5fa; background: #172554; }

  .search-box { display: flex; gap: .5rem; align-items: flex-start; margin-bottom: .75rem; }
  textarea {
    flex: 1; background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
    border-radius: 6px; padding: .5rem .65rem; font-size: .82rem; resize: vertical;
    font-family: inherit; line-height: 1.4;
  }
  textarea:focus { outline: none; border-color: #3b82f6; }
  .btn-submit {
    background: #1d4ed8; color: #fff; border: none; border-radius: 6px;
    padding: .5rem 1rem; font-size: .82rem; font-weight: 600; cursor: pointer;
    white-space: nowrap; align-self: stretch;
  }
  .btn-submit:hover:not(:disabled) { background: #2563eb; }
  .btn-submit:disabled { opacity: .5; cursor: default; }

  .err { color: #f87171; font-size: .8rem; margin-bottom: .5rem; }
  .garde { font-size: .74rem; color: #fbbf24; background: #2a1f06; border: 1px solid #78350f;
    border-radius: 6px; padding: .45rem .65rem; margin: 0 0 .6rem; line-height: 1.5; }

  .answer-block {
    background: #0f2a1e; border: 1px solid #166534; border-radius: 8px;
    margin-bottom: 1rem; overflow: hidden;
  }
  .answer-header { background: #166534; color: #4ade80; font-size: .72rem; font-weight: 700;
    padding: .3rem .75rem; text-transform: uppercase; letter-spacing: .05em; }
  .answer-text { padding: .75rem; font-size: .82rem; color: #d1fae5; line-height: 1.6; white-space: pre-wrap; }

  .sources-title {
    font-size: .8rem; font-weight: 600; color: #94a3b8; margin-bottom: .4rem;
    display: flex; align-items: center; gap: .4rem;
  }
  .count { font-size: .68rem; background: #334155; color: #94a3b8; border-radius: 999px; padding: 1px 5px; }

  .sources-list { display: flex; flex-direction: column; gap: .25rem; }
  .source-row {
    display: grid; grid-template-columns: 44px 90px 1fr 20px;
    align-items: center; gap: .5rem;
    background: #1e293b; border-radius: 5px; padding: .35rem .6rem;
    font-size: .75rem;
  }
  .score { font-weight: 700; font-size: .72rem; }
  .source-badge { font-size: .65rem; background: #334155; color: #94a3b8;
    border-radius: 3px; padding: 1px 5px; text-align: center; }
  .chunk { color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ent-link { color: #60a5fa; font-size: .8rem; }
  .ent-link:hover { text-decoration: underline; }

  .hint { font-size: .78rem; margin-top: 2rem; text-align: center; line-height: 1.8; }
  code { background: #1e293b; border-radius: 4px; padding: 2px 6px; font-size: .75rem; color: #a5f3fc; }
</style>
