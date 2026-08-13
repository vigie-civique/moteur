<script>
  import { activeLayers, bizStatus, showExternal, TYPE_COLORS } from '$lib/stores/app.js'

  const LAYERS = [
    { key: 'businesses',   label: 'Entreprises',   color: TYPE_COLORS.business    },
    { key: 'associations', label: 'Associations',  color: TYPE_COLORS.association },
    { key: 'services',     label: 'Services pub.', color: TYPE_COLORS.service     },
    { key: 'places',       label: 'POI / Lieux',   color: TYPE_COLORS.place       },
    { key: 'persons',      label: 'Personnes',     color: TYPE_COLORS.person      },
    { key: 'dvf',          label: 'DVF (ventes)',  color: '#f97316'               },
  ]

  function toggle(key) {
    activeLayers.update(l => ({ ...l, [key]: !l[key] }))
  }
</script>

<div class="layer-bar">
  {#each LAYERS as l}
    <button
      class:on={$activeLayers[l.key]}
      on:click={() => toggle(l.key)}
      style="--c: {l.color}"
    >
      <span class="pip"></span>
      {l.label}
    </button>
  {/each}

  <select bind:value={$bizStatus} title="Statut entreprise">
    <option value="">Toutes</option>
    <option value="A">Actives</option>
    <option value="F">Fermées</option>
  </select>

  <label class="external-toggle" title="Inclure les entités dont le siège est hors commune">
    <input type="checkbox" bind:checked={$showExternal} />
    Hors commune
  </label>
</div>

<style>
  .layer-bar {
    display: flex;
    align-items: center;
    gap: .35rem;
    padding: .35rem 1rem;
    background: #1e293b;
    border-bottom: 1px solid #1e293b;
    flex-wrap: wrap;
    flex-shrink: 0;
  }

  button {
    display: flex;
    align-items: center;
    gap: .35rem;
    padding: .2rem .6rem;
    border-radius: 999px;
    font-size: .75rem;
    border: 1px solid #334155;
    background: #0f172a;
    color: #64748b;
    transition: all .15s;
  }
  button.on {
    border-color: var(--c);
    color: var(--c);
    background: color-mix(in srgb, var(--c) 15%, transparent);
  }
  .pip {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--c);
    opacity: .4;
    transition: opacity .15s;
  }
  button.on .pip { opacity: 1; }

  select {
    margin-left: auto;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #94a3b8;
    font-size: .75rem;
    padding: .2rem .5rem;
  }

  .external-toggle {
    display: flex;
    align-items: center;
    gap: .3rem;
    font-size: .75rem;
    color: #64748b;
    cursor: pointer;
    user-select: none;
  }
  .external-toggle input { cursor: pointer; }
</style>
