<script>
  // Ce qu'un contributeur a voulu écrire sur un objet PUBLIÉ, et qui attend
  // qu'un validateur l'accepte. Le contributeur y voit les siennes.
  import { onMount } from 'svelte'
  import { authFetch } from '$lib/stores/auth.js'
  import { COMMUNE } from '$lib/instance.js'
  import { heureLocale } from '$lib/heure.js'
  import { messageErreur } from '$lib/roles.js'
  import { LIBELLES } from '$lib/champs.js'
  import LigneExtraite from './LigneExtraite.svelte'

  const ETATS = [
    ['en_attente', 'En attente'], ['acceptee', 'Acceptées'],
    ['refusee', 'Refusées'], ['retiree', 'Retirées'],
  ]
  const NATURE = {
    fiche: 'Fiche', coords: 'Point sur la carte', relation: 'Relation', correction: 'Chiffre corrigé',
    marche: 'Marché lu dans un procès-verbal',
  }
  const OBJET = { flow: 'flux', marche: 'marché', deliberation: 'acte' }
  // Les champs d'une relation et d'une correction n'ont pas de libellé commun
  // avec ceux d'une fiche.
  const AUTRES = {
    relation_type: 'Type de relation', since: 'Depuis', until: "Jusqu'à", source: 'Source',
    amount: 'Montant', montant: 'Montant', year: 'Année', date: 'Date', title: 'Titre',
    description: 'Description', source_url: 'Lien source', statut: 'Statut',
    type_norm: 'Nature', date_notif: 'Date de notification', objet: 'Objet',
    titulaire_nom: 'Titulaire', acheteur_nom: 'Acheteur',
  }
  const libelle = (c) => LIBELLES[c] ?? AUTRES[c] ?? c
  const dire = (v) => (v == null || v === '' ? '—' : String(v))

  let etat = 'en_attente'
  let propositions = []
  let peutTrancher = false
  let erreur = ''
  let chargement = true
  let motifs = {}          // id → motif saisi pour un refus
  let enCours = null
  let corrigeables = {}
  // `?nature=marche` : la file des marchés lus, seule. Un rapport en dépose
  // des dizaines d'un coup ; mêlées aux propositions des contributeurs, elles
  // les repousseraient en bas de la file.
  let nature = ''

  onMount(() => {
    nature = new URLSearchParams(window.location.search).get('nature') || ''
    charger()
  })

  async function charger() {
    chargement = true; erreur = ''
    try {
      const r = await authFetch(`/atelier/propositions?etat=${etat}${nature ? `&nature=${nature}` : ''}`)
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      propositions = d.propositions; peutTrancher = d.peut_trancher
      corrigeables = d.corrigeables || {}
    } finally { chargement = false }
  }

  // La valeur a bougé depuis la proposition : la collecte ou un autre éditeur
  // sont passés. Accepter écrasera ce qui est là MAINTENANT — le dire avant.
  const aBouge = (p, c) => p.actuel && dire(p.actuel[c]) !== dire(p.avant[c])

  async function trancher(p, accepter, motifDonne = null, corrections = {}) {
    const motif = (motifDonne ?? motifs[p.id] ?? '').trim()
    if (!accepter && !motif) {
      erreur = 'Refuser demande un motif : la personne qui a proposé doit savoir quoi corriger.'
      return
    }
    enCours = p.id; erreur = ''
    try {
      const r = await authFetch(`/atelier/propositions/${p.id}/decision`, {
        method: 'POST', body: JSON.stringify({ accepter, motif, corrections }),
      })
      if (!r.ok) { erreur = messageErreur((await r.json()).detail); return }
      propositions = propositions.filter(x => x.id !== p.id)
    } finally { enCours = null }
  }

  let depotEnCours = false
  let bilan = null
  async function deposer(ev) {
    const fichier = ev.target.files?.[0]
    if (!fichier) return
    depotEnCours = true; erreur = ''; bilan = null
    try {
      let rapport
      try { rapport = JSON.parse(await fichier.text()) }
      catch { erreur = "Ce fichier n'est pas du JSON lisible."; return }
      const r = await authFetch('/atelier/marches-extraits', {
        method: 'POST', body: JSON.stringify(rapport),
      })
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      bilan = d
      await charger()
    } finally { depotEnCours = false; ev.target.value = '' }
  }

  async function retirer(p) {
    enCours = p.id; erreur = ''
    try {
      const r = await authFetch(`/atelier/propositions/${p.id}`, { method: 'DELETE' })
      if (!r.ok) { erreur = messageErreur((await r.json()).detail); return }
      propositions = propositions.filter(x => x.id !== p.id)
    } finally { enCours = null }
  }
</script>

<svelte:head><title>Propositions — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <h1>Propositions</h1>
  <p class="intro">
    {#if peutTrancher}
      Ce que les contributeurs ont voulu modifier sur des données déjà publiées. Rien n'est
      appliqué tant que vous ne l'avez pas accepté.
    {:else}
      Vos modifications sur des données déjà publiées. Elles seront appliquées quand un
      validateur les aura acceptées.
    {/if}
  </p>

  <div class="filtres">
    {#each ETATS as [cle, nom]}
      <button class:actif={etat === cle} on:click={() => { etat = cle; charger() }}>{nom}</button>
    {/each}
    <button class:actif={nature === 'marche'}
            on:click={() => { nature = nature === 'marche' ? '' : 'marche'; charger() }}>
      Marchés lus dans les PV seulement
    </button>
  </div>

  {#if peutTrancher}
    <!-- Le seul chemin d'entrée d'un rapport d'extraction depuis que l'atelier
         tourne sur un serveur : déposer le fichier ici. Format :
         docs/format-marches-extraits.md. -->
    <details class="depot">
      <summary>Déposer un rapport de marchés extraits des procès-verbaux</summary>
      <p class="muted">Chaque ligne dont la citation se retrouve dans le texte de son acte devient une
        proposition à relire ici, une à une. Rien n'est publié avant. Redéposer le même rapport ne
        propose rien de plus.</p>
      <input type="file" accept="application/json,.json" on:change={deposer} disabled={depotEnCours} />
      {#if bilan}
        <p>{bilan.proposees} ligne(s) proposée(s) sur {bilan.lignes} ;
          {bilan.deja_proposees} déjà proposée(s) ; {bilan.deja_importees} déjà en base ;
          {bilan.refusees.length} refusée(s).</p>
        {#if bilan.refusees.length}
          <ul class="refus">
            {#each bilan.refusees as r}<li>ligne {r.ligne} : {r.motif}</li>{/each}
          </ul>
        {/if}
        {#if bilan.cles_ignorees.length}
          <p class="muted">Colonnes ignorées : {bilan.cles_ignorees.join(', ')}</p>
        {/if}
      {/if}
    </details>
  {/if}

  {#if erreur}<p class="avis">{erreur}</p>{/if}

  {#each propositions as p (p.id)}
    <article>
      <header>
        <strong>{NATURE[p.nature] ?? p.nature}</strong>
        {#if p.entity_id}
          · <a href="/atelier/entite/{p.entity_id}">{p.fiche ?? `fiche ${p.entity_id}`}</a>
        {:else}
          · {OBJET[p.object_type] ?? p.object_type} n° {p.object_id}
        {/if}
        <span class="muted">· proposé par {p.propose_par ?? '—'}, {heureLocale(p.propose_le)}</span>
      </header>

      {#if etat === 'en_attente' && p.actuel === null}
        <p class="avis">L'objet visé n'existe plus : cette proposition ne peut qu'être refusée.</p>
      {/if}

      {#if p.nature === 'marche'}
        <LigneExtraite {p} peutTrancher={peutTrancher && etat === 'en_attente'}
          enCours={enCours === p.id} corrigeables={corrigeables.marche || []}
          on:trancher={(e) => trancher(p, e.detail.accepter, e.detail.motif, e.detail.corrections)} />
      {:else}
      <table>
        <thead><tr><th>Champ</th><th>Valeur en place</th><th>{peutTrancher ? 'Valeur proposée' : 'Votre proposition'}</th></tr></thead>
        <tbody>
          {#each Object.keys(p.charge) as c}
            <tr>
              <td>{libelle(c)}</td>
              <td class="avant">
                {dire(p.avant[c])}
                {#if aBouge(p, c)}
                  <div class="bouge">⚠ vaut maintenant « {dire(p.actuel[c])} » — modifié depuis</div>
                {/if}
              </td>
              <td class="apres">{dire(p.charge[c])}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      {/if}

      {#if etat !== 'en_attente'}
        <p class="muted">
          {ETATS.find(e => e[0] === p.etat)?.[1] ?? p.etat}
          {#if p.tranche_par}par {p.tranche_par}{/if}
          {#if p.tranche_le}, {heureLocale(p.tranche_le)}{/if}
          {#if p.motif} — « {p.motif} »{/if}
        </p>
      {:else if p.nature === 'marche'}
        <!-- Les gestes d'une ligne extraite vivent dans LigneExtraite. -->
      {:else if peutTrancher}
        <div class="gestes">
          <button class="oui" disabled={enCours === p.id || p.actuel === null}
                  on:click={() => trancher(p, true)}>Accepter — la valeur est écrite</button>
          <input placeholder="Motif du refus (obligatoire pour refuser)" bind:value={motifs[p.id]} />
          <button class="non" disabled={enCours === p.id}
                  on:click={() => trancher(p, false)}>Refuser</button>
        </div>
      {:else}
        <div class="gestes">
          <button class="non" disabled={enCours === p.id} on:click={() => retirer(p)}>
            Retirer ma proposition
          </button>
        </div>
      {/if}
    </article>
  {/each}

  {#if !propositions.length && !chargement}
    <p class="muted vide">Aucune proposition {etat === 'en_attente' ? 'en attente' : 'dans cet état'}.</p>
  {/if}
</div>

<style>
  .page { padding: 1.2rem; display: flex; flex-direction: column; gap: .8rem; font-size: .9rem; max-width: 60rem; }
  h1 { font-size: 1.2rem; color: var(--texte); }
  .intro { color: var(--texte-2); }
  .filtres { display: flex; gap: .4rem; flex-wrap: wrap; }
  .filtres button { border: 1px solid var(--bordure-forte); border-radius: 6px; padding: .35rem .7rem; color: var(--texte-2); }
  .filtres button.actif { background: var(--accent-fort); border-color: var(--accent-fort); color: var(--sur-accent); }
  article { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px; padding: .8rem; display: flex; flex-direction: column; gap: .6rem; }
  header { color: var(--texte); }
  header a { color: var(--info); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--texte-doux); font-weight: 500; font-size: .8rem; padding: .35rem .5rem; border-bottom: 1px solid var(--bordure); }
  td { padding: .4rem .5rem; border-bottom: 1px solid var(--bordure-douce); color: var(--texte); vertical-align: top; overflow-wrap: anywhere; }
  .avant { color: var(--danger-texte); }
  .apres { color: var(--succes); }
  .bouge { color: var(--alerte-texte); font-size: .82rem; margin-top: .2rem; }
  .gestes { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .gestes input { flex: 1; min-width: 14rem; background: var(--fond); border: 1px solid var(--bordure); color: var(--texte); border-radius: 5px; padding: .4rem .5rem; }
  .gestes button { border-radius: 6px; padding: .45rem .8rem; border: 1px solid var(--bordure-forte); color: var(--texte); }
  .gestes button.oui { background: var(--succes-bordure); border-color: var(--succes-bordure); }
  .gestes button.non { background: transparent; }
  .gestes button:disabled { opacity: .5; }
  .muted { color: var(--texte-doux); }
  .vide { padding: 1rem 0; }
  .depot { background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px; padding: .6rem .8rem; }
  .depot summary { cursor: pointer; color: var(--texte); }
  .refus { color: var(--danger-texte); font-size: .85rem; max-height: 12rem; overflow: auto; }
  .avis { background: var(--alerte-doux); border: 1px solid var(--alerte-bordure); border-radius: 6px; color: var(--alerte-texte); padding: .5rem .75rem; }
</style>
