<script>
  // Comptes et invitations — réservé aux administrateurs (tenu par l'API).
  // On n'entre dans l'atelier que sur invitation : l'admin inscrit une adresse,
  // choisit le rôle, et transmet le lien à la personne.
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { SITE_NOM, COMMUNE } from '$lib/instance.js'
  import { heureLocale } from '$lib/heure.js'
  import { ROLES, LIBELLE_ROLE, DESCRIPTION_ROLE, auMoins, messageErreur } from '$lib/roles.js'

  let donnees = null
  let erreur = ''
  let avis = ''
  let email = ''
  let role = 'contributor'
  let envoi = false
  // Le lien qu'on vient de fabriquer : son jeton n'est rendu qu'une fois.
  let lien = null          // { email, role, nature, url, expire_le }
  let copie = false

  const ETATS = {
    en_attente: 'En attente', utilisee: 'Acceptée', annulee: 'Annulée', expiree: 'Expirée',
  }

  onMount(charger)

  async function appel(chemin, options = {}) {
    const r = await authFetch(chemin, options)
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(messageErreur(d.detail, `Échec (${r.status})`))
    return d
  }

  async function charger() {
    erreur = ''
    try { donnees = await appel('/admin/comptes') }
    catch (e) { erreur = e.message }
  }

  $: base = donnees?.adresse_atelier || (typeof location !== 'undefined' ? location.origin : '')
  $: seulementIci = !donnees?.adresse_atelier && typeof location !== 'undefined'
       && ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(location.hostname)
  $: enAttente = (donnees?.invitations ?? []).filter(i => i.etat === 'en_attente')
  $: passees = (donnees?.invitations ?? []).filter(i => i.etat !== 'en_attente').slice(0, 20)

  function montrerLien(reponse) {
    const inv = reponse.invitation
    lien = { ...inv, url: `${base}/atelier/invitation#${reponse.jeton}` }
    copie = false
  }

  async function inviter() {
    envoi = true; avis = ''; lien = null
    try {
      const d = await appel('/admin/comptes/invitations', {
        method: 'POST', body: JSON.stringify({ email, role }),
      })
      montrerLien(d)
      email = ''
      await charger()
    } catch (e) { avis = e.message }
    finally { envoi = false }
  }

  async function renouveler(inv) {
    avis = ''
    try { montrerLien(await appel(`/admin/comptes/invitations/${inv.id}/renouveler`, { method: 'POST' })); await charger() }
    catch (e) { avis = e.message }
  }

  async function annuler(inv) {
    avis = ''
    try { await appel(`/admin/comptes/invitations/${inv.id}`, { method: 'DELETE' }); await charger() }
    catch (e) { avis = e.message }
  }

  async function modifier(compte, changement) {
    avis = ''
    try { await appel(`/admin/comptes/${compte.id}`, { method: 'PATCH', body: JSON.stringify(changement) }) }
    catch (e) { avis = e.message }
    await charger()
  }

  async function lienMotDePasse(compte) {
    avis = ''
    try { montrerLien(await appel(`/admin/comptes/${compte.id}/lien-mot-de-passe`, { method: 'POST' })); await charger() }
    catch (e) { avis = e.message }
  }

  async function copier() {
    try { await navigator.clipboard.writeText(lien.url); copie = true }
    catch { copie = false }
  }

  // Le courriel part de la messagerie de l'administrateur : l'atelier n'envoie
  // rien lui-même, et n'a donc aucun identifiant de messagerie à garder.
  $: courriel = lien ? `mailto:${encodeURIComponent(lien.email)}?subject=${encodeURIComponent(
        lien.nature === 'compte' ? `Invitation à l'atelier de ${SITE_NOM}` : `Nouveau mot de passe — atelier de ${SITE_NOM}`
      )}&body=${encodeURIComponent(
        (lien.nature === 'compte'
          ? `Bonjour,\n\nVoici votre invitation à rejoindre l'atelier de ${SITE_NOM}, avec le rôle ${LIBELLE_ROLE[lien.role].toLowerCase()}.\n\nPour créer votre compte, ouvrez ce lien et choisissez votre mot de passe :\n`
          : `Bonjour,\n\nPour choisir un nouveau mot de passe pour l'atelier de ${SITE_NOM}, ouvrez ce lien :\n`)
        + `${lien.url}\n\nIl ne sert qu'une fois et expire le ${heureLocale(lien.expire_le)}.\n\n${$currentUser?.email ?? ''}`
      )}` : ''
</script>

<svelte:head><title>Comptes — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <h1>Comptes</h1>
  <p class="intro">
    On n'entre dans l'atelier que sur invitation. Inscrivez l'adresse de la personne,
    choisissez son rôle, puis transmettez-lui le lien : elle choisira elle-même son mot de passe.
  </p>

  {#if !auMoins($currentUser, 'admin')}
    <p class="avis">La gestion des comptes est réservée aux administrateurs.</p>
  {:else if erreur}
    <p class="avis">{erreur}</p>
  {:else if donnees}

    <section class="carte">
      <h2>Inviter quelqu'un</h2>
      <form on:submit|preventDefault={inviter}>
        <label class="adresse">Adresse électronique
          <input type="email" bind:value={email} placeholder="prenom.nom@exemple.fr" required />
        </label>
        <fieldset>
          <legend>Rôle</legend>
          {#each ROLES as r}
            <label class="choix" class:actif={role === r}>
              <input type="radio" bind:group={role} value={r} />
              <span><b>{LIBELLE_ROLE[r]}</b> — {DESCRIPTION_ROLE[r]}</span>
            </label>
          {/each}
        </fieldset>
        <button class="principal" disabled={envoi || !email}>
          {envoi ? 'Création du lien…' : "Créer le lien d'invitation"}
        </button>
      </form>
      {#if avis}<p class="avis">{avis}</p>{/if}

      {#if lien}
        <div class="lien" role="status">
          <p>
            <b>Lien pour {lien.email}</b>
            {lien.nature === 'compte' ? `(${LIBELLE_ROLE[lien.role].toLowerCase()})` : '(nouveau mot de passe)'} —
            à transmettre maintenant : il ne sera plus affiché. Une seule utilisation, jusqu'au {heureLocale(lien.expire_le)}.
          </p>
          <input readonly value={lien.url} on:focus={(e) => e.target.select()} />
          <div class="actions">
            <button class="principal" on:click={copier}>{copie ? 'Copié ✓' : 'Copier le lien'}</button>
            <a class="bouton" href={courriel}>Écrire le courriel</a>
          </div>
          {#if seulementIci}
            <p class="attention">
              ⚠ Cet atelier est ouvert à l'adresse {location.origin}, qui ne mène qu'à cette machine :
              le lien ne fonctionnera pas ailleurs. Pour inviter quelqu'un qui travaille d'un autre
              poste, l'atelier doit être joignable par le réseau.
            </p>
          {/if}
        </div>
      {/if}
    </section>

    {#if enAttente.length}
      <section class="carte">
        <h2>Invitations en attente</h2>
        <table>
          <thead><tr><th>Adresse</th><th>Rôle</th><th>Invitée par</th><th>Expire le</th><th></th></tr></thead>
          <tbody>
            {#each enAttente as inv (inv.id)}
              <tr>
                <td>{inv.email}{#if inv.nature === 'mot_de_passe'} <span class="muted">(mot de passe)</span>{/if}</td>
                <td>{LIBELLE_ROLE[inv.role]}</td>
                <td>{inv.invite_par ?? '—'}</td>
                <td>{heureLocale(inv.expire_le)}</td>
                <td class="droite">
                  <button class="secondaire" on:click={() => renouveler(inv)}>Nouveau lien</button>
                  <button class="secondaire danger" on:click={() => annuler(inv)}>Annuler</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}

    <section class="carte">
      <h2>Comptes</h2>
      <table>
        <thead><tr><th>Adresse</th><th>Rôle</th><th>Dernière connexion</th><th>État</th><th></th></tr></thead>
        <tbody>
          {#each donnees.comptes as c (c.id)}
            <tr class:inactif={c.desactive_le}>
              <td class="adresse-cell">{c.email}{#if c.id === $currentUser?.id}&nbsp;<span class="muted">(vous)</span>{/if}</td>
              <td>
                <select value={c.role} disabled={!!c.desactive_le}
                        on:change={(e) => modifier(c, { role: e.target.value })}>
                  {#each ROLES as r}<option value={r}>{LIBELLE_ROLE[r]}</option>{/each}
                </select>
              </td>
              <td class="date">{c.last_login ? heureLocale(c.last_login) : 'jamais'}</td>
              <td>{c.desactive_le ? `Désactivé le ${heureLocale(c.desactive_le)}` : 'Actif'}</td>
              <td class="droite">
                {#if c.desactive_le}
                  <button class="secondaire" on:click={() => modifier(c, { actif: true })}>Réactiver</button>
                {:else}
                  <button class="secondaire" on:click={() => lienMotDePasse(c)}>Lien de mot de passe</button>
                  {#if c.id !== $currentUser?.id}
                    <button class="secondaire danger" on:click={() => modifier(c, { actif: false })}>Désactiver</button>
                  {/if}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="muted petit">
        Un compte ne se supprime pas : ce qu'il a fait reste attribué dans le journal.
        Désactivé, il perd l'accès immédiatement.
      </p>
    </section>

    {#if passees.length}
      <details class="carte">
        <summary>Invitations passées ({passees.length})</summary>
        <table>
          <thead><tr><th>Adresse</th><th>Rôle</th><th>Créée le</th><th>État</th></tr></thead>
          <tbody>
            {#each passees as inv (inv.id)}
              <tr><td>{inv.email}</td><td>{LIBELLE_ROLE[inv.role]}</td><td>{heureLocale(inv.cree_le)}</td><td>{ETATS[inv.etat]}</td></tr>
            {/each}
          </tbody>
        </table>
      </details>
    {/if}
  {:else}
    <p class="muted">Chargement…</p>
  {/if}
</div>

<style>
  .page { padding: 1.2rem; max-width: 980px; display: flex; flex-direction: column; gap: 1rem; font-size: .88rem; }
  h1 { font-size: 1.2rem; color: #e2e8f0; }
  h2 { font-size: .95rem; color: #e2e8f0; margin-bottom: .6rem; }
  .intro { color: #cbd5e1; max-width: 70ch; line-height: 1.5; }
  .carte { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem; overflow-x: auto; }
  form { display: flex; flex-direction: column; gap: .8rem; }
  label.adresse { display: flex; flex-direction: column; gap: .3rem; color: #cbd5e1; max-width: 420px; }
  input[type=email], .lien input { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: .55rem .7rem; font-size: .9rem; width: 100%; }
  fieldset { border: none; display: flex; flex-direction: column; gap: .4rem; }
  legend { color: #cbd5e1; margin-bottom: .3rem; }
  .choix { display: flex; gap: .55rem; align-items: flex-start; padding: .5rem .6rem; border: 1px solid #334155; border-radius: 6px; color: #cbd5e1; line-height: 1.45; cursor: pointer; }
  .choix.actif { border-color: #3b82f6; background: #172554; }
  .choix input { margin-top: .25rem; }
  .principal { background: #2563eb; color: #fff; border-radius: 6px; padding: .55rem .9rem; font-weight: 600; align-self: flex-start; }
  .principal:disabled { opacity: .45; cursor: default; }
  .bouton { border: 1px solid #3b82f6; border-radius: 6px; padding: .5rem .9rem; color: #bfdbfe; }
  .secondaire { border: 1px solid #475569; border-radius: 5px; padding: .25rem .55rem; font-size: .78rem; color: #cbd5e1; margin-left: .3rem; }
  .secondaire.danger { border-color: #7f1d1d; color: #fca5a5; }
  .lien { margin-top: 1rem; padding: .8rem; border: 1px solid #1d4ed8; border-radius: 8px; background: #0b1a3a; display: flex; flex-direction: column; gap: .6rem; line-height: 1.5; }
  .actions { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .attention { color: #fde68a; }
  .avis { background: #3b2506; border: 1px solid #b45309; border-radius: 6px; color: #fde68a; padding: .5rem .75rem; margin-top: .6rem; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: #94a3b8; font-weight: 500; font-size: .78rem; padding: .35rem .4rem; border-bottom: 1px solid #334155; }
  td { padding: .45rem .4rem; border-bottom: 1px solid #1f2a3d; color: #e2e8f0; vertical-align: middle; }
  td.droite { text-align: right; white-space: nowrap; }
  td.adresse-cell, td.date { white-space: nowrap; }
  tr.inactif td { color: #64748b; }
  select { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; border-radius: 5px; padding: .25rem .4rem; }
  .muted { color: #94a3b8; }
  .petit { font-size: .8rem; margin-top: .6rem; }
  summary { cursor: pointer; color: #cbd5e1; }
</style>
