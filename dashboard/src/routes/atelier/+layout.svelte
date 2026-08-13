<script>
  import { onMount } from 'svelte'
  import { goto } from '$app/navigation'
  import { page } from '$app/stores'
  import { currentUser, logout } from '$lib/stores/auth.js'

  let ready = false

  $: isLogin = $page.url.pathname === '/atelier/login'

  onMount(async () => {
    if (isLogin) { ready = true; return }

    // Vérifier le token d'accès courant
    const access = sessionStorage.getItem('atelier_access')
    if (access) {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${access}` },
      })
      if (res.ok) {
        currentUser.set(await res.json())
        ready = true
        return
      }
    }

    // Tenter le refresh
    const refresh = localStorage.getItem('atelier_refresh')
    if (refresh) {
      const rr = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
      if (rr.ok) {
        const data = await rr.json()
        sessionStorage.setItem('atelier_access', data.access_token)
        const me = await fetch('/api/auth/me', {
          headers: { Authorization: `Bearer ${data.access_token}` },
        })
        if (me.ok) {
          currentUser.set(await me.json())
          ready = true
          return
        }
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

  const NAV = [
    { href: '/atelier',                        label: 'File de travail' },
    { href: '/atelier/donnees',                label: 'Données importées' },
    { href: '/atelier/queue/websites',         label: '→ Websites candidats' },
    { href: '/atelier/analyses',               label: 'Analyses croisées' },
    { href: '/atelier/ia',                     label: 'Recherche IA' },
    { href: '/atelier/publication',            label: 'Publication' },
  ]
</script>

{#if isLogin}
  <slot />
{:else if ready && $currentUser}
  <div class="atelier-shell">
    <aside class="atelier-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">Atelier</span>
        <span class="role-badge" class:admin={$currentUser.role === 'admin'}>{$currentUser.role}</span>
      </div>

      <nav class="sidebar-nav">
        {#each NAV as n}
          <a href={n.href} class:active={$page.url.pathname === n.href}>{n.label}</a>
        {/each}
      </nav>

      <div class="sidebar-footer">
        <span class="user-email">{$currentUser.email}</span>
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
    background: #1e293b;
    border-right: 1px solid #334155;
    display: flex;
    flex-direction: column;
    padding: .75rem 0;
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 .9rem .6rem;
    border-bottom: 1px solid #334155;
    margin-bottom: .4rem;
  }

  .sidebar-title {
    font-weight: 700;
    font-size: .85rem;
    color: #e2e8f0;
  }

  .role-badge {
    font-size: .65rem;
    padding: 1px 6px;
    border-radius: 999px;
    background: #334155;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .04em;
  }
  .role-badge.admin { background: #1d4ed8; color: #bfdbfe; }

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
    color: #94a3b8;
    transition: background .12s;
  }
  .sidebar-nav a.active { background: #3b82f6; color: #fff; }
  .sidebar-nav a:hover:not(.active) { background: #0f172a; color: #e2e8f0; }

  .sidebar-footer {
    padding: .6rem .9rem 0;
    border-top: 1px solid #334155;
    display: flex;
    flex-direction: column;
    gap: .4rem;
  }

  .user-email {
    font-size: .72rem;
    color: #64748b;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .logout-btn {
    font-size: .75rem;
    color: #ef4444;
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
    background: #0f172a;
  }
</style>
