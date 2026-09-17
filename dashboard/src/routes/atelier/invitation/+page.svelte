<script>
  // Page ouverte SANS session : c'est ici que l'invité crée son compte, ou
  // qu'un compte existant repose son mot de passe. Le jeton arrive dans le
  // fragment de l'adresse (#…), que le navigateur n'envoie jamais au serveur.
  import { onMount } from 'svelte'
  import { goto } from '$app/navigation'
  import { SITE_NOM, COMMUNE } from '$lib/instance.js'
  import { currentUser } from '$lib/stores/auth.js'
  import { heureLocale } from '$lib/heure.js'
  import { DESCRIPTION_ROLE, messageErreur } from '$lib/roles.js'

  let jeton = ''
  let invitation = null
  let erreur = ''
  let chargement = true
  let motdepasse = ''
  let confirmation = ''
  let envoi = false

  onMount(async () => {
    jeton = decodeURIComponent(location.hash.slice(1))
    // Le jeton ne reste pas dans la barre d'adresse ni dans l'historique.
    history.replaceState(null, '', location.pathname)
    if (!jeton) {
      erreur = "Ce lien est incomplet. Ouvrez le lien reçu en entier, ou demandez-en un nouveau à un administrateur."
      chargement = false
      return
    }
    try {
      const r = await fetch('/api/auth/invitation/lire', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jeton }),
      })
      const d = await r.json()
      if (r.ok) invitation = d
      else erreur = messageErreur(d.detail, 'Lien non reconnu.')
    } catch {
      erreur = "L'atelier ne répond pas."
    } finally {
      chargement = false
    }
  })

  $: tropCourt = motdepasse.length > 0 && motdepasse.length < 12
  $: differents = confirmation.length > 0 && confirmation !== motdepasse
  $: pret = motdepasse.length >= 12 && motdepasse === confirmation

  async function accepter() {
    if (!pret) return
    envoi = true; erreur = ''
    try {
      const r = await fetch('/api/auth/invitation/accepter', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jeton, motdepasse }),
      })
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      sessionStorage.setItem('atelier_access', d.access_token)
      localStorage.setItem('atelier_refresh', d.refresh_token)
      currentUser.set(d.user)
      goto('/atelier')
    } catch {
      erreur = "L'atelier ne répond pas."
    } finally {
      envoi = false
    }
  }
</script>

<svelte:head><title>Invitation — Atelier {COMMUNE}</title></svelte:head>

<div class="wrap">
  <div class="carte">
    <h1>Atelier de {SITE_NOM}</h1>

    {#if chargement}
      <p class="muted">Lecture du lien…</p>
    {:else if invitation}
      {#if invitation.nature === 'compte'}
        <p>
          <b>{invitation.invite_par ?? 'Un administrateur'}</b> vous invite à rejoindre l'atelier
          comme <b>{invitation.role_libelle}</b>.
        </p>
        <p class="role">{DESCRIPTION_ROLE[invitation.role]}</p>
      {:else}
        <p>Choisissez un nouveau mot de passe pour votre compte.</p>
      {/if}

      <form on:submit|preventDefault={accepter}>
        <label>Adresse de connexion
          <input type="email" value={invitation.email} readonly autocomplete="username" />
        </label>
        <label><span>Mot de passe <span class="muted">(12 caractères au moins)</span></span>
          <input type="password" bind:value={motdepasse} autocomplete="new-password" disabled={envoi} />
        </label>
        {#if tropCourt}<p class="aide">Encore {12 - motdepasse.length} caractère(s).</p>{/if}
        <label>Le même, une seconde fois
          <input type="password" bind:value={confirmation} autocomplete="new-password" disabled={envoi} />
        </label>
        {#if differents}<p class="aide">Les deux mots de passe ne sont pas identiques.</p>{/if}

        {#if erreur}<p class="erreur">{erreur}</p>{/if}

        <button type="submit" disabled={!pret || envoi}>
          {envoi ? 'Création…' : invitation.nature === 'compte' ? 'Créer mon compte et entrer' : 'Enregistrer et entrer'}
        </button>
        <p class="muted petit">Lien valable une seule fois, jusqu'au {heureLocale(invitation.expire_le)}.</p>
      </form>
    {:else}
      <p class="erreur">{erreur}</p>
      <p><a href="/atelier/login">Aller à la page de connexion</a></p>
    {/if}
  </div>
</div>

<style>
  .wrap { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; padding: 16px; }
  .carte { width: 100%; max-width: 440px; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1.75rem; display: flex; flex-direction: column; gap: .8rem; font-size: .92rem; line-height: 1.5; }
  h1 { font-size: 1.15rem; color: #e2e8f0; }
  .role { color: #cbd5e1; background: #0f172a; border-radius: 6px; padding: .6rem .75rem; font-size: .85rem; }
  form { display: flex; flex-direction: column; gap: .7rem; margin-top: .3rem; }
  label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; color: #cbd5e1; }
  input { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: .6rem .7rem; font-size: .95rem; }
  input[readonly] { color: #94a3b8; }
  input:focus { outline: none; border-color: #3b82f6; }
  button { background: #2563eb; color: #fff; border-radius: 6px; padding: .7rem; font-weight: 600; font-size: .95rem; }
  button:disabled { opacity: .45; cursor: default; }
  .muted { color: #94a3b8; }
  .petit { font-size: .8rem; }
  .aide { color: #fbbf24; font-size: .82rem; }
  .erreur { background: #450a0a; border: 1px solid #7f1d1d; border-radius: 6px; color: #fecaca; padding: .55rem .7rem; }
</style>
