<script>
  import ChoixTheme from '$lib/components/ChoixTheme.svelte'
  import { onMount } from 'svelte'
  import { goto } from '$app/navigation'
  import { page } from '$app/stores'
  import { currentUser, logout, rafraichir } from '$lib/stores/auth.js'
  import { LIBELLE_ROLE, auMoins } from '$lib/roles.js'

  let ready = false

  // Pages ouvertes sans session : la connexion, et l'invitation — où l'invité
  // n'a pas encore de compte.
  $: isLogin = ['/atelier/login', '/atelier/invitation'].includes($page.url.pathname)

  onMount(async () => {
    if (isLogin) { ready = true; return }

    // Vérifier le token d'accès courant
    const access = sessionStorage.getItem('atelier_access')
    if (access) {
      const res = await fetch('/api/auth/me', {
        headers: { 'X-Atelier-Session': access },
      })
      if (res.ok) {
        currentUser.set(await res.json())
        ready = true
        return
      }
    }

    // Tenter le rafraîchissement (cookie HttpOnly, cf. stores/auth.js)
    if (await rafraichir()) {
      const me = await fetch('/api/auth/me', {
        headers: { 'X-Atelier-Session': sessionStorage.getItem('atelier_access') },
      })
      if (me.ok) {
        currentUser.set(await me.json())
        ready = true
        return
      }
    }

    // Non authentifié
    sessionStorage.removeItem('atelier_access')
    localStorage.removeItem('atelier_refresh')
    goto('/atelier/login')
  })

  async function handleLogout() {
    await logout()
    goto('/atelier/login')
  }

  // `min` : le rôle à partir duquel la page sert à quelque chose. L'API tient
  // le droit ; le menu évite seulement d'ouvrir une page qui refuserait tout.
  // 23/09/2026 — le menu suit les files (`collectors/files.py`). Avant, il
  // ouvrait sur la liste des 5 484 fiches, ne nommait aucune des files de
  // travail, et deux d'entre elles n'y figuraient pas du tout : `/atelier/geo`
  // existait sans entrée, et les liens présumés n'avaient aucune page.
  const NAV = [
    { href: '/atelier',                        label: "Aujourd'hui" },
    { href: '/atelier/relations',              label: 'Liens présumés' },
    { href: '/atelier/queue/websites',         label: 'Adresses de sites' },
    { href: '/atelier/geo',                    label: 'Points sur la carte' },
    { href: '/atelier/donnees',                label: 'Chiffres à confirmer' },
    { href: '/atelier/propositions',           label: 'Propositions' },
    { href: '/atelier/conseils',               label: 'Conseils en clair' },
    { href: '/atelier/dossiers',               label: 'Dossiers' },
    { href: '/atelier/taches',                 label: 'Ce que les dossiers ne savent pas' },
    { href: '/atelier/fiches',                 label: 'Toutes les fiches' },
    { href: '/atelier/saisie',                 label: 'Saisir une donnée' },
    { href: '/atelier/analyses',               label: 'Analyses croisées', min: 'validator' },
    { href: '/atelier/ia',                     label: 'Recherche IA' },
    { href: '/atelier/publication',            label: 'Publication' },
    { href: '/atelier/journal',                label: 'Journal' },
    { href: '/atelier/comptes',                label: 'Comptes', min: 'admin' },
  ]
  $: nav = NAV.filter(n => !n.min || auMoins($currentUser, n.min))
</script>

{#if isLogin}
  <slot />
{:else if ready && $currentUser}
  <div class="atelier-shell">
    <aside class="atelier-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">Atelier</span>
        <span class="role-badge" class:admin={$currentUser.role === 'admin'}>{LIBELLE_ROLE[$currentUser.role] ?? $currentUser.role}</span>
      </div>

      <nav class="sidebar-nav">
        {#each nav as n}
          <a href={n.href} class:active={$page.url.pathname === n.href}>{n.label}</a>
        {/each}
      </nav>

      <div class="sidebar-footer">
        <a class="user-email" href="/atelier/mon-compte" title="Mon compte">{$currentUser.email}</a>
        <ChoixTheme />
        <button class="logout-btn" on:click={handleLogout}>Déconnexion</button>
      </div>
    </aside>

    <div class="atelier-content">
      <slot />
    </div>
  </div>
{/if}

<style>
  .atelier-shell {
    display: flex;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }

  .atelier-sidebar {
    width: 200px;
    flex-shrink: 0;
    background: var(--surface);
    border-right: 1px solid var(--bordure);
    display: flex;
    flex-direction: column;
    padding: .75rem 0;
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 .9rem .6rem;
    border-bottom: 1px solid var(--bordure);
    margin-bottom: .4rem;
  }

  .sidebar-title {
    font-weight: 700;
    font-size: .85rem;
    color: var(--texte);
  }

  .role-badge {
    font-size: .65rem;
    padding: 1px 6px;
    border-radius: 999px;
    background: var(--surface-2);
    color: var(--texte-doux);
    text-transform: uppercase;
    letter-spacing: .04em;
  }
  .role-badge.admin { background: var(--accent-fort); color: var(--sur-accent); }

  .sidebar-nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: .25rem .5rem;
    gap: 2px;
  }

  .sidebar-nav a {
    padding: .4rem .65rem;
    border-radius: 5px;
    font-size: .8rem;
    color: var(--texte-doux);
    transition: background .12s;
  }
  .sidebar-nav a.active { background: var(--accent); color: var(--sur-accent); }
  .sidebar-nav a:hover:not(.active) { background: var(--fond); color: var(--texte); }

  .sidebar-footer {
    padding: .6rem .9rem 0;
    border-top: 1px solid var(--bordure);
    display: flex;
    flex-direction: column;
    gap: .4rem;
  }

  .user-email {
    font-size: .72rem;
    color: var(--texte-doux);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .logout-btn {
    font-size: .75rem;
    color: var(--danger);
    text-align: left;
    padding: 0;
    cursor: pointer;
    background: none;
    border: none;
  }
  .logout-btn:hover { text-decoration: underline; }

  .atelier-content {
    flex: 1;
    overflow-y: auto;
    background: var(--fond);
  }

  /* Sur un portable étroit (820 px), le menu latéral mangeait le quart de la
     largeur et les tableaux débordaient : il devient une bande en haut, qui
     défile de côté. */
  @media (max-width: 900px) {
    .atelier-shell { flex-direction: column; }
    .atelier-sidebar {
      width: 100%; flex-direction: row; align-items: center;
      padding: .3rem .5rem; border-right: none; border-bottom: 1px solid var(--bordure);
      overflow-x: auto; gap: .5rem;
    }
    .sidebar-header { border-bottom: none; margin: 0; padding: 0 .4rem; gap: .4rem; }
    .sidebar-nav { flex-direction: row; flex: none; padding: 0; }
    .sidebar-nav a { white-space: nowrap; }
    .sidebar-footer { flex-direction: row; align-items: center; border-top: none; padding: 0 .4rem; }
    .user-email { display: none; }
  }
</style>
