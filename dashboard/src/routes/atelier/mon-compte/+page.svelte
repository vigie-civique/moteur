<script>
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { COMMUNE } from '$lib/instance.js'
  import { LIBELLE_ROLE, DESCRIPTION_ROLE, messageErreur } from '$lib/roles.js'
  import ChoixTheme from '$lib/components/ChoixTheme.svelte'

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
    <h2>Affichage</h2>
    <p class="muted">« Système » suit le réglage clair ou sombre de cet ordinateur. Le choix est retenu sur ce navigateur seulement.</p>
    <div><ChoixTheme /></div>
  </section>

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
  h1 { font-size: 1.2rem; color: var(--texte); }
  h2 { font-size: .95rem; color: var(--texte); margin-bottom: .6rem; }
  .carte { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px; padding: 1rem; display: flex; flex-direction: column; gap: .35rem; line-height: 1.5; }
  form { display: flex; flex-direction: column; gap: .7rem; }
  label { display: flex; flex-direction: column; gap: .3rem; color: var(--texte-2); }
  input { background: var(--fond); border: 1px solid var(--bordure); border-radius: 6px; color: var(--texte); padding: .55rem .7rem; font-size: .9rem; }
  button { background: var(--bouton); color: var(--sur-accent); border-radius: 6px; padding: .6rem .9rem; font-weight: 600; align-self: flex-start; }
  button:disabled { opacity: .45; cursor: default; }
  .muted { color: var(--texte-doux); }
  .aide { color: var(--alerte); font-size: .82rem; }
  .erreur { background: var(--danger-doux); border: 1px solid var(--danger-bordure); border-radius: 6px; color: var(--danger-texte); padding: .5rem .7rem; }
  .ok { background: var(--succes-doux); border: 1px solid var(--succes-bordure); border-radius: 6px; color: var(--succes-texte); padding: .5rem .7rem; }
</style>
