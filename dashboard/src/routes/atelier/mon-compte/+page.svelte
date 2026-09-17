<script>
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { COMMUNE } from '$lib/instance.js'
  import { LIBELLE_ROLE, DESCRIPTION_ROLE, messageErreur } from '$lib/roles.js'

  let actuel = ''
  let nouveau = ''
  let confirmation = ''
  let envoi = false
  let erreur = ''
  let fait = false

  $: pret = actuel && nouveau.length >= 12 && nouveau === confirmation

  async function changer() {
    envoi = true; erreur = ''; fait = false
    try {
      const r = await authFetch('/auth/mot-de-passe', {
        method: 'POST', body: JSON.stringify({ actuel, nouveau }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { erreur = messageErreur(d.detail, `Échec (${r.status})`); return }
      // Les autres sessions du compte sont closes ; celle-ci reçoit des jetons neufs.
      sessionStorage.setItem('atelier_access', d.access_token)
      localStorage.setItem('atelier_refresh', d.refresh_token)
      actuel = nouveau = confirmation = ''
      fait = true
    } finally {
      envoi = false
    }
  }
</script>

<svelte:head><title>Mon compte — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <h1>Mon compte</h1>

  {#if $currentUser}
    <section class="carte">
      <p><b>{$currentUser.email}</b></p>
      <p>Rôle : <b>{LIBELLE_ROLE[$currentUser.role]}</b></p>
      <p class="muted">{DESCRIPTION_ROLE[$currentUser.role]}</p>
    </section>
  {/if}

  <section class="carte">
    <h2>Changer de mot de passe</h2>
    <form on:submit|preventDefault={changer}>
      <label>Mot de passe actuel
        <input type="password" bind:value={actuel} autocomplete="current-password" /></label>
      <label><span>Nouveau mot de passe <span class="muted">(12 caractères au moins)</span></span>
        <input type="password" bind:value={nouveau} autocomplete="new-password" /></label>
      <label>Le même, une seconde fois
        <input type="password" bind:value={confirmation} autocomplete="new-password" /></label>
      {#if confirmation && confirmation !== nouveau}<p class="aide">Les deux mots de passe ne sont pas identiques.</p>{/if}
      {#if erreur}<p class="erreur">{erreur}</p>{/if}
      {#if fait}<p class="ok">Mot de passe changé. Vos autres sessions ouvertes (autre navigateur, autre poste) sont fermées.</p>{/if}
      <button disabled={!pret || envoi}>{envoi ? 'Enregistrement…' : 'Changer le mot de passe'}</button>
    </form>
  </section>
</div>

<style>
  .page { padding: 1.2rem; max-width: 560px; display: flex; flex-direction: column; gap: 1rem; font-size: .9rem; }
  h1 { font-size: 1.2rem; color: #e2e8f0; }
  h2 { font-size: .95rem; color: #e2e8f0; margin-bottom: .6rem; }
  .carte { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem; display: flex; flex-direction: column; gap: .35rem; line-height: 1.5; }
  form { display: flex; flex-direction: column; gap: .7rem; }
  label { display: flex; flex-direction: column; gap: .3rem; color: #cbd5e1; }
  input { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: .55rem .7rem; font-size: .9rem; }
  button { background: #2563eb; color: #fff; border-radius: 6px; padding: .6rem .9rem; font-weight: 600; align-self: flex-start; }
  button:disabled { opacity: .45; cursor: default; }
  .muted { color: #94a3b8; }
  .aide { color: #fbbf24; font-size: .82rem; }
  .erreur { background: #450a0a; border: 1px solid #7f1d1d; border-radius: 6px; color: #fecaca; padding: .5rem .7rem; }
  .ok { background: #052e16; border: 1px solid #166534; border-radius: 6px; color: #bbf7d0; padding: .5rem .7rem; }
</style>
