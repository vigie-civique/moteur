<script>
  import { COMMUNE, SITE_NOM, SITE_URL } from '$lib/instance.js'
  import { page, updated } from '$app/stores'
  import { goto, beforeNavigate } from '$app/navigation'
  import Icon from '$lib/components/Icon.svelte'

  // Une version plus récente du site a été publiée pendant que cet onglet était
  // ouvert : on quitte la navigation interne pour un vrai chargement. Sans ça,
  // le client continue de réclamer des fragments `/_app/immutable/` empreintés
  // qui n'existent plus chez l'hébergeur, et le lecteur doit rafraîchir à la
  // main pour voir quoi que ce soit. Suppose `version.pollInterval` réglé dans
  // svelte.config.js.
  beforeNavigate(({ to, willUnload, cancel }) => {
    if ($updated && to?.url && !willUnload) {
      cancel()
      location.href = to.url.href
    }
  })

  // Public organisé par QUESTION citoyenne (modèle CivLab), pas par table.
  //
  // Réduit de huit entrées à cinq le 11/08/2026 : huit portes de même poids ne
  // se retiennent pas, et le header passait sur trois lignes sous 860 px faute
  // de règle @media. « Le territoire », « Environnement » et « Vie locale »
  // restent atteignables depuis l'accueil, « Comprendre » et le pied de page :
  // ce sont des pages de contexte, pas des questions de départ.
  // « Qui agit ? » mène à l'annuaire, pas à la carte : la carte ne montre que
  // les 1 135 acteurs géolocalisés, l'annuaire les couvre tous. Un nom, un
  // périmètre, une page — et le même libellé que la porte de l'accueil.
  const nav = [
    { href: '/nouveautes',      label: 'Récent',         icone: 'recent', titre: 'Ce qui a changé' },
    { href: '/qui-decide',      label: 'Qui décide',     icone: 'decide' },
    { href: '/argent',          label: "Où va l'argent", icone: 'argent' },
    { href: '/acteurs-publics', label: 'Qui agit',       icone: 'acteurs', titre: 'Qui agit ?',
      aussi: ['/carte', '/entite'] },
    { href: '/comprendre',      label: 'Comprendre',     icone: 'comprendre' },
  ]
  $: path = $page.url.pathname
  // La carte et les fiches acteur appartiennent à « Qui agit ? » : sans ça,
  // aucun onglet n'était souligné une fois qu'on y arrivait.
  const estActif = (n) =>
    n.href === '/' ? path === '/'
    : path.startsWith(n.href) || (n.aussi || []).some((p) => path.startsWith(p))

  // Recherche accessible depuis toutes les pages : un simple submit vers
  // /recherche?q=, qui filtre l'index côté client (le public est statique).
  let q = ''
  let menuOuvert = false

  function chercher(e) {
    e.preventDefault()
    menuOuvert = false
    const v = q.trim()
    goto(v ? `/recherche?q=${encodeURIComponent(v)}` : '/recherche')
  }

  // Le panneau mobile ne doit pas rester ouvert par-dessus la page d'arrivée.
  $: if (path) menuOuvert = false
</script>

<!-- Adresse canonique. Un site publié sur un hébergeur répond souvent à deux
     adresses : son domaine et le sous-domaine de l'hébergeur, que celui-ci garde
     actif et qui n'est pas dans la zone du domaine — aucune redirection ne peut
     donc le rattraper. Sans cette balise, les deux se concurrencent et l'autorité
     de référencement reste chez l'hébergeur, qui n'appartient pas au projet.
     Posée une seule fois ici : chaque page en hérite. -->
{#if SITE_URL}
  <svelte:head>
    <link rel="canonical" href="{SITE_URL}{path}" />
    <meta property="og:url" content="{SITE_URL}{path}" />
    <meta property="og:site_name" content={SITE_NOM} />
    <meta property="og:type" content="website" />
    <meta property="og:locale" content="fr_FR" />
    <meta name="twitter:card" content="summary" />
  </svelte:head>
{/if}

<svelte:window on:keydown={(e) => { if (e.key === 'Escape') menuOuvert = false }} />

<div class="app">
  <header>
    <a class="brand" href="/">
      <Icon name="decide" size={22} />
      <span><strong>Vigie Civique</strong> <em>{COMMUNE}</em></span>
    </a>

    <nav class="principale">
      {#each nav as n}
        <a href={n.href} class:active={estActif(n)} title={n.titre || n.label}>
          <Icon name={n.icone} size={16} />{n.label}
        </a>
      {/each}
    </nav>

    <form class="recherche" on:submit={chercher} role="search">
      <Icon name="recherche" size={15} />
      <input type="search" bind:value={q} placeholder="Rechercher un acteur…"
             aria-label="Rechercher un acteur" autocomplete="off" />
      <button type="submit">Chercher</button>
    </form>

    <button class="burger" on:click={() => (menuOuvert = !menuOuvert)}
            aria-expanded={menuOuvert} aria-controls="menu-mobile"
            aria-label={menuOuvert ? 'Fermer le menu' : 'Ouvrir le menu'}>
      <Icon name={menuOuvert ? 'fermer' : 'menu'} size={22} />
    </button>
  </header>

  {#if menuOuvert}
    <div class="menu-mobile" id="menu-mobile">
      {#each nav as n}
        <a href={n.href} class:active={estActif(n)}>
          <Icon name={n.icone} size={18} />{n.titre || n.label}
        </a>
      {/each}
      <div class="separateur"></div>
      <a href="/territoire"><Icon name="territoire" size={18} />Le territoire</a>
      <a href="/environnement"><Icon name="environnement" size={18} />Environnement</a>
      <a href="/vie-locale"><Icon name="vie" size={18} />Vie locale</a>
      <form class="recherche mobile" on:submit={chercher} role="search">
        <Icon name="recherche" size={15} />
        <input type="search" bind:value={q} placeholder="Rechercher un acteur…"
               aria-label="Rechercher un acteur" autocomplete="off" />
      </form>
    </div>
  {/if}

  <main>
    <slot />
  </main>

  <footer>
    <div class="fdesc">
      Veille citoyenne — données publiques (SIRENE, RNA, DVF, BODACC, OFGL, DECP, délibérations).
    </div>
    <nav class="fnav">
      <a href="/territoire">Le territoire</a>
      <a href="/environnement">Environnement</a>
      <a href="/vie-locale">Vie locale</a>
      <a href="/methode">Méthode &amp; sources</a>
      <a href="/repliquer">Répliquer</a>
      <a href="/mentions-legales">Mentions légales</a>
      <a href="/contact">Droit de réponse</a>
    </nav>
  </footer>
</div>

<style>
  /* ------------------------------------------------------------------
     Jetons de design. Le site tournait sur la palette Tailwind par
     défaut (slate 900 / blue 600) : correcte mais anonyme. Encre + papier +
     un seul accent (bleu d'ardoise), et les couleurs de l'argent tenues
     à l'écart de l'accent pour qu'un montant ne ressemble pas à un lien.
     ------------------------------------------------------------------ */
  :global(:root) {
    --encre:      #14202a;
    --papier:     #f6f7f5;
    --blanc:      #ffffff;
    --ardoise:    #14556b;
    --ardoise-fonce: #0e3f51;
    --ardoise-pale:  #eef3f5;
    --ambre:      #9a6b12;
    --ambre-pale: #f7f1e4;
    --recette:    #2c6e4f;
    --depense:    #a4453a;
    --gris:       #5c6b72;
    --gris-clair: #8a969b;
    --trait:      #dde2df;
    --trait-pale: #eceeea;

    --display: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
    --texte:   system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --data:    ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;

    --rayon: 5px;
    --ombre: 0 1px 2px rgba(20,32,42,.05), 0 6px 18px rgba(20,32,42,.05);
  }

  :global(*) { box-sizing: border-box; }
  :global(body) {
    margin: 0; background: var(--papier); color: var(--encre);
    font-family: var(--texte); line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  :global(a) { color: var(--ardoise); text-decoration: none; }
  :global(a:hover) { text-decoration: underline; }
  :global(:focus-visible) { outline: 2px solid var(--ardoise); outline-offset: 2px; border-radius: 3px; }
  :global(h1), :global(h2), :global(h3) { font-family: var(--display); font-weight: 600; letter-spacing: -.01em; }
  :global(h1) { text-wrap: balance; }

  .app { min-height: 100vh; display: flex; flex-direction: column; }

  header {
    display: flex; align-items: center; gap: 1.6rem;
    padding: .7rem 1.4rem; background: var(--blanc);
    border-bottom: 1px solid var(--trait);
    position: sticky; top: 0; z-index: 1000;
  }
  .brand {
    display: flex; align-items: center; gap: .5rem; white-space: nowrap;
    font-family: var(--display); font-size: 1.08rem; color: var(--encre);
  }
  .brand:hover { text-decoration: none; }
  .brand :global(.icon) { color: var(--ardoise); }
  .brand strong { font-weight: 600; }
  .brand em { font-style: normal; color: var(--gris); }

  .principale { display: flex; gap: 1.35rem; }
  .principale a {
    display: flex; align-items: center; gap: .38rem; white-space: nowrap;
    color: var(--gris); font-size: .87rem; font-weight: 500;
    padding: .3rem 0; border-bottom: 2px solid transparent;
  }
  .principale a:hover { color: var(--encre); text-decoration: none; }
  .principale a.active { color: var(--ardoise); border-bottom-color: var(--ardoise); }

  .recherche {
    margin-left: auto; display: flex; align-items: center; gap: .4rem;
    border: 1px solid var(--trait); border-radius: var(--rayon);
    padding: .3rem .55rem; background: var(--papier); color: var(--gris-clair);
  }
  .recherche:focus-within { border-color: var(--ardoise); background: var(--blanc); }
  .recherche input {
    width: 11rem; border: 0; background: transparent; color: var(--encre);
    font: inherit; font-size: .85rem; padding: 0;
  }
  .recherche input:focus { outline: none; }
  /* Le bouton n'apporte rien visuellement (le champ se soumet à Entrée) mais
     doit rester atteignable au clavier et aux lecteurs d'écran. */
  .recherche button {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }
  .recherche button:focus-visible {
    position: static; width: auto; height: auto; clip: auto; margin: 0;
    padding: .15rem .45rem; font: inherit; font-size: .78rem;
    border: 1px solid var(--ardoise); border-radius: 4px;
    background: var(--blanc); color: var(--ardoise); cursor: pointer;
  }

  .burger {
    display: none; margin-left: auto; padding: .3rem;
    background: none; border: 1px solid transparent; border-radius: var(--rayon);
    color: var(--gris); cursor: pointer;
  }
  .burger:hover { border-color: var(--trait); color: var(--encre); }

  .menu-mobile {
    display: none; background: var(--blanc); border-bottom: 1px solid var(--trait);
    padding: .3rem 0 .8rem; position: sticky; top: 57px; z-index: 999;
  }
  .menu-mobile a {
    display: flex; align-items: center; gap: .65rem;
    padding: .6rem 1.4rem; color: var(--encre); font-size: .93rem;
  }
  .menu-mobile a:hover { text-decoration: none; background: var(--papier); }
  .menu-mobile a :global(.icon) { color: var(--gris); }
  .menu-mobile a.active {
    color: var(--ardoise); background: var(--ardoise-pale);
    box-shadow: inset 2px 0 0 var(--ardoise);
  }
  .menu-mobile a.active :global(.icon) { color: var(--ardoise); }
  .menu-mobile .separateur { height: 1px; background: var(--trait-pale); margin: .4rem 1.4rem; }
  .recherche.mobile { margin: .6rem 1.4rem 0; }
  .recherche.mobile input { width: 100%; }

  main { flex: 1; }

  footer {
    padding: 1.6rem 1.4rem; background: var(--encre); color: #9fb0b6;
    font-size: .85rem; display: flex; justify-content: space-between;
    gap: 1rem 1.5rem; flex-wrap: wrap;
  }
  .fdesc { max-width: 46ch; }
  .fnav { display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-start; }
  footer a { color: #cfdadd; }

  @media (max-width: 900px) {
    header { gap: .8rem; padding: .6rem 1rem; }
    .principale, .recherche:not(.mobile) { display: none; }
    .burger { display: flex; }
    .menu-mobile { display: block; }
    footer { padding: 1.4rem 1rem; }
  }
</style>
