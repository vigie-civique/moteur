<script>
  import { COMMUNE } from '$lib/instance.js'
  import SearchBar from '$lib/components/SearchBar.svelte'
  import GraphView from '$lib/components/GraphView.svelte'
  import SidePanel from '$lib/components/SidePanel.svelte'
</script>

<svelte:head>
  <title>Graphe de relations — {COMMUNE}</title>
</svelte:head>

<div class="page-graph">
  <div class="left">
    <div class="search-row">
      <SearchBar />
    </div>
    <div class="graph-area">
      <GraphView />
    </div>
  </div>
  <SidePanel />
</div>

<style>
  .page-graph {
    display: flex;
    flex: 1;
    overflow: hidden;
    width: 100%;
  }
  .left {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .search-row {
    padding: .35rem 1rem;
    background: var(--surface);
    border-bottom: 1px solid var(--bordure);
    flex-shrink: 0;
  }
  .graph-area {
    flex: 1;
    position: relative;
    overflow: hidden;
  }
</style>
