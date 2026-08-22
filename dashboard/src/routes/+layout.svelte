<script>
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { stats } from '$lib/stores/app.js'
  import { api } from '$lib/api.js'
  import { currentUser, initAuth } from '$lib/stores/auth.js'
  import { COMMUNE, COMMUNE_DE, LA_COMMUNE, CODE_POSTAL, SITE_NOM } from '$lib/instance.js'
  import 'leaflet/dist/leaflet.css'
  import 'leaflet.markercluster/dist/MarkerCluster.css'
  import 'leaflet.markercluster/dist/MarkerCluster.Default.css'

  onMount(async () => {
    initAuth()   // réhydrate currentUser depuis le token de session
    // Sur la page login : pas de token → /stats renvoie 401 (verrou global API).
    // Inutile de le tenter, ça déclenchait un refresh + redirect en boucle.
    if ($page.url.pathname.startsWith('/atelier/login')) return
    try {
      const s = await api.stats()
      stats.set(s)
    } catch (e) {
      console.warn('stats:', e)
    }
  })

  // Atelier organisé par TÂCHE — pas en miroir du public. cf. CARTE_PRODUIT.md §4.
  // Les onglets façon public (Carte/Graphe/Délibs/Budgets/Méthode/Urbanisme/CC CAC)
  // appartiennent au site public → retirés ici, remplacés par un lien « voir le public ».
  const NAV = [
    { href: '/atelier',             label: '◳ Tableau de bord' },
    { href: '/acteurs-publics',     label: '👤 Acteurs' },
    { href: '/atelier/geo',         label: '📍 Géoloc' },
    { href: '/atelier/queue/websites', label: '✓ Validation' },
    { href: '/atelier/donnees',     label: '📥 Données importées' },
    { href: '/atelier/analyses',    label: '🔬 Analyses' },
    { href: '/atelier/ia',          label: '🤖 IA' },
    { href: '/atelier/publication', label: '🚀 Publication' },
  ]
  // La page Publication est ouverte à tout l'atelier depuis le 22/08/2026, en
  // LECTURE SEULE pour les non-admins : l'action reste réservée au rôle admin
  // (décision 03/07/2026 : 1 admin + 2 validateurs), mais un validateur qui
  // vient de corriger doit pouvoir voir si c'est en ligne et si le dernier
  // contrôle est rouge. Cacher l'état ne protégeait rien.
  $: nav = NAV.filter(n => !n.adminOnly || !$currentUser || $currentUser.role === 'admin')
  // « 👁 Voir le site public » — app publique séparée (dev : 5174).
  const PUBLIC_URL = 'http://localhost:5174'
</script>

<svelte:head>
  <!-- Descriptions communes à tout l'atelier. Elles vivaient dans app.html, qui
       est du HTML statique et ne sait rien de l'instance. -->
  <meta name="description" content="Veille citoyenne sur la vie politique et municipale {COMMUNE_DE} ({CODE_POSTAL}) — conseil municipal, finances, entreprises, associations." />
  <meta property="og:title" content="{COMMUNE} — Veille citoyenne" />
  <meta property="og:description" content="Données publiques structurées sur {LA_COMMUNE}" />
</svelte:head>

<div class="app">
  <header data-pagefind-ignore>
    <a href="/atelier" class="brand">
      <span class="dot"></span>
      <span class="title">{SITE_NOM}</span>
      <span class="sub">{CODE_POSTAL} — atelier de veille</span>
    </a>

    <nav>
      {#each nav as n}
        {#if n.soon}
          <span class="soon" title="Surface à venir">{n.label} <em>·&nbsp;bientôt</em></span>
        {:else}
          <a href={n.href} class:active={$page.url.pathname === n.href}>{n.label}</a>
        {/if}
      {/each}
      <a class="view-public" href={PUBLIC_URL} target="_blank" rel="noopener">👁 Voir le site public</a>
    </nav>

    {#if $stats}
      <div class="badge-row">
        <span class="badge biz">{$stats.businesses ?? 0} entreprises</span>
        <span class="badge asso">{$stats.associations ?? 0} assos</span>
        <span class="badge svc">{$stats.services ?? 0} services</span>
        <span class="badge per">{$stats.persons ?? 0} personnes</span>
      </div>
    {/if}
  </header>

  <main data-pagefind-body>
    <slot />
  </main>
</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) { font-family: 'Inter', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; overflow: hidden; }
  :global(a) { color: #60a5fa; text-decoration: none; }
  :global(button) { cursor: pointer; border: none; background: none; color: inherit; font: inherit; }
  :global(::-webkit-scrollbar) { width: 6px; }
  :global(::-webkit-scrollbar-track) { background: #1e293b; }
  :global(::-webkit-scrollbar-thumb) { background: #334155; border-radius: 3px; }

  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: .5rem 1rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: .5rem;
    white-space: nowrap;
    color: #e2e8f0;
  }
  .dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #ef4444;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: .4; }
  }
  .title { font-weight: 700; font-size: 1rem; }
  .sub   { font-size: .75rem; color: #64748b; }

  nav {
    display: flex;
    gap: .25rem;
    background: #0f172a;
    border-radius: 6px;
    padding: 2px;
  }
  nav a {
    padding: .25rem .75rem;
    border-radius: 4px;
    font-size: .8rem;
    color: #94a3b8;
    transition: background .15s;
  }
  nav a.active {
    background: #3b82f6;
    color: #fff;
  }
  nav a:hover:not(.active) { background: #1e293b; }
  nav .soon {
    padding: .25rem .75rem;
    font-size: .8rem;
    color: #475569;
    cursor: default;
  }
  nav .soon em { font-style: normal; color: #64748b; font-size: .68rem; }
  nav .view-public {
    margin-left: .5rem;
    padding: .25rem .75rem;
    border-radius: 4px;
    font-size: .8rem;
    color: #93c5fd;
    border: 1px solid #334155;
  }
  nav .view-public:hover { background: #1e293b; }

  .badge-row { display: flex; gap: .4rem; flex-wrap: wrap; margin-left: auto; }
  .badge {
    font-size: .72rem;
    padding: 2px 8px;
    border-radius: 999px;
    font-weight: 600;
  }
  .biz  { background: #1d4ed8; }
  .asso { background: #065f46; }
  .svc  { background: #92400e; }
  .per  { background: #7f1d1d; }

  main {
    flex: 1;
    overflow: hidden;
    display: flex;
  }
</style>
