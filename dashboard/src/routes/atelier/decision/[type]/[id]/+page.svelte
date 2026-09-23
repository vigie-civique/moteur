<script>
  // L'écran d'une décision — lot C, 23/09/2026.
  //
  // Trois zones, et rien d'autre :
  //   1. la QUESTION, en français, et ce que la ligne affirme ;
  //   2. les PREUVES — l'acte, sa date, SON TEXTE, d'où la ligne vient ;
  //   3. le GESTE, nommé, avec sa conséquence dite AVANT le clic.
  //
  // Ce qu'on remplace : un tableau de lignes et des ✓ ✗ sans libellé, sans
  // confirmation, sans retour en arrière. On tranchait sans voir sur quoi.
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { goto } from '$app/navigation'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'
  import { ORIGINES, ORIGINE_AIDE, VERDICT } from '$lib/axes.js'

  $: type = $page.params.type
  $: id   = $page.params.id
  $: tranche = auMoins($currentUser, 'validator')

  let d        = null
  let loading  = true
  let error    = ''
  let avis     = ''
  let choisi   = null    // le geste en cours de confirmation
  let precision = ''
  let envoi    = false
  let texteOuvert = false

  // Recharger quand l'URL change : « Suivant » navigue sans remonter la page.
  $: if (type && id) charger(type, id)

  async function charger(t, i) {
    loading = true; error = ''; choisi = null; precision = ''; texteOuvert = false
    try {
      const res = await authFetch(`/atelier/decision/${t}/${i}`)
      if (!res.ok) throw new Error(`${res.status}`)
      d = await res.json()
    } catch (e) { error = e.message; d = null }
    finally { loading = false }
  }

  async function poser() {
    envoi = true; avis = ''
    try {
      const res = await authFetch(`/atelier/decision/${type}/${id}`, {
        method: 'POST',
        body: JSON.stringify({ geste: choisi.cle, precision }),
      })
      const corps = await res.json().catch(() => ({}))
      if (!res.ok) {
        const det = corps.detail
        avis = (typeof det === 'object' ? det?.message : det)
             || `L'enregistrement a échoué (${res.status}).`
        return
      }
      // Dire ce qui vient de se passer, puis enchaîner — ou s'arrêter en le
      // disant. Une file qui se termine sans un mot ressemble à une panne.
      // `suivant` porte SON type : la file « Chiffres à confirmer » enchaîne
      // les flux puis les marchés, et s'arrêter au changement de type ferait
      // croire la file finie alors qu'il reste des lignes.
      const suite = d.suivant
      avis = `« ${d.revendication} » — ${choisi.libelle.toLowerCase()}. ${corps.effet}`
      if (suite) goto(`/atelier/decision/${suite.objet}/${suite.id}`)
      else { await charger(type, id); avis += " C'était la dernière de cette file." }
    } finally { envoi = false }
  }

  // Le passage du texte de l'acte où le montant apparaît. Une preuve de
  // 1 985 caractères qu'il faut lire en entier n'est pas une preuve utilisable :
  // on montre les alentours du chiffre, et le texte complet reste dépliable.
  function passage(texte, objet) {
    if (!texte) return null
    const montant = objet?.amount ?? objet?.montant
    // Un montant absent OU NUL n'a rien à surligner : chercher « 0 » dans un
    // procès-verbal accroche le premier zéro venu — sur la ligne 394 de
    // Lasalle, c'était celui de « L2131-1 ». Un surlignage faux est pire qu'un
    // surlignage absent : il donne l'air d'une preuve.
    if (!montant) return null
    // Le même nombre s'écrit « 13456 », « 13 456 », « 13.456,00 » : on cherche
    // ses chiffres à la suite, séparateurs admis entre eux.
    const chiffres = String(Math.round(Math.abs(montant)))
    const motif = new RegExp(chiffres.split('').join('[\\s.,  ]*'))
    const m = texte.match(motif)
    if (!m) return null
    const debut = Math.max(0, m.index - 220)
    const fin   = Math.min(texte.length, m.index + m[0].length + 220)
    return {
      avant: (debut > 0 ? '…' : '') + texte.slice(debut, m.index),
      trouve: m[0],
      apres: texte.slice(m.index + m[0].length, fin) + (fin < texte.length ? '…' : ''),
    }
  }

  $: extrait = d ? passage(d.acte?.content, d.objet) : null
</script>

<svelte:head><title>Décider — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <a class="retour" href="/atelier">← Aujourd'hui</a>

  {#if loading}
    <p class="msg">Chargement…</p>
  {:else if error}
    <p class="msg erreur">Cette ligne n'a pas pu être ouverte ({error}).</p>
  {:else if d}

    <!-- ZONE 1 — la question, et ce que la ligne affirme -->
    <section class="question">
      <h1>{d.question}</h1>
      <p class="revendication">{d.revendication}</p>
      {#if d.reste}
        <p class="reste">{d.reste} ligne{d.reste > 1 ? 's' : ''} de cette file
          attend{d.reste > 1 ? 'ent' : ''} encore un regard.</p>
      {/if}
    </section>

    {#if avis}<p class="avis" role="status">{avis}</p>{/if}

    {#if d.decision.verdict !== 'jamais_relu'}
      <p class="deja">
        Déjà tranchée : <strong>{VERDICT[d.decision.verdict]?.libelle ?? d.decision.verdict}</strong>
        {#if d.decision.par}par {d.decision.par}{/if}
        {#if d.decision.le}, le {heureLocale(d.decision.le)}{/if}.
        {#if d.decision.note}<br><span class="note">« {d.decision.note} »</span>{/if}
      </p>
    {/if}

    <!-- ZONE 2 — les preuves -->
    <section class="preuves">
      <h2>Sur quoi on se fonde</h2>

      <dl>
        <dt>D'où vient cette ligne</dt>
        <dd>
          {ORIGINES[d.objet.origine] ?? "Origine non établie"}
          {#if ORIGINE_AIDE[d.objet.origine]}
            <span class="aide">{ORIGINE_AIDE[d.objet.origine]}</span>
          {:else}
            <span class="aide">Aucune preuve d'origine en base : c'est peut-être
              le vrai défaut de cette ligne.</span>
          {/if}
        </dd>

        {#if d.objet.saisi_par}
          <dt>Saisie par</dt>
          <dd>{d.objet.saisi_par}{#if d.objet.saisi_le}, le {heureLocale(d.objet.saisi_le)}{/if}</dd>
        {/if}

        {#if d.acte}
          <dt>L'acte qui la porte</dt>
          <dd>
            {d.acte.title || 'Acte sans titre'}
            {#if d.acte.date}<span class="aide">séance du {d.acte.date}</span>{/if}
          </dd>
        {:else}
          <dt>L'acte qui la porte</dt>
          <dd class="manque">
            Aucun acte rattaché. Rien ici ne permet de vérifier le chiffre —
            c'est en soi une raison de demander une autre preuve.
          </dd>
        {/if}

        {#if d.objet.source_url || d.acte?.source_url}
          <dt>La source</dt>
          <dd><a href={d.objet.source_url || d.acte.source_url}
                 target="_blank" rel="noopener noreferrer">Ouvrir le document d'origine</a></dd>
        {/if}
      </dl>

      {#if extrait}
        <figure class="extrait">
          <figcaption>Le passage où ce chiffre apparaît, dans le texte de l'acte</figcaption>
          <p>{extrait.avant}<mark>{extrait.trouve}</mark>{extrait.apres}</p>
        </figure>
      {:else if d.acte?.content && !(d.objet.amount ?? d.objet.montant)}
        <p class="alerte">
          Cette ligne ne porte AUCUN montant. Le texte de l'acte est là, sous
          « Lire le texte complet » : s'il en donne un, c'est la lecture
          automatique qui a échoué, et la ligne est à écarter ou à corriger.
        </p>
      {:else if d.acte?.content}
        <p class="alerte">
          Le chiffre de cette ligne ne se retrouve PAS tel quel dans le texte de
          l'acte. Cela n'en fait pas une erreur — il peut être calculé, ou écrit
          autrement — mais il n'est pas prouvé par ce texte.
        </p>
      {/if}

      {#if d.acte?.content}
        <button class="deplier" on:click={() => texteOuvert = !texteOuvert}>
          {texteOuvert ? 'Replier' : 'Lire'} le texte complet de l'acte
          ({d.acte.content.length} caractères)
        </button>
        {#if texteOuvert}<pre class="texte">{d.acte.content}</pre>{/if}
      {/if}
    </section>

    <!-- ZONE 3 — le geste, et sa conséquence -->
    <section class="gestes">
      <h2>Ce que vous décidez</h2>

      {#if !tranche}
        <p class="msg">
          Trancher demande le rôle validateur. Vous pouvez lire cette ligne et
          ses preuves, et signaler un problème à un validateur.
        </p>
      {:else if choisi}
        <div class="confirmation">
          <p class="choisi">{choisi.libelle}</p>
          <p class="effet">{choisi.effet}</p>
          {#if choisi.demande_un_mot}
            <label for="precision">En un mot, ce qui ne va pas</label>
            <textarea id="precision" bind:value={precision} rows="3"
                      placeholder="Le montant est celui du HT, l'acte vote le TTC."></textarea>
          {/if}
          <div class="boutons">
            <button class="valider" disabled={envoi} on:click={poser}>
              {envoi ? 'Enregistrement…' : 'Confirmer'}
            </button>
            <button class="annuler" disabled={envoi}
                    on:click={() => { choisi = null; precision = '' }}>
              Revenir en arrière
            </button>
          </div>
        </div>
      {:else}
        <ul class="catalogue">
          {#each d.gestes as g (g.cle)}
            <li>
              <button class="geste" class:retire={g.verdict === 'ecarte'}
                      on:click={() => { choisi = g; precision = '' }}>
                {g.libelle}
              </button>
              <p class="effet">{g.effet}</p>
            </li>
          {/each}
        </ul>
        <p class="rien">
          Rien ne vous oblige à trancher : une ligne jamais relue continue
          d'exister comme avant.
          {#if d.suivant}
            <a href="/atelier/decision/{d.suivant.objet}/{d.suivant.id}">Passer à la suivante →</a>
          {/if}
        </p>
      {/if}
    </section>

  {/if}
</div>

<style>
  .page {
    padding: 1.2rem 1.4rem 3rem;
    max-width: 54rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }
  .retour { font-size: .85rem; color: #93c5fd; text-decoration: none; }

  .msg { font-size: .92rem; line-height: 1.5; color: #94a3b8; }
  .msg.erreur { color: #fca5a5; }

  h1 { font-size: 1.5rem; line-height: 1.3; font-weight: 700; color: #f1f5f9; margin: .3rem 0 0; }
  .revendication {
    font-size: 1.15rem; line-height: 1.45; color: #e2e8f0; margin: .6rem 0 0;
    padding: .7rem .9rem; background: #111a2b; border-radius: .4rem;
    border-left: 3px solid #3b82f6;
  }
  .reste { font-size: .85rem; color: #94a3b8; margin: .5rem 0 0; }

  .avis {
    font-size: .9rem; line-height: 1.5; color: #bbf7d0; background: #14291d;
    border-radius: .3rem; padding: .55rem .75rem; margin: 0;
  }
  .deja {
    font-size: .9rem; line-height: 1.5; color: #fcd34d; background: #2a2412;
    border-radius: .3rem; padding: .55rem .75rem; margin: 0;
  }
  .deja strong { color: #fde68a; }
  .note { color: #cbd5e1; font-style: italic; }

  h2 {
    font-size: .8rem; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: #94a3b8; margin: 0 0 .6rem;
  }
  section.preuves, section.gestes {
    padding: 1rem 1.1rem; border: 1px solid #334155;
    border-radius: .5rem; background: #0f1626;
  }

  dl { display: grid; grid-template-columns: max-content 1fr; gap: .4rem .9rem; margin: 0; }
  dt { font-size: .85rem; color: #94a3b8; }
  dd { font-size: .95rem; color: #e2e8f0; margin: 0; }
  dd.manque { color: #fca5a5; line-height: 1.45; }
  .aide { display: block; font-size: .82rem; color: #94a3b8; line-height: 1.4; }
  dd a { color: #93c5fd; }

  .extrait {
    margin: .9rem 0 0; padding: .75rem .9rem;
    background: #0b1220; border-radius: .4rem; border: 1px solid #1e293b;
  }
  .extrait figcaption { font-size: .8rem; color: #94a3b8; margin-bottom: .45rem; }
  .extrait p { font-size: .95rem; line-height: 1.6; color: #cbd5e1; margin: 0; }
  mark { background: #3b82f6; color: #fff; padding: 0 .15rem; border-radius: .15rem; }

  .alerte {
    margin: .9rem 0 0; font-size: .88rem; line-height: 1.5; color: #fcd34d;
    background: #2a2412; border-radius: .35rem; padding: .55rem .75rem;
  }

  .deplier {
    margin-top: .8rem; background: transparent; border: 1px solid #334155;
    color: #93c5fd; border-radius: .3rem; padding: .35rem .7rem;
    font-size: .85rem; cursor: pointer;
  }
  .texte {
    margin-top: .6rem; padding: .75rem .9rem; background: #0b1220;
    border-radius: .4rem; font-size: .88rem; line-height: 1.6; color: #cbd5e1;
    white-space: pre-wrap; max-height: 26rem; overflow: auto;
  }

  .catalogue { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .7rem; }
  .catalogue li { display: flex; flex-direction: column; gap: .2rem; }
  .geste {
    align-self: flex-start; text-align: left;
    padding: .5rem .9rem; border-radius: .3rem;
    background: #1e293b; color: #f1f5f9; border: 1px solid #334155;
    font-size: .98rem; font-weight: 600; cursor: pointer;
  }
  .geste:hover { background: #26344a; }
  /* Ce qui RETIRE du site se distingue de ce qui n'y touche pas. */
  .geste.retire { border-color: #7f1d1d; color: #fecaca; }
  .geste.retire:hover { background: #2a1414; }
  .effet { font-size: .85rem; line-height: 1.45; color: #94a3b8; margin: 0; }

  .rien { font-size: .85rem; color: #94a3b8; margin: .9rem 0 0; }
  .rien a { color: #93c5fd; }

  .confirmation { display: flex; flex-direction: column; gap: .5rem; }
  .choisi { font-size: 1.05rem; font-weight: 600; color: #f1f5f9; margin: 0; }
  label { font-size: .85rem; color: #94a3b8; }
  textarea {
    width: 100%; background: #0b1220; border: 1px solid #334155;
    border-radius: .3rem; color: #e2e8f0; padding: .5rem .6rem;
    font-size: .95rem; font-family: inherit; line-height: 1.5;
  }
  .boutons { display: flex; gap: .5rem; margin-top: .3rem; }
  .valider {
    padding: .5rem 1rem; border-radius: .3rem; border: none;
    background: #3b82f6; color: #fff; font-size: .95rem; font-weight: 600;
    cursor: pointer;
  }
  .valider:disabled { opacity: .6; cursor: default; }
  .annuler {
    padding: .5rem 1rem; border-radius: .3rem; border: 1px solid #334155;
    background: transparent; color: #cbd5e1; font-size: .95rem; cursor: pointer;
  }

  @media (max-width: 640px) {
    .page { padding: 1rem .9rem 3rem; }
    dl { grid-template-columns: 1fr; gap: .1rem .9rem; }
    dt { margin-top: .5rem; }
  }
</style>
