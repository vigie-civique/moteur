<script>
  import { COMMUNE, SITE_NOM } from '$lib/instance.js'
  import { goto } from '$app/navigation'
  import { onMount } from 'svelte'
  import { currentUser } from '$lib/stores/auth.js'
  import { messageErreur } from '$lib/roles.js'

  // Sans aucun compte, personne ne peut en inviter : le dire, plutôt que de
  // laisser chercher un mot de passe qui n'existe pas.
  let aucunCompte = false
  onMount(async () => {
    try {
      const r = await fetch('/api/auth/etat')
      if (r.ok) aucunCompte = !(await r.json()).comptes
    } catch { /* l'erreur de connexion le dira */ }
  })

  let email    = ''
  let password = ''
  let error    = ''
  let loading  = false

  async function handleLogin() {
    if (!email || !password) return
    loading = true
    error   = ''
    try {
      const res = await fetch('/api/auth/login', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (!res.ok) {
        error = messageErreur(data.detail, 'Erreur de connexion')
        return
      }
      sessionStorage.setItem('atelier_access',  data.access_token)
      currentUser.set(data.user)
      goto('/atelier')
    } catch {
      error = 'Serveur inaccessible'
    } finally {
      loading = false
    }
  }
</script>

<svelte:head><title>Connexion — Atelier {COMMUNE}</title></svelte:head>

<div class="login-wrap">
  <div class="login-card">
    <div class="login-header">
      <span class="dot"></span>
      <div>
        <h1>Atelier</h1>
        <p>{SITE_NOM} — accès restreint</p>
      </div>
    </div>

    <form on:submit|preventDefault={handleLogin}>
      <label>
        Email
        <input
          type="email"
          bind:value={email}
          autocomplete="email"
          placeholder="vous@exemple.fr"
          disabled={loading}
          required
        />
      </label>

      <label>
        Mot de passe
        <input
          type="password"
          bind:value={password}
          autocomplete="current-password"
          disabled={loading}
          required
        />
      </label>

      {#if error}
        <p class="error">{error}</p>
      {/if}

      <button type="submit" class="submit" disabled={loading || !email || !password}>
        {loading ? 'Connexion...' : 'Se connecter'}
      </button>
    </form>

    {#if aucunCompte}
      <p class="note">
        Cet atelier n'a encore aucun compte. Le premier compte administrateur se crée
        à l'installation ; c'est ensuite lui qui invite les autres personnes.
      </p>
    {:else}
      <p class="note">
        On entre dans l'atelier sur invitation d'un administrateur. Vous avez reçu un lien ?
        Ouvrez-le pour créer votre compte. Mot de passe oublié : demandez un nouveau lien
        à un administrateur.
      </p>
    {/if}
  </div>
</div>

<style>
  .login-wrap {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--fond);
  }

  .login-card {
    width: 360px;
    background: var(--surface);
    border: 1px solid var(--bordure);
    border-radius: 10px;
    padding: 2rem;
  }

  .login-header {
    display: flex;
    align-items: center;
    gap: .75rem;
    margin-bottom: 1.75rem;
  }

  .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--danger);
    flex-shrink: 0;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: .3; }
  }

  h1 {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--texte);
  }

  p {
    font-size: .75rem;
    color: var(--texte-doux);
    margin-top: 2px;
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: .35rem;
    font-size: .8rem;
    color: var(--texte-doux);
  }

  input {
    background: var(--fond);
    border: 1px solid var(--bordure);
    border-radius: 6px;
    color: var(--texte);
    padding: .55rem .7rem;
    font-size: .88rem;
    font-family: inherit;
    transition: border-color .15s;
  }
  input:focus { outline: none; border-color: var(--focus); }
  input:disabled { opacity: .5; }

  .error {
    background: var(--danger-doux);
    border: 1px solid var(--danger-bordure);
    border-radius: 6px;
    color: var(--danger-texte);
    padding: .5rem .7rem;
    font-size: .8rem;
  }

  .submit {
    background: var(--bouton);
    color: var(--sur-accent);
    border: none;
    border-radius: 6px;
    padding: .6rem;
    font-size: .88rem;
    font-weight: 600;
    cursor: pointer;
    margin-top: .25rem;
    transition: background .15s;
  }
  .submit:hover:not(:disabled) { background: var(--accent-fort); }
  .submit:disabled { opacity: .45; cursor: default; }

  .note {
    margin-top: 1.1rem;
    font-size: .78rem;
    line-height: 1.5;
    color: var(--texte-doux);
  }
</style>
