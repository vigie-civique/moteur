<script>
  import { goto } from '$app/navigation'
  import { currentUser } from '$lib/stores/auth.js'

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
        error = data.detail || 'Erreur de connexion'
        return
      }
      sessionStorage.setItem('atelier_access',  data.access_token)
      localStorage.setItem('atelier_refresh', data.refresh_token)
      currentUser.set(data.user)
      goto('/atelier')
    } catch {
      error = 'Serveur inaccessible'
    } finally {
      loading = false
    }
  }
</script>

<svelte:head><title>Connexion — Atelier Lasalle</title></svelte:head>

<div class="login-wrap">
  <div class="login-card">
    <div class="login-header">
      <span class="dot"></span>
      <div>
        <h1>Atelier</h1>
        <p>Vigie Civique Lasalle — accès restreint</p>
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
  </div>
</div>

<style>
  .login-wrap {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0f172a;
  }

  .login-card {
    width: 360px;
    background: #1e293b;
    border: 1px solid #334155;
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
    background: #ef4444;
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
    color: #e2e8f0;
  }

  p {
    font-size: .75rem;
    color: #64748b;
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
    color: #94a3b8;
  }

  input {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #e2e8f0;
    padding: .55rem .7rem;
    font-size: .88rem;
    font-family: inherit;
    transition: border-color .15s;
  }
  input:focus { outline: none; border-color: #3b82f6; }
  input:disabled { opacity: .5; }

  .error {
    background: #450a0a;
    border: 1px solid #7f1d1d;
    border-radius: 6px;
    color: #fca5a5;
    padding: .5rem .7rem;
    font-size: .8rem;
  }

  .submit {
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: .6rem;
    font-size: .88rem;
    font-weight: 600;
    cursor: pointer;
    margin-top: .25rem;
    transition: background .15s;
  }
  .submit:hover:not(:disabled) { background: #1d4ed8; }
  .submit:disabled { opacity: .45; cursor: default; }
</style>
