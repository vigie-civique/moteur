<script>
  // Les tâches nées des lacunes des dossiers (collectors/taches.py), 03/10/2026.
  //
  // Chacune tient en une vingtaine de minutes pour quelqu'un qui n'a jamais
  // ouvert un terminal : choisir un acte parmi quelques-uns, écrire une
  // demande, résumer une réponse. Répondre PROPOSE ; un validateur valide.
  // Rien ici n'écrit dans un dossier : la réponse validée attend l'éditeur,
  // et c'est son changement du texte qui ferme la tâche.
  import { onMount } from 'svelte'
  import { authFetch } from '$lib/stores/auth.js'
  import { COMMUNE } from '$lib/instance.js'
  import { heureLocale } from '$lib/heure.js'
  import { messageErreur } from '$lib/roles.js'

  const NATURE = { relier: 'Relier une citation', demander: 'Préparer une demande', verser: 'Verser une réponse' }
  const ETAT = {
    ouverte: 'à faire', proposee: 'réponse à valider',
    validee: "validée — à reporter dans le dossier par l'éditeur", fermee: 'fermée',
  }
  const QUOI = {
    creee: 'relevée', proposee: 'réponse proposée', validee: 'validée', renvoyee: 'renvoyée',
    envoyee: 'demande envoyée', fermee: 'fermée', reouverte: 'rouverte', etat_lacune: 'état changé dans le dossier',
  }

  let vue = 'a_faire'
  let taches = []
  let peutValider = false
  let croisee = true
  let moi = null
  let nbDossiers = 0
  let chargement = true
  let erreur = ''
  let ouverte = null       // l'id de la tâche dépliée
  let saisie = {}          // id → contenu en cours
  let motifs = {}
  let envois = {}
  let enCours = null

  onMount(charger)

  async function charger() {
    chargement = true; erreur = ''
    try {
      const r = await authFetch(`/atelier/taches?etat=${vue}`)
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      taches = d.taches; peutValider = d.peut_valider; croisee = d.relecture_croisee
      moi = d.moi; nbDossiers = d.dossiers
    } finally { chargement = false }
  }

  // Une demande se prépare à partir de la lacune : on ne part pas d'une page blanche.
  function modele(t) {
    const l = t.lacune || {}
    return {
      destinataire: '', objet: l.question || '',
      texte: `Madame, Monsieur,\n\nDans le cadre d'un travail d'information des habitants, `
           + `nous souhaiterions obtenir communication des documents permettant de connaître : `
           + `${l.question || ''}.\n\nCe que nous savons déjà : ${l.ou_on_en_est || '—'}.\n\n`
           + `Cette demande s'appuie sur le droit d'accès aux documents administratifs `
           + `(articles L311-1 et suivants du code des relations entre le public et l'administration).\n\n`
           + `Avec nos remerciements,`,
      envoye_le: '',
    }
  }
  function deplier(t) {
    ouverte = ouverte === t.id ? null : t.id
    if (!saisie[t.id]) {
      saisie[t.id] = t.nature === 'demander' ? modele(t)
        : t.nature === 'verser' ? { resume: '', recu_le: '', ou: '' }
        : { cle: '', note: '' }
    }
  }

  async function poster(t, chemin, corps) {
    enCours = t.id; erreur = ''
    try {
      const r = await authFetch(`/atelier/taches/${t.id}/${chemin}`, { method: 'POST', body: JSON.stringify(corps) })
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      await charger()
      ouverte = t.id
    } finally { enCours = null }
  }

  const peutTrancher = (t) => peutValider && t.etat === 'proposee' && !(croisee && t.propose_par === moi)
  const jour = (d) => d ? `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : ''
</script>

<svelte:head><title>Ce que les dossiers ne savent pas — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <h1>Ce que les dossiers ne savent pas</h1>
  <p class="intro">
    Chaque question ouverte d'un dossier, et chaque citation qui ne mène à aucun
    acte publié, est une tâche. Répondre <strong>propose</strong> ; un validateur
    valide. Rien n'est écrit dans un dossier : l'éditeur reprend la réponse, et
    sa correction ferme la tâche.
  </p>

  <div class="filtres">
    <button class:actif={vue === 'a_faire'} on:click={() => { vue = 'a_faire'; charger() }}>À faire</button>
    <button class:actif={vue === 'fermee'} on:click={() => { vue = 'fermee'; charger() }}>Fermées</button>
  </div>

  {#if erreur}<p class="avis">{erreur}</p>{/if}

  {#if chargement}<p class="muted">Relevé des dossiers…</p>
  {:else if !taches.length}
    <p class="muted vide">
      {#if vue === 'fermee'}Aucune tâche n'a encore été refermée par un dossier.
      {:else if !nbDossiers}Cette instance n'a aucun dossier : rien ne peut y être ouvert.
      {:else}Aucun des {nbDossiers} dossiers ne déclare de question ouverte, ni de citation sans acte publié.{/if}
    </p>
  {:else}
    {#each taches as t (t.id)}
      <article>
        <header>
          <p class="nature">{NATURE[t.nature]} · dossier « {t.dossier_titre} »{#if t.lacune?.section} · § {t.lacune.section}{/if}</p>
          <h2>{t.libelle}</h2>
          <p class="etat">
            {ETAT[t.etat]}
            {#if t.etat_lacune} · dans le dossier : « {t.lacune?.etat_libelle || t.etat_lacune} »{/if}
            {#if t.envoye_le} · demande envoyée le {jour(t.envoye_le)}{/if}
            {#if t.raison} · {t.raison}{/if}
          </p>
          {#if t.lacune?.ou_on_en_est}<p class="muted">Où on en est : {t.lacune.ou_on_en_est}</p>{/if}
          {#if t.lacune?.comment}<p class="muted">Comment le savoir : {t.lacune.comment}</p>{/if}
        </header>

        {#if t.a_reporter}
          <p class="reporter">À reporter dans le dossier : <code>{t.a_reporter}</code></p>
        {/if}

        {#if t.reponse && t.etat !== 'ouverte'}
          <div class="reponse">
            <p class="muted">Réponse proposée{#if t.propose_par_email} par {t.propose_par_email}{/if}{#if t.propose_le}, {heureLocale(t.propose_le)}{/if}</p>
            {#if t.nature === 'relier'}
              <p>{t.reponse.cle ? `Acte ${t.reponse.cle}` : 'Aucun des actes proposés'}{#if t.reponse.note} — {t.reponse.note}{/if}</p>
            {:else if t.nature === 'demander'}
              <p><strong>À :</strong> {t.reponse.destinataire} · <strong>Objet :</strong> {t.reponse.objet}</p>
              <pre>{t.reponse.texte}</pre>
            {:else}
              <p>{t.reponse.resume}</p>
              {#if t.reponse.ou}<p class="muted">Où la trouver : {t.reponse.ou}</p>{/if}
            {/if}
          </div>
        {/if}

        {#if peutTrancher(t)}
          <div class="gestes">
            <input placeholder="Motif (obligatoire pour renvoyer)" bind:value={motifs[t.id]} />
            <button class="oui" disabled={enCours === t.id} on:click={() => poster(t, 'decision', { accepter: true, motif: motifs[t.id] || '' })}>Valider</button>
            <button class="non" disabled={enCours === t.id} on:click={() => poster(t, 'decision', { accepter: false, motif: motifs[t.id] || '' })}>Renvoyer</button>
          </div>
        {:else if peutValider && t.etat === 'proposee'}
          <p class="muted">Vous avez apporté cette réponse : un autre validateur la relira.</p>
        {/if}

        {#if t.nature === 'demander' && t.etat === 'validee'}
          <div class="gestes">
            <label>Envoyée le <input type="date" bind:value={envois[t.id]} /></label>
            <button disabled={!envois[t.id] || enCours === t.id} on:click={() => poster(t, 'envoi', { envoye_le: envois[t.id] })}>Noter l'envoi</button>
          </div>
        {/if}

        {#if t.etat === 'ouverte' || t.etat === 'proposee'}
          <button class="deplier" on:click={() => deplier(t)}>
            {ouverte === t.id ? 'Replier' : t.etat === 'proposee' ? 'Proposer une autre réponse' : 'Répondre'}
          </button>
        {/if}

        {#if ouverte === t.id && saisie[t.id]}
          <form class="saisie" on:submit|preventDefault={() => poster(t, 'reponse', { contenu: saisie[t.id] })}>
            {#if t.nature === 'relier'}
              {#if t.candidats?.length}
                <p>Lequel de ces actes publiés la phrase voulait-elle dire ?</p>
                {#each t.candidats as c}
                  <label class="candidat">
                    <input type="radio" bind:group={saisie[t.id].cle} value={c.cle} />
                    <span>{jour(c.date)} · {c.assemblee}{#if c.numero} · n°{c.numero}{/if} — {c.titre}
                      <a href={c.url} target="_blank" rel="noopener">voir l'acte</a>{#if c.source_url} · <a href={c.source_url} target="_blank" rel="noopener">pièce source</a>{/if}</span>
                  </label>
                {/each}
                <label class="candidat"><input type="radio" bind:group={saisie[t.id].cle} value="" /> <span>Aucun de ces actes</span></label>
              {:else}
                <p class="muted">Aucun acte publié n'est daté près de cette citation : l'acte n'est peut-être pas publié, ou la date est fausse. Dites ce que vous avez trouvé.</p>
              {/if}
              <label>Ce que vous avez vérifié <textarea rows="2" bind:value={saisie[t.id].note}></textarea></label>
            {:else if t.nature === 'demander'}
              <label>À qui écrire <input bind:value={saisie[t.id].destinataire} placeholder="la mairie, le syndicat, la préfecture…" /></label>
              <label>Objet <input bind:value={saisie[t.id].objet} /></label>
              <label>La demande <textarea rows="10" bind:value={saisie[t.id].texte}></textarea></label>
              <label>Déjà envoyée le (facultatif) <input type="date" bind:value={saisie[t.id].envoye_le} /></label>
            {:else}
              <label>Ce que dit la réponse <textarea rows="4" bind:value={saisie[t.id].resume}></textarea></label>
              <label>Reçue le <input type="date" bind:value={saisie[t.id].recu_le} /></label>
              <label>Où la trouver (lien, document de l'atelier, courrier) <input bind:value={saisie[t.id].ou} /></label>
            {/if}
            <div class="gestes"><button class="oui" disabled={enCours === t.id}>Proposer cette réponse</button></div>
          </form>
        {/if}

        {#if t.journal?.length}
          <details>
            <summary>Historique</summary>
            <ul class="journal">
              {#each t.journal as j}<li>{heureLocale(j.le)} — {QUOI[j.quoi] ?? j.quoi}{#if j.par} par {j.par}{/if}{#if j.detail && typeof j.detail === 'string' && !j.detail.startsWith('{')} : {j.detail}{/if}</li>{/each}
            </ul>
          </details>
        {/if}
      </article>
    {/each}
  {/if}
</div>

<style>
  .page { padding: 1.2rem; display: flex; flex-direction: column; gap: .8rem; font-size: .9rem; max-width: 60rem; }
  h1 { font-size: 1.2rem; color: var(--texte); }
  h2 { font-size: 1rem; color: var(--texte); margin: .2rem 0; }
  .intro { color: var(--texte-2); }
  .filtres { display: flex; gap: .4rem; flex-wrap: wrap; }
  .filtres button { border: 1px solid var(--bordure-forte); border-radius: 6px; padding: .35rem .7rem; color: var(--texte-2); }
  .filtres button.actif { background: var(--accent-fort); border-color: var(--accent-fort); color: var(--sur-accent); }
  article { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px; padding: .8rem; display: flex; flex-direction: column; gap: .5rem; }
  .nature, .etat { color: var(--texte-doux); font-size: .82rem; margin: 0; }
  .reporter code, pre { background: var(--fond); border: 1px solid var(--bordure); border-radius: 5px; padding: .3rem .5rem; color: var(--texte); white-space: pre-wrap; overflow-wrap: anywhere; }
  .reponse { border-left: 3px solid var(--bordure-forte); padding-left: .6rem; }
  .saisie { display: flex; flex-direction: column; gap: .5rem; }
  .saisie label { display: flex; flex-direction: column; gap: .2rem; color: var(--texte-2); }
  .saisie label.candidat { flex-direction: row; align-items: baseline; gap: .5rem; color: var(--texte); }
  .saisie input:not([type=radio]), .saisie textarea, .gestes input { background: var(--fond); border: 1px solid var(--bordure); color: var(--texte); border-radius: 5px; padding: .4rem .5rem; font: inherit; }
  a { color: var(--info); }
  .gestes { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .gestes input { flex: 1; min-width: 14rem; }
  .gestes button, .deplier { border-radius: 6px; padding: .45rem .8rem; border: 1px solid var(--bordure-forte); color: var(--texte); align-self: flex-start; }
  .gestes button.oui { background: var(--succes-bordure); border-color: var(--succes-bordure); }
  .gestes button.non { background: transparent; }
  button:disabled { opacity: .5; }
  .journal { margin: .3rem 0 0; padding-left: 1.1rem; color: var(--texte-2); font-size: .82rem; }
  .muted { color: var(--texte-doux); margin: 0; }
  .vide { padding: 1rem 0; }
  .avis { background: var(--alerte-doux); border: 1px solid var(--alerte-bordure); border-radius: 6px; color: var(--alerte-texte); padding: .5rem .75rem; }
</style>
