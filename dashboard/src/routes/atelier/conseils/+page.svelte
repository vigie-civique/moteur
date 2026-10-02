<script>
  // La file « Conseils en clair » — écrite le 30/09/2026.
  //
  // Une feuille « en clair » (avant / après / documents) est un texte rédigé
  // sur une séance, pas un fait collecté : elle ne sort sur le site que RETENUE
  // par un validateur (`collectors/verdict.py`, OBJETS_A_RETENIR), et seulement
  // si le vérificateur ne lui trouve aucune faute. Cette page est le seul endroit
  // où ce verdict se pose.
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'

  $: tranche = auMoins($currentUser, 'validator')

  let seances = []
  let loading = true
  let error   = ''
  let avis    = ''
  let feuilles = null     // { titre, html } : l'aperçu ouvert
  let occupe  = {}
  let notes   = {}

  const LIBELLE = { jamais_relu: 'Jamais relu', retenu: 'Retenu — publié', a_revoir: 'À revoir', ecarte: 'Écarté' }

  onMount(() => charger())

  async function charger() {
    loading = true; error = ''
    try {
      const res = await authFetch('/atelier/en-clair')
      if (!res.ok) throw new Error(`${res.status}`)
      seances = await res.json()
      notes = Object.fromEntries(seances.map(s => [s.releve, s.note || '']))
    } catch (e) { error = e.message }
    finally { loading = false }
  }

  // L'aperçu exige la session : on le charge avec le jeton, puis on l'ouvre.
  async function apercu(s) {
    const res = await authFetch(`/atelier/en-clair/${s.releve}/apercu`)
    if (!res.ok) { avis = `Aperçu impossible (${res.status}).`; return }
    // Dans un cadre SANS droits (`sandbox`), et non plus dans un onglet : un
    // `blob:` ouvert depuis l'atelier s'exécute à son adresse, donc avec sa
    // session. Les feuilles n'ont besoin d'aucun script pour se lire.
    feuilles = { titre: `${s.assemblee}, ${s.date}`, html: await res.text() }
  }

  async function motif(res, defaut) {
    const d = (await res.json().catch(() => ({}))).detail
    return (typeof d === 'object' ? d?.message : d) || defaut
  }

  async function decider(s, review_status) {
    if (!s.seance_id) { avis = "Aucune séance en base ne correspond à ce relevé."; return }
    occupe = { ...occupe, [s.releve]: true }; avis = ''
    try {
      const corps = { note: notes[s.releve] || '', lu_le: s.reviewed_at, empreinte_vue: s.empreinte }
      if (review_status) corps.review_status = review_status
      const res = await authFetch(`/atelier/annotations/en_clair/${s.seance_id}`, {
        method: 'PATCH', body: JSON.stringify(corps),
      })
      if (res.ok) {
        avis = `${s.assemblee}, ${s.date} : ${review_status ? LIBELLE[review_status].toLowerCase() : 'note enregistrée'}.`
          + (review_status === 'retenu' ? ' La feuille sortira à la prochaine publication.' : '')
        await charger()
      } else {
        avis = await motif(res, `L'enregistrement a échoué (${res.status}).`)
        if (res.status === 409) await charger()
      }
    } finally {
      const o = { ...occupe }; delete o[s.releve]; occupe = o
    }
  }
</script>

<svelte:head><title>Conseils en clair — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <header>
    <div>
      <a class="retour" href="/atelier">← Aujourd'hui</a>
      <h1>Ces feuilles peuvent-elles être publiées ?</h1>
      <p class="intro">
        Chaque séance tient en trois feuilles : ce qui était annoncé, ce qui a été
        décidé, et ce que les documents publics ont de faux. Elles ont été
        rédigées hors de l'atelier et vérifiées automatiquement contre les pièces.
        <strong>Rien n'est publié sans avoir été retenu ici.</strong>
      </p>
    </div>
    {#if !loading}
      <p class="compte"><strong>{seances.filter(s => s.verdict !== 'retenu' || s.modifie).length}</strong> à relire sur {seances.length}</p>
    {/if}
  </header>

  {#if avis}<p class="avis">{avis}</p>{/if}
  {#if loading}<p class="msg">Chargement…</p>
  {:else if error}<p class="msg erreur">La file n'a pas pu être chargée ({error}).</p>
  {:else if !seances.length}<p class="msg">Aucun relevé de séance dans <code>data/conseils/</code>.</p>
  {:else}
    <ul class="liens">
      {#each seances as s (s.releve)}
        <li class="lien" class:retenu={s.verdict === 'retenu' && !s.modifie} class:ecarte={s.verdict === 'ecarte'}>
          <p class="paire"><span class="tag" class:cc={s.code === 'cc'}>{s.code === 'cc' ? 'CC' : 'CM'}</span>
            {s.date} — {s.titre}</p>
          <p class="meta">
            {s.actes} acte{s.actes > 1 ? 's' : ''} relevé{s.actes > 1 ? 's' : ''} ·
            {s.erreurs_documents} erreur{s.erreurs_documents > 1 ? 's' : ''} dans les documents ·
            <span class="verdict">{LIBELLE[s.verdict]}</span>
            {#if s.reviewed_at} par {s.reviewed_by}, {heureLocale(s.reviewed_at)}{/if}
            {#if s.modifie}<span class="modifie">relevé modifié depuis la relecture — ne sort plus</span>{/if}
          </p>
          {#if s.fautes.length}
            <div class="fautes"><strong>Le vérificateur refuse ce relevé :</strong>
              <ul>{#each s.fautes.slice(0, 5) as f}<li>{f}</li>{/each}</ul></div>
          {:else}
            <p class="ok">Vérifié : chaque citation, montant et chiffre est retrouvé dans les pièces.</p>
          {/if}
          <textarea rows="2" placeholder="Note de relecture (ce qu'il faudrait corriger, ou pourquoi vous retenez)"
                    bind:value={notes[s.releve]}></textarea>
          <div class="actions">
            <button on:click={() => apercu(s)}>Voir les trois feuilles</button>
            {#if tranche}
              <button class="oui" disabled={occupe[s.releve] || s.fautes.length > 0}
                      title={s.fautes.length ? 'Un relevé en faute ne peut pas être retenu' : ''}
                      on:click={() => decider(s, 'retenu')}>Retenir</button>
              <button disabled={occupe[s.releve]} on:click={() => decider(s, 'a_revoir')}>À revoir</button>
              <button class="non" disabled={occupe[s.releve]} on:click={() => decider(s, 'ecarte')}>Écarter</button>
            {:else}
              <button disabled={occupe[s.releve]} on:click={() => decider(s, null)}>Enregistrer la note</button>
              <span class="aide">Retenir ou écarter demande le rôle de validateur.</span>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if feuilles}
  <div class="voile" role="dialog" aria-modal="true" aria-label="Aperçu des feuilles">
    <div class="feuilles">
      <header>
        <strong>{feuilles.titre}</strong>
        <button on:click={() => (feuilles = null)}>Fermer</button>
      </header>
      <iframe title="Les trois feuilles de la séance" sandbox="" srcdoc={feuilles.html}></iframe>
    </div>
  </div>
{/if}

<style>
  .page { padding: 1.2rem 1.4rem 2rem; max-width: 62rem; display: flex; flex-direction: column; gap: .9rem; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .retour { font-size: .85rem; color: #93c5fd; text-decoration: none; }
  h1 { font-size: 1.35rem; font-weight: 700; color: #f1f5f9; margin: .3rem 0 0; }
  .intro { font-size: .92rem; line-height: 1.5; color: #94a3b8; margin: .4rem 0 0; max-width: 44rem; }
  .intro strong { color: #cbd5e1; }
  .compte { font-size: .9rem; color: #94a3b8; margin: 0; }
  .compte strong { font-size: 1.5rem; color: #f1f5f9; }
  .msg { font-size: .92rem; line-height: 1.5; color: #94a3b8; }
  .msg.erreur { color: #fca5a5; }
  .avis { font-size: .9rem; color: #bbf7d0; background: #14291d; border-radius: .3rem; padding: .5rem .7rem; margin: 0; }
  .liens { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .6rem; }
  .lien { padding: .85rem 1rem; border: 1px solid #334155; border-radius: .45rem; background: #111a2b;
          display: flex; flex-direction: column; gap: .45rem; }
  .lien.retenu { border-color: #166534; }
  .lien.ecarte { opacity: .65; }
  .paire { font-size: 1.05rem; color: #f1f5f9; margin: 0; }
  .tag { font-size: .7rem; font-weight: 700; padding: .1rem .4rem; border-radius: .3rem; background: #1e3a5f; color: #bfdbfe; margin-right: .3rem; }
  .tag.cc { background: #3f2e12; color: #fde68a; }
  .meta { font-size: .85rem; color: #94a3b8; margin: 0; }
  .verdict { color: #e2e8f0; font-weight: 600; }
  .modifie { margin-left: .4rem; font-size: .78rem; color: #fde68a; background: #3f2e12; border-radius: .3rem; padding: .05rem .4rem; }
  .ok { font-size: .85rem; color: #86efac; margin: 0; }
  .fautes { font-size: .85rem; color: #fca5a5; }
  .fautes ul { margin: .2rem 0 0; padding-left: 1.1rem; }
  textarea { background: #0b1220; color: #e2e8f0; border: 1px solid #334155; border-radius: .3rem;
             padding: .4rem .5rem; font: inherit; font-size: .88rem; resize: vertical; }
  .actions { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  button { font: inherit; font-size: .88rem; padding: .35rem .8rem; border-radius: .3rem; border: 1px solid #475569;
           background: #1e293b; color: #e2e8f0; cursor: pointer; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  button.oui { border-color: #166534; background: #14291d; color: #bbf7d0; }
  button.non { border-color: #7f1d1d; background: #2a1414; color: #fecaca; }
  .aide { font-size: .8rem; color: #94a3b8; }
  .voile { position: fixed; inset: 0; background: rgba(2, 6, 23, .8); z-index: 50; display: flex; padding: 1.5rem; }
  .feuilles { flex: 1; display: flex; flex-direction: column; background: #1e293b; border: 1px solid #334155; border-radius: .4rem; overflow: hidden; }
  .feuilles header { display: flex; justify-content: space-between; align-items: center; padding: .5rem .8rem; color: #e2e8f0; }
  .feuilles header button { border: 1px solid #475569; border-radius: .3rem; padding: .3rem .7rem; color: #e2e8f0; }
  .feuilles iframe { flex: 1; width: 100%; border: 0; background: #fff; }
</style>
