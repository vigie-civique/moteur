<script>
  import SearchBar from '$lib/components/SearchBar.svelte'
  import GraphView from '$lib/components/GraphView.svelte'
  import SidePanel from '$lib/components/SidePanel.svelte'
</script>

<svelte:head>
  <title>Graphe de relations — Lasalle</title>
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
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
  }
  .graph-area {
    flex: 1;
    position: relative;
    overflow: hidden;
  }
</style>
