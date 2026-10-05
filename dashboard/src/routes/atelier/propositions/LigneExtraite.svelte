<script>
  // Un marché LU dans un procès-verbal par un outil d'extraction, et qui
  // n'est encore nulle part en base (cf. collectors/marches_extraits.py).
  // Le validateur le juge l'acte sous les yeux : le texte de l'acte, le passage
  // que l'outil cite comme preuve, et ce qu'il en a tiré — qu'il peut corriger
  // avant d'accepter. Rien n'est publié avant ce geste.
  import { createEventDispatcher } from 'svelte'
  import { lienSur } from '$lib/liens.js'

  export let p
  export let peutTrancher = false
  export let enCours = false
  export let corrigeables = []

  const dispatch = createEventDispatcher()

  const LIBELLES = {
    objet: 'Objet', acheteur_nom: 'Acheteur', acheteur_siren: "SIREN de l'acheteur",
    titulaire: 'Titulaire', montant: 'Montant (€)', devise_base: 'HT ou TTC',
    procedure: 'Procédure', nature: 'Nature',
  }
  const PORTEE = {
    commune: 'la commune', intercommunalite: "l'intercommunalité",
    autre: 'un autre acheteur', non_etabli: 'acheteur non établi',
  }

  $: c = p.charge
  $: acte = p.acte
  // Ce que le validateur a sous les yeux et peut changer : la valeur lue, au
  // départ. Seul ce qui DIFFÈRE de la lecture part en correction.
  let valeurs = {}
  $: if (p && !Object.keys(valeurs).length) {
    valeurs = Object.fromEntries(corrigeables.map((k) => [k, c[k] ?? '']))
  }
  $: corrections = Object.fromEntries(
    corrigeables.filter((k) => String(valeurs[k] ?? '') !== String(c[k] ?? ''))
      .map((k) => [k, valeurs[k] === '' ? null : valeurs[k]]))
  $: corrige = Object.keys(corrections).length > 0

  let motif = ''

  // Le passage cité et son contexte, découpés par l'API comme
  // `citation_presente` les a reconnus (ponctuation et accents compris). Le
  // navigateur cherchait lui-même, plus strictement : le surlignage échouait là
  // où le contrôle avait réussi.
  $: extrait = acte?.extrait
  $: doublons = p.doublons || []
</script>

<div class="ligne">
  {#if acte}
    <p class="acte">
      Lu dans <a href="/atelier/decision/deliberation/{acte.id}">{acte.title || 'acte sans titre'}</a>
      du {acte.date?.slice(0, 10)}
      {#if lienSur(acte.source_url)}· <a href={lienSur(acte.source_url)} target="_blank" rel="noopener">pièce source ↗</a>{/if}
    </p>
  {/if}

  <blockquote>
    {#if extrait}
      {extrait.avant}<mark>{extrait.cite}</mark>{extrait.apres}
    {:else}
      <mark>{c.citation}</mark>
    {/if}
  </blockquote>
  {#if c.trouvee_dans === 'seance'}
    <p class="signal">Le passage se lit dans un autre acte de la même pièce, pas dans celui-ci.</p>
  {/if}
  {#if !c.montant_dans_citation}
    <p class="signal">Le montant lu ne figure pas dans le passage cité : le vérifier dans l'acte.</p>
  {/if}
  {#if c.portee === 'commune' && c.assemblee_de_l_acte === 'intercommunalite'}
    <p class="signal">L'acte est de l'intercommunalité, l'acheteur lu est la commune.</p>
  {:else if c.portee === 'intercommunalite' && c.assemblee_de_l_acte === 'commune'}
    <p class="signal">L'acte est municipal, l'acheteur lu est l'intercommunalité : un compte rendu, ou une erreur de lecture ?</p>
  {/if}

  {#if doublons.length}
    <div class="signal">
      Déjà en base pour le même acheteur et le même montant — un doublon, ou un autre marché ?
      <ul>
        {#each doublons as d}
          <li>{d.date_notif || 'sans date'} · {d.objet} · {d.source}{d.confidence === 'probable' ? ' (non publié)' : ''}</li>
        {/each}
      </ul>
    </div>
  {/if}

  <p class="muted">Acheteur : {PORTEE[c.portee] ?? c.portee}
    {#if c.acheteur_siren}— SIREN donné par l'outil, qui peut l'avoir déduit de l'assemblée
      plutôt que lu dans l'acte : la portée en découle, le vérifier{/if}
    {#if c.titre_acte && c.titre_acte !== acte?.title}· l'outil a lu le titre « {c.titre_acte} »{/if}</p>

  <div class="champs">
    {#each corrigeables as k}
      <label>
        <span>{LIBELLES[k] ?? k}</span>
        {#if peutTrancher}
          {#if k === 'devise_base'}
            <select bind:value={valeurs[k]}><option value="">—</option><option>HT</option><option>TTC</option></select>
          {:else}
            <input bind:value={valeurs[k]} class:modifie={String(valeurs[k] ?? '') !== String(c[k] ?? '')} />
          {/if}
        {:else}
          <b>{c[k] ?? '—'}</b>
        {/if}
      </label>
    {/each}
  </div>

  {#if peutTrancher}
    <div class="gestes">
      <button class="oui" disabled={enCours || p.actuel === null}
              on:click={() => dispatch('trancher', { accepter: true, motif, corrections })}>
        {corrige ? 'Corriger et accepter' : 'Accepter — le marché est publié au prochain passage'}
      </button>
      <input placeholder="Motif (obligatoire pour écarter)" bind:value={motif} />
      <button class="non" disabled={enCours}
              on:click={() => dispatch('trancher', { accepter: false, motif, corrections: {} })}>
        Écarter
      </button>
    </div>
  {/if}
</div>

<style>
  .ligne { display: flex; flex-direction: column; gap: .5rem; }
  .acte a { color: var(--info); }
  blockquote { margin: 0; padding: .6rem .8rem; background: var(--fond); border-left: 3px solid var(--bordure-forte);
               color: var(--texte-2); max-height: 14rem; overflow: auto; white-space: pre-wrap; font-size: .85rem; }
  mark { background: var(--alerte-doux); color: var(--texte); }
  .signal { color: var(--alerte-texte); font-size: .85rem; }
  .muted { color: var(--texte-doux); }
  .champs { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: .5rem; }
  .champs label { display: flex; flex-direction: column; gap: .2rem; font-size: .8rem; color: var(--texte-doux); }
  .champs input, .champs select { background: var(--fond); border: 1px solid var(--bordure); color: var(--texte);
                                  border-radius: 5px; padding: .35rem .5rem; font-size: .9rem; }
  .champs input.modifie { border-color: var(--alerte-bordure); }
  .gestes { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .gestes input { flex: 1; min-width: 14rem; background: var(--fond); border: 1px solid var(--bordure); color: var(--texte); border-radius: 5px; padding: .4rem .5rem; }
  .gestes button { border-radius: 6px; padding: .45rem .8rem; border: 1px solid var(--bordure-forte); color: var(--texte); }
  .gestes button.oui { background: var(--succes-bordure); border-color: var(--succes-bordure); }
  .gestes button.non { background: transparent; }
  .gestes button:disabled { opacity: .5; }
</style>
