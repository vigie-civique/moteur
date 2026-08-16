<script>
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { selectedEntity, stats } from '$lib/stores/app.js'

  // Le modèle est un réglage du serveur, pas une constante de l'interface :
  // le bouton nommait un fournisseur en dur et continuait de le nommer après
  // en avoir changé. On demande à l'API ce qui tourne réellement.
  let ia = null
  onMount(async () => { ia = await api.iaConfig() })

  let topic    = 'synthèse générale'
  let context  = ''
  let result   = ''
  let loading  = false
  let error    = null

  const TOPICS = [
    'synthèse générale',
    'réseau d\'influence',
    'flux financiers et subventions',
    'immobilier (DVF)',
    'tissu associatif',
    'tissu économique',
    'personnes clés',
  ]

  async function synthesize() {
    loading = true; result = ''; error = null
    // Auto-contexte : stats + entité sélectionnée
    let ctx = context
    if (!ctx && $stats) {
      ctx = `Base de données : ${$stats.entities ?? 0} entités, ${$stats.businesses ?? 0} entreprises, `
           + `${$stats.associations ?? 0} associations, ${$stats.persons ?? 0} personnes, `
           + `${$stats.relations ?? 0} relations, ${$stats.events ?? 0} événements CM.`
    }
    if ($selectedEntity) {
      ctx += `\n\nEntité active : ${$selectedEntity.name} (${$selectedEntity.type})`
      if ($selectedEntity.siren) ctx += `, SIREN ${$selectedEntity.siren}`
    }
    try {
      const r = await api.synthesize(topic, ctx)
      if (r.error) error = r.error
      else result = r.synthesis || ''
    } catch(e) { error = e.message }
    loading = false
  }
</script>

<div class="ai-panel">
  <div class="controls">
    <select bind:value={topic}>
      {#each TOPICS as t}<option value={t}>{t}</option>{/each}
    </select>

    <textarea
      bind:value={context}
      placeholder="Contexte additionnel (optionnel — sinon auto-généré depuis la base)…"
      rows="3"
    ></textarea>

    <button on:click={synthesize} disabled={loading || (ia && !ia.configuree)}>
      {loading ? 'Analyse en cours…' : '⚡ Analyser'}
    </button>

    {#if ia && !ia.configuree}
      <p class="hint">
        Aucun modèle configuré. Régler <code>IA_URL</code> et <code>IA_MODELE</code>
        dans <code>.env</code> — le fournisseur est libre, local compris
        (cf. <code>deploy/env.exemple</code>).
      </p>
    {:else if ia?.modele}
      <p class="hint">
        Modèle : <code>{ia.modele}</code>
        {#if ia.locale}— local, aucune donnée ne sort de la machine{:else}— service distant : les extraits envoyés sortent de la machine{/if}
      </p>
    {/if}
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if result}
    <div class="result">
      {#each result.split('\n') as line}
        {#if line.trim()}
          <p>{line}</p>
        {:else}
          <br/>
        {/if}
      {/each}
    </div>
  {:else if !loading}
    <p class="hint">Lance une analyse pour obtenir une synthèse IA des données OSINT.</p>
  {/if}
</div>

<style>
  .ai-panel {
    display: flex;
    flex-direction: column;
    gap: .75rem;
    height: 100%;
    overflow-y: auto;
  }

  .controls {
    display: flex;
    flex-direction: column;
    gap: .5rem;
  }

  select, textarea {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #e2e8f0;
    font-size: .82rem;
    padding: .4rem .6rem;
    width: 100%;
  }
  textarea { resize: vertical; font-family: inherit; }

  button {
    padding: .45rem 1rem;
    background: #3b82f6;
    color: #fff;
    border-radius: 6px;
    font-size: .82rem;
    font-weight: 600;
    transition: background .15s;
  }
  button:hover:not(:disabled) { background: #2563eb; }
  button:disabled { opacity: .5; cursor: wait; }

  .error {
    background: #450a0a;
    border: 1px solid #7f1d1d;
    border-radius: 6px;
    padding: .5rem .75rem;
    font-size: .8rem;
    color: #fca5a5;
  }

  .result {
    background: #0f172a;
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: .75rem;
    font-size: .82rem;
    line-height: 1.65;
    color: #cbd5e1;
    white-space: pre-wrap;
  }
  .result p { margin-bottom: .5rem; }

  .hint { color: #475569; font-size: .82rem; }
  .hint code {
    background: #0f172a;
    border-radius: 3px;
    color: #94a3b8;
    padding: 0 .25rem;
  }
</style>
