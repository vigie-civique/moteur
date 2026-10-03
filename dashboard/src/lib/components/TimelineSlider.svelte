<script>
  import { timelineYear, timelineMode, timelineRange } from '$lib/stores/timeline.js'

  let playing = false
  let timer

  $: min = $timelineRange.min
  $: max = $timelineRange.max

  // Valeur locale pour le slider (null → max pour représenter "tout")
  let sliderVal = max

  // Sync store → slider
  $: if ($timelineYear === null) sliderVal = max + 1

  function onSlide(e) {
    const v = Number(e.target.value)
    if (v > max) {
      timelineYear.set(null)
    } else {
      timelineYear.set(v)
    }
  }

  function reset() {
    stopPlay()
    timelineYear.set(null)
    sliderVal = max + 1
  }

  function startPlay() {
    if (playing) return
    playing = true
    // Commence depuis min si on est sur "tout"
    if ($timelineYear === null) {
      timelineYear.set(min)
      sliderVal = min
    }
    timer = setInterval(() => {
      timelineYear.update(y => {
        const next = (y ?? min) + 1
        sliderVal = next > max ? max + 1 : next
        if (next > max) { stopPlay(); return null }
        return next
      })
    }, 900)
  }

  function stopPlay() {
    playing = false
    clearInterval(timer)
  }

  function togglePlay() {
    playing ? stopPlay() : startPlay()
  }

  import { onDestroy } from 'svelte'
  onDestroy(() => clearInterval(timer))
</script>

<div class="timeline">
  <div class="controls">
    <button class="play-btn" on:click={togglePlay} title={playing ? 'Pause' : 'Lecture'}>
      {playing ? '⏸' : '▶'}
    </button>

    <button class="reset-btn" on:click={reset} title="Toutes les années">⏹</button>

    <div class="mode-toggle">
      <button class:active={$timelineMode === 'cumulative'} on:click={() => timelineMode.set('cumulative')}>cumulatif</button>
      <button class:active={$timelineMode === 'exact'}      on:click={() => timelineMode.set('exact')}>année exacte</button>
    </div>
  </div>

  <div class="slider-wrap">
    <span class="yr-label min">{min}</span>

    <input
      type="range"
      min={min}
      max={max + 1}
      step="1"
      bind:value={sliderVal}
      on:input={onSlide}
    />

    <span class="yr-label max">
      {$timelineYear === null ? 'Tout' : $timelineYear}
    </span>
  </div>

  {#if $timelineYear !== null}
    <div class="badge">
      {$timelineMode === 'cumulative' ? '≤ ' : ''}{$timelineYear}
    </div>
  {/if}
</div>

<style>
  .timeline {
    position: absolute;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    background: color-mix(in srgb, var(--fond) 92%, transparent);
    backdrop-filter: blur(8px);
    border: 1px solid var(--bordure);
    border-radius: 10px;
    padding: .5rem .85rem;
    display: flex;
    align-items: center;
    gap: .75rem;
    min-width: 420px;
    box-shadow: 0 4px 20px var(--ombre);
  }

  .controls {
    display: flex;
    align-items: center;
    gap: .35rem;
    flex-shrink: 0;
  }

  .play-btn, .reset-btn {
    width: 28px; height: 28px;
    border-radius: 50%;
    background: var(--surface);
    border: 1px solid var(--bordure);
    font-size: .9rem;
    display: flex; align-items: center; justify-content: center;
    transition: background .15s;
  }
  .play-btn:hover, .reset-btn:hover { background: var(--surface-2); }

  .mode-toggle {
    display: flex;
    background: var(--fond);
    border-radius: 6px;
    padding: 1px;
    gap: 1px;
  }
  .mode-toggle button {
    font-size: .65rem;
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--texte-doux);
    transition: all .15s;
  }
  .mode-toggle button.active {
    background: var(--accent);
    color: var(--sur-accent);
  }

  .slider-wrap {
    display: flex;
    align-items: center;
    gap: .5rem;
    flex: 1;
  }

  input[type=range] {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: var(--surface-2);
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--sur-accent);
    box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 50%, transparent);
  }

  .yr-label {
    font-size: .72rem;
    color: var(--texte-doux);
    flex-shrink: 0;
    width: 36px;
  }
  .yr-label.max { text-align: right; }

  .badge {
    background: var(--accent);
    color: var(--sur-accent);
    font-size: .78rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 999px;
    flex-shrink: 0;
    min-width: 54px;
    text-align: center;
  }
</style>
