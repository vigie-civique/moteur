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
    background: rgba(15, 23, 42, 0.92);
    backdrop-filter: blur(8px);
    border: 1px solid #334155;
    border-radius: 10px;
    padding: .5rem .85rem;
    display: flex;
    align-items: center;
    gap: .75rem;
    min-width: 420px;
    box-shadow: 0 4px 20px rgba(0,0,0,.4);
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
    background: #1e293b;
    border: 1px solid #334155;
    font-size: .9rem;
    display: flex; align-items: center; justify-content: center;
    transition: background .15s;
  }
  .play-btn:hover, .reset-btn:hover { background: #334155; }

  .mode-toggle {
    display: flex;
    background: #0f172a;
    border-radius: 6px;
    padding: 1px;
    gap: 1px;
  }
  .mode-toggle button {
    font-size: .65rem;
    padding: 2px 6px;
    border-radius: 4px;
    color: #64748b;
    transition: all .15s;
  }
  .mode-toggle button.active {
    background: #3b82f6;
    color: #fff;
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
    background: #334155;
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #3b82f6;
    border: 2px solid #fff;
    box-shadow: 0 0 6px rgba(59,130,246,.5);
  }

  .yr-label {
    font-size: .72rem;
    color: #64748b;
    flex-shrink: 0;
    width: 36px;
  }
  .yr-label.max { text-align: right; }

  .badge {
    background: #3b82f6;
    color: #fff;
    font-size: .78rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 999px;
    flex-shrink: 0;
    min-width: 54px;
    text-align: center;
  }
</style>
