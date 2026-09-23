<script>
  // La file des liens présumés — écrite le 23/09/2026.
  //
  // `/api/candidates` et `/api/candidates/{id}/review` existaient depuis des
  // mois ; le seul écran qui les lisait (`ReviewPanel.svelte`) n'était monté
  // nulle part. 87 liens attendaient à Lasalle sans qu'aucune page de l'atelier
  // n'y mène. C'est la file « déjà écrite et jamais rassemblée » du lot B.
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'

  $: tranche = auMoins($currentUser, 'validator')
  $: me = $currentUser?.email || ''

  let liens   = []
  let loading = true
  let error   = ''
  let avis    = ''
  let occupe  = {}

  // Ce que le détecteur a remarqué, dit en français. Un `signal` inconnu se
  // montre tel quel plutôt que d'être tu : une file qui masque ce qu'elle ne
  // sait pas nommer demande de trancher à l'aveugle.
  const SIGNAUX = {
    commission_pv:        "Le procès-verbal d'une séance nomme cette personne dans cette commission.",
    maiden_name:          "Même nom de naissance.",
    same_full_name:       "Deux fiches portent exactement le même nom.",
    same_surname:         "Même patronyme.",
    same_address:         "Les deux fiches déclarent la même adresse.",
    toponym:              "Le nom reprend un lieu-dit du territoire.",
    entity_duplicate:     "Ces deux fiches décrivent peut-être la même entité.",
    subsidy_entity_match: "Le bénéficiaire d'une subvention porte ce nom.",
  }

  // Ce que « Oui » change VRAIMENT, selon le type de lien. L'API le calcule
  // depuis les règles de publication de l'instance (`sort_du_type`) : depuis
  // que `detect_links` est câblé, la file mêle des sièges de commission, qui
  // se publient, et des doublons ou des lieux-dits partagés, qui ne sortent
  // jamais du site. Une phrase unique aurait menti sur les trois quarts.
  const EFFET = {
    public: "Il devient une relation publiée, et peut rendre une personne "
          + "publiable au titre de ce lien.",
    selon_pertinence: "Il devient une relation ; elle ne sera publiée que si "
          + "elle touche un acteur public ou de l'argent public.",
    prive: "Il est enregistré pour le travail de l'atelier, et ne sera PAS "
          + "publié : ce type de lien ne sort jamais du site.",
  }

  onMount(() => charger())

  async function charger() {
    loading = true; error = ''
    try {
      const res = await authFetch('/candidates?status=pending')
      if (!res.ok) throw new Error(`${res.status}`)
      liens = await res.json()
    } catch (e) { error = e.message }
    finally { loading = false }
  }

  async function motif(res, defaut) {
    const d = (await res.json().catch(() => ({}))).detail
    return (typeof d === 'object' ? d?.message : d) || defaut
  }

  async function trancher(lien, action, libelle, effet) {
    occupe = { ...occupe, [lien.id]: true }
    avis = ''
    try {
      const res = await authFetch(`/candidates/${lien.id}/review`, {
        method: 'POST', body: JSON.stringify({ action, note: '' }),
      })
      if (res.ok) {
        liens = liens.filter(l => l.id !== lien.id)
        avis = `« ${lien.from_name} → ${lien.to_name} » : ${libelle}. ${effet}`
      } else {
        avis = await motif(res, `L'enregistrement a échoué (${res.status}).`)
        if (res.status === 409) await charger()
      }
    } finally {
      const o = { ...occupe }; delete o[lien.id]; occupe = o
    }
  }

  async function reserver(lien) {
    avis = ''
    const res = await authFetch(`/atelier/queue/${lien.id}/claim`, {
      method: 'POST', body: JSON.stringify({ table: 'relation_candidates' }),
    })
    if (res.ok) {
      const r = await res.json()
      liens = liens.map(l => l.id === lien.id
        ? { ...l, reservation: { par: r.locked_by, expire_dans_min: r.expires_in_min } } : l)
    } else {
      avis = await motif(res, `Réservation impossible (${res.status}).`)
      if (res.status === 409) await charger()
    }
  }

  async function liberer(lien) {
    avis = ''
    const res = await authFetch(
      `/atelier/queue/${lien.id}/claim?table=relation_candidates`, { method: 'DELETE' })
    if (res.ok) liens = liens.map(l => l.id === lien.id ? { ...l, reservation: null } : l)
    else avis = await motif(res, `Libération impossible (${res.status}).`)
  }
</script>

<svelte:head><title>Liens présumés — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <header>
    <div>
      <a class="retour" href="/atelier">← Aujourd'hui</a>
      <h1>Ces deux-là sont-ils vraiment liés ?</h1>
      <p class="intro">
        Un détecteur a remarqué quelque chose : un nom dans un procès-verbal,
        deux fiches qui se ressemblent, un homonyme. Il ne tranche rien —
        <strong>aucun de ces liens n'existe</strong> tant que personne ne l'a
        confirmé, et beaucoup ne sortiront jamais sur le site même confirmés.
        Chaque ligne dit ce que « Oui » changerait.
      </p>
    </div>
    {#if !loading && !error}
      <p class="compte"><strong>{liens.length}</strong> en attente</p>
    {/if}
  </header>

  {#if avis}<p class="avis" role="status">{avis}</p>{/if}
  {#if $currentUser && !tranche}
    <p class="msg">
      Vous pouvez lire cette file. Confirmer ou écarter un lien demande le rôle
      validateur.
    </p>
  {/if}

  {#if loading}
    <p class="msg">Chargement…</p>
  {:else if error}
    <p class="msg erreur">Erreur : {error}</p>
  {:else if liens.length === 0}
    <p class="msg">
      Rien n'attend ici. Un zéro sur cette file ne veut pas dire que tout a été
      relu : il veut dire que les détecteurs n'ont rien trouvé de neuf depuis
      leur dernier passage — « Aujourd'hui » en donne la date.
    </p>
  {:else}
    <ul class="liens">
      {#each liens as l (l.id)}
        <li class="lien">
          <p class="paire">
            <a href="/atelier/entite/{l.from_id}">{l.from_name}</a>
            <span class="type">{l.relation_type.replace(/_/g, ' ')}</span>
            <a href="/atelier/entite/{l.to_id}">{l.to_name}</a>
          </p>

          <p class="indice">
            {SIGNAUX[l.signal] ?? `Signal « ${l.signal} ».`}
            {#if l.signal_detail}<span class="detail">{l.signal_detail}</span>{/if}
          </p>

          <!-- La conséquence AVANT le geste, pas seulement après : c'est la
               règle du chantier, et ici elle change d'un lien à l'autre. -->
          <p class="consequence" class:jamais={l.sort_si_accepte === 'prive'}>
            {EFFET[l.sort_si_accepte] ?? EFFET.prive}
          </p>

          {#if l.reservation}
            <p class="reservation" class:mienne={l.reservation.par === me}>
              {#if l.reservation.par === me}
                Vous l'avez réservé
              {:else}
                Réservé par {l.reservation.par}
              {/if}
              {#if l.reservation.expire_dans_min}
                — {Math.round(l.reservation.expire_dans_min)} min restantes
              {/if}
              {#if l.reservation.par === me || $currentUser?.role === 'admin'}
                <button class="lien-nu" on:click={() => liberer(l)}>libérer</button>
              {/if}
            </p>
          {/if}

          {#if tranche}
            <div class="gestes">
              <button class="oui" disabled={occupe[l.id]}
                      on:click={() => trancher(l, 'accept', 'lien confirmé',
                        EFFET[l.sort_si_accepte] ?? EFFET.prive)}>
                Oui, le lien existe
              </button>
              <button class="non" disabled={occupe[l.id]}
                      on:click={() => trancher(l, 'reject', 'lien écarté',
                        'Il ne sera pas créé, et ne sera plus proposé.')}>
                Non, ce lien est faux
              </button>
              <button class="doute" disabled={occupe[l.id]}
                      on:click={() => trancher(l, 'ignore', 'laissé de côté',
                        "Il sort de la file sans être créé : à reprendre avec une preuve.")}>
                Je ne sais pas
              </button>
              {#if !l.reservation}
                <button class="lien-nu" on:click={() => reserver(l)}>
                  je m'en occupe
                </button>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .page {
    padding: 1.2rem 1.4rem 2rem;
    max-width: 62rem;
    display: flex;
    flex-direction: column;
    gap: .9rem;
  }
  header {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 1rem; flex-wrap: wrap;
  }
  .retour { font-size: .85rem; color: #93c5fd; text-decoration: none; }
  h1 { font-size: 1.35rem; font-weight: 700; color: #f1f5f9; margin: .3rem 0 0; }
  .intro { font-size: .92rem; line-height: 1.5; color: #94a3b8; margin: .4rem 0 0; max-width: 44rem; }
  .intro strong { color: #cbd5e1; }
  .compte { font-size: .9rem; color: #94a3b8; margin: 0; }
  .compte strong { font-size: 1.5rem; color: #f1f5f9; }

  .msg { font-size: .92rem; line-height: 1.5; color: #94a3b8; }
  .msg.erreur { color: #fca5a5; }
  .avis {
    font-size: .9rem; color: #bbf7d0; background: #14291d;
    border-radius: .3rem; padding: .5rem .7rem; margin: 0;
  }

  .liens { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .6rem; }
  .lien {
    padding: .85rem 1rem;
    border: 1px solid #334155;
    border-radius: .45rem;
    background: #111a2b;
    display: flex; flex-direction: column; gap: .4rem;
  }
  .paire { font-size: 1.05rem; color: #f1f5f9; margin: 0; }
  .paire a { color: #f1f5f9; text-decoration: none; border-bottom: 1px solid #475569; }
  .paire a:hover { border-color: #93c5fd; }
  .type {
    font-size: .78rem; text-transform: uppercase; letter-spacing: .05em;
    color: #94a3b8; margin: 0 .5rem;
  }
  .indice { font-size: .9rem; line-height: 1.45; color: #94a3b8; margin: 0; }
  .detail { color: #64748b; }

  .consequence {
    font-size: .85rem; line-height: 1.45; color: #cbd5e1; margin: 0;
    border-left: 2px solid #3b82f6; padding-left: .55rem;
  }
  /* Un lien qui ne sortira jamais se distingue d'un lien publiable : c'est la
     seule chose que le bénévole doit savoir avant de cliquer. */
  .consequence.jamais { color: #94a3b8; border-left-color: #475569; }

  .reservation {
    font-size: .85rem; color: #fcd34d; background: #2a2412;
    border-radius: .3rem; padding: .3rem .5rem; margin: 0; align-self: flex-start;
  }
  .reservation.mienne { color: #bbf7d0; background: #14291d; }

  .gestes { display: flex; gap: .45rem; flex-wrap: wrap; margin-top: .2rem; }
  .gestes button {
    padding: .42rem .8rem; border-radius: .3rem; font-size: .9rem;
    font-weight: 600; border: 1px solid transparent; cursor: pointer;
  }
  .gestes button:disabled { opacity: .5; cursor: default; }
  .oui   { background: #166534; color: #dcfce7; }
  .non   { background: #7f1d1d; color: #fee2e2; }
  .doute { background: transparent; color: #cbd5e1; border-color: #334155; }
  .lien-nu {
    background: transparent; color: #93c5fd; border: none;
    font-size: .85rem; cursor: pointer; text-decoration: underline;
    padding: .42rem .3rem;
  }

  @media (max-width: 640px) {
    .page { padding: 1rem .9rem 2rem; }
  }
</style>
