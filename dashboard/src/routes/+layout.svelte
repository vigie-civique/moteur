<script>
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { stats } from '$lib/stores/app.js'
  import { api } from '$lib/api.js'
  import { currentUser, initAuth } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { COMMUNE, COMMUNE_DE, LA_COMMUNE, CODE_POSTAL, SITE_NOM, SITE_URL } from '$lib/instance.js'
  import 'leaflet/dist/leaflet.css'
  import 'leaflet.markercluster/dist/MarkerCluster.css'
  import 'leaflet.markercluster/dist/MarkerCluster.Default.css'
  // Après Leaflet : ses contrôles et ses popups lisent les jetons du thème.
  import '$lib/theme.css'
  // Le choix Système / Clair / Sombre s'applique sur toutes les pages.
  import '$lib/theme.js'

  onMount(async () => {
    initAuth()   // réhydrate currentUser depuis le token de session
    // Sur la page login : pas de token → /stats renvoie 401 (verrou global API).
    // Inutile de le tenter, ça déclenchait un refresh + redirect en boucle.
    if ($page.url.pathname.startsWith('/atelier/login')
        || $page.url.pathname.startsWith('/atelier/invitation')) return
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
    { href: '/atelier/analyses',    label: '🔬 Analyses', min: 'validator' },
    { href: '/atelier/ia',          label: '🤖 IA' },
    { href: '/atelier/publication', label: '🚀 Publication' },
  ]
  // La page Publication est ouverte à tout l'atelier depuis le 22/08/2026, en
  // LECTURE SEULE pour les non-admins : l'action reste réservée au rôle admin
  // (décision 03/07/2026 : 1 admin + 2 validateurs), mais un validateur qui
  // vient de corriger doit pouvoir voir si c'est en ligne et si le dernier
  // contrôle est rouge. Cacher l'état ne protégeait rien.
  $: nav = NAV.filter(n => !n.min || auMoins($currentUser, n.min))
  // Connexion et invitation : la personne n'a pas (encore) de session. Lui
  // montrer le menu de l'atelier, c'était l'inviter dans des pages fermées.
  $: horsSession = ['/atelier/login', '/atelier/invitation'].includes($page.url.pathname)
  // Dans l'atelier, le menu est celui du côté (`atelier/+layout.svelte`). Les
  // deux menus empilés ne disaient pas la même chose (« Tableau de bord » ici,
  // « Aujourd'hui » là) : celui-ci ne reste que sur les pages hors atelier.
  $: dansAtelier = $page.url.pathname.startsWith('/atelier')
  // « 👁 Voir le site public » : l'adresse déclarée par l'instance. Elle visait
  // `localhost:5174`, le serveur de développement — mort pour tout le monde.
  const PUBLIC_URL = SITE_URL || '/'
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
      <img class="logo" src="/favicon.svg" alt="" width="22" height="22" />
      <span class="title">{SITE_NOM}</span>
      <span class="sub">{CODE_POSTAL} — atelier de veille</span>
    </a>

    {#if !horsSession && dansAtelier}
      <a class="view-public seul" href={PUBLIC_URL} target="_blank" rel="noopener">👁 Voir le site public</a>
    {:else if !horsSession}
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

    {/if}

    {#if $stats && !horsSession && !dansAtelier}
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
  /* 112,5 % : les tailles de l'atelier sont en `rem`, de .65 à .85 — soit 10 à
     13 px à la taille par défaut, illisibles sur un portable qu'on ne choisit
     pas, dans une salle communale. Elles montent toutes d'un cran d'un coup. */
  :global(html) { font-size: 112.5%; }
  :global(body) { font-family: 'Inter', system-ui, sans-serif; background: var(--fond); color: var(--texte); overflow: hidden; }
  :global(a) { color: var(--lien); text-decoration: none; }
  :global(button) { cursor: pointer; border: none; background: none; color: inherit; font: inherit; }
  :global(::-webkit-scrollbar) { width: 6px; }
  :global(::-webkit-scrollbar-track) { background: var(--surface); }
  :global(::-webkit-scrollbar-thumb) { background: var(--surface-2); border-radius: 3px; }

  /* Leaflet : seuls les contrôles et les popups suivent le thème. Le fond de
     carte (plan IGN, orthophoto) reste celui de son éditeur. Les sélecteurs
     reprennent la spécificité de leaflet.css pour le remplacer. */
  :global(.leaflet-bar a),
  :global(.leaflet-touch .leaflet-bar a) {
    background-color: var(--surface); color: var(--texte); border-bottom-color: var(--bordure);
  }
  :global(.leaflet-bar a:hover),
  :global(.leaflet-bar a:focus) { background-color: var(--surface-2); color: var(--texte); }
  :global(.leaflet-bar a.leaflet-disabled) { background-color: var(--fond); color: var(--texte-doux); }
  :global(.leaflet-touch .leaflet-control-layers),
  :global(.leaflet-touch .leaflet-bar) { border-color: var(--bordure); }
  :global(.leaflet-control-layers) {
    background: var(--surface); color: var(--texte); box-shadow: 0 1px 5px var(--ombre);
  }
  :global(.leaflet-control-layers-separator) { border-top-color: var(--bordure); }
  :global(.leaflet-popup-content-wrapper),
  :global(.leaflet-popup-tip) {
    background: var(--surface); color: var(--texte); box-shadow: 0 3px 14px var(--ombre);
  }
  :global(.leaflet-container a.leaflet-popup-close-button) { color: var(--texte-doux); }
  :global(.leaflet-container a.leaflet-popup-close-button:hover) { color: var(--texte); }
  :global(.leaflet-container .leaflet-control-attribution) {
    background: color-mix(in srgb, var(--surface) 85%, transparent); color: var(--texte-doux);
  }
  :global(.leaflet-container .leaflet-control-attribution a) { color: var(--lien); }

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
    background: var(--surface);
    border-bottom: 1px solid var(--bordure);
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: .5rem;
    white-space: nowrap;
    color: var(--texte);
  }
  .logo { display: block; flex: none; border-radius: 5px; }
  .title { font-weight: 700; font-size: 1rem; }
  .sub   { font-size: .75rem; color: var(--texte-doux); }

  nav {
    display: flex;
    gap: .25rem;
    background: var(--fond);
    border-radius: 6px;
    padding: 2px;
  }
  nav a {
    padding: .25rem .75rem;
    border-radius: 4px;
    font-size: .8rem;
    color: var(--texte-doux);
    transition: background .15s;
  }
  nav a.active {
    background: var(--accent);
    color: var(--sur-accent);
  }
  nav a:hover:not(.active) { background: var(--surface); }
  nav .soon {
    padding: .25rem .75rem;
    font-size: .8rem;
    color: var(--texte-doux);
    cursor: default;
  }
  nav .soon em { font-style: normal; color: var(--texte-doux); font-size: .68rem; }
  nav .view-public {
    margin-left: .5rem;
    padding: .25rem .75rem;
    border-radius: 4px;
    font-size: .8rem;
    color: var(--info);
    border: 1px solid var(--bordure);
  }
  nav .view-public:hover { background: var(--surface); }
  .view-public.seul {
    margin-left: auto; padding: .25rem .75rem; border-radius: 4px;
    font-size: .8rem; color: var(--info); border: 1px solid var(--bordure);
  }
  .view-public.seul:hover { background: var(--fond); }

  .badge-row { display: flex; gap: .4rem; flex-wrap: wrap; margin-left: auto; }
  .badge {
    color: var(--sur-accent);
    font-size: .72rem;
    padding: 2px 8px;
    border-radius: 999px;
    font-weight: 600;
  }
  .biz  { background: var(--type-entreprise); }
  .asso { background: var(--type-association); }
  .svc  { background: var(--type-service); }
  .per  { background: var(--type-personne); }

  main {
    flex: 1;
    overflow: hidden;
    display: flex;
  }
</style>
