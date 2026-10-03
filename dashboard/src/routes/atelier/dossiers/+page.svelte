<script>
  // Les dossiers thématiques — écrite le 01/10/2026.
  //
  // Un dossier est le seul texte du site écrit par un humain. Il s'éditait sur
  // le disque et sortait sur une ligne de son en-tête (`statut: publie`). Il
  // s'édite désormais ici, et ne sort que RETENU par un validateur, tel qu'il a
  // été relu : une modification après relecture le retire du site jusqu'à ce
  // qu'il soit retenu de nouveau (`collectors/verdict.py`, empreinte).
  //
  // Écrire PROPOSE (contributeur et au-dessus) ; retenir TRANCHE (validateur).
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { marked } from 'marked'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins, messageErreur } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'

  $: tranche = auMoins($currentUser, 'validator')
  $: ecrit = auMoins($currentUser, 'contributor')

  const LIBELLE = { jamais_relu: 'Jamais relu', retenu: 'Retenu — publié', a_revoir: 'À revoir', ecarte: 'Écarté' }

  // Ce qui a changé parmi les actes cités depuis la relecture (api.py,
  // `_dossier_ligne` → collectors/dossiers.py::peremption).
  const perimeDetail = (d) => (d.perime?.elements || [])
    .map((e) => `${e.libelle} : ${e.quoi === 'disparu' ? "n'est plus publiée" : e.champs.join(', ') + ' modifié'}`)
    .join('\n')
  // Ce que le résolveur fait des citations du texte enregistré.
  const citationsResume = (d) => {
    const n = (s) => d.citations.filter((c) => c.statut === s).length
    return [`${n('precis') + n('imprecis')} citation(s) reliée(s)`,
            n('non_resolu') ? `${n('non_resolu')} sans acte publié` : ''].filter(Boolean).join(' · ')
  }
  const citationsDetail = (d) => d.citations
    .map((c) => `${c.texte} → ${c.statut === 'non_resolu' ? c.raison : c.cle}${c.statut === 'imprecis' ? ' (imprécis)' : ''}`)
    .join('\n')

  let dossiers = []
  let loading = true
  let error = ''
  let avis = ''
  let occupe = false

  // L'éditeur : un dossier ouvert à la fois.
  let ouvert = null      // la ligne du dossier, telle que chargée
  let texte = ''
  let lu = ''            // le texte tel qu'il a été chargé ou enregistré
  let note = ''
  let nouveau = { slug: '', titre: '' }

  $: sale = ouvert && texte !== lu

  onMount(() => {
    charger()
    const garde = (e) => { if (sale) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', garde)
    return () => window.removeEventListener('beforeunload', garde)
  })

  async function motif(res, defaut) {
    const d = (await res.json().catch(() => ({}))).detail
    return messageErreur(d, defaut)
  }

  async function charger() {
    loading = true; error = ''
    try {
      const res = await authFetch('/atelier/dossiers')
      if (!res.ok) throw new Error(`${res.status}`)
      dossiers = await res.json()
    } catch (e) { error = e.message }
    finally { loading = false }
  }

  async function ouvrir(slug) {
    if (sale && !confirm('Les modifications non enregistrées seront perdues. Continuer ?')) return
    avis = ''
    const res = await authFetch(`/atelier/dossiers/${slug}`)
    if (!res.ok) { avis = await motif(res, `Ouverture impossible (${res.status}).`); return }
    ouvert = await res.json()
    texte = lu = ouvert.texte
    note = ouvert.note || ''
  }

  function fermer() {
    if (sale && !confirm('Les modifications non enregistrées seront perdues. Fermer ?')) return
    ouvert = null; texte = lu = ''
  }

  async function enregistrer() {
    occupe = true; avis = ''
    try {
      const res = await authFetch(`/atelier/dossiers/${ouvert.slug}`, {
        method: 'PUT', body: JSON.stringify({ texte, empreinte_lue: ouvert.empreinte }),
      })
      if (res.ok) {
        const etait = ouvert.verdict
        await charger()
        await rouvrir()
        avis = 'Enregistré.' + (etait === 'retenu'
          ? ' Ce dossier était retenu : il ne sortira plus tant qu’un validateur ne l’aura pas relu et retenu de nouveau.'
          : '')
      } else {
        avis = await motif(res, `L'enregistrement a échoué (${res.status}).`)
        if (res.status === 409) avis += ' Copiez votre texte avant de recharger le dossier.'
      }
    } finally { occupe = false }
  }

  async function rouvrir() {
    const res = await authFetch(`/atelier/dossiers/${ouvert.slug}`)
    if (res.ok) { ouvert = await res.json(); texte = lu = ouvert.texte }
  }

  async function decider(d, review_status) {
    if (sale) { avis = 'Enregistrez d’abord le texte : on ne retient que ce qui a été enregistré.'; return }
    occupe = true; avis = ''
    try {
      const corps = { note: d === ouvert ? note : (d.note || ''), lu_le: d.reviewed_at,
                      empreinte_vue: d.empreinte }
      if (review_status) corps.review_status = review_status
      const res = await authFetch(`/atelier/annotations/dossier/${d.dossier_id}`, {
        method: 'PATCH', body: JSON.stringify(corps),
      })
      if (res.ok) {
        avis = `${d.titre} : ${review_status ? LIBELLE[review_status].toLowerCase() : 'note enregistrée'}.`
          + (review_status === 'retenu' ? ' Il sortira à la prochaine publication.' : '')
        await charger()
        if (ouvert) await rouvrir()
      } else {
        avis = await motif(res, `La décision a échoué (${res.status}).`)
        if (res.status === 409) await charger()
      }
    } finally { occupe = false }
  }

  async function creer() {
    occupe = true; avis = ''
    try {
      const res = await authFetch('/atelier/dossiers', {
        method: 'POST', body: JSON.stringify(nouveau),
      })
      if (res.ok) {
        const { slug } = await res.json()
        nouveau = { slug: '', titre: '' }
        await charger()
        await ouvrir(slug)
      } else {
        avis = await motif(res, `La création a échoué (${res.status}).`)
      }
    } finally { occupe = false }
  }

  // L'aperçu : l'en-tête lu comme le site le lit, le corps rendu par la même
  // bibliothèque. Il s'affiche dans un cadre SANS script (sandbox) : un texte
  // proposé par un contributeur ne s'exécute pas chez le validateur qui le relit.
  function entete(t) {
    const m = /^---\n([\s\S]*?)\n---\n?/.exec(t)
    if (!m) return { meta: {}, corps: t }
    const meta = {}
    for (const l of m[1].split('\n')) {
      const k = /^([a-z_]+)\s*:\s*(.*?)\s*(#.*)?$/.exec(l)
      if (k) meta[k[1]] = k[2].replace(/^["']|["']$/g, '')
    }
    return { meta, corps: t.slice(m[0].length) }
  }

  const echapper = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

  const STYLE = `body{font:16px/1.6 system-ui,-apple-system,sans-serif;color:#14202a;background:#fff;
    max-width:44rem;margin:0 auto;padding:1.4rem}
    h1,h2,h3{font-family:"Iowan Old Style",Palatino,Georgia,serif;font-weight:600;line-height:1.25}
    h1{font-size:1.8rem;margin:0 0 .4rem}.chapeau{color:#5c6b72;font-size:1.05rem;margin:0 0 1.2rem}
    h2{font-size:1.3rem;margin:1.8rem 0 .5rem;border-bottom:1px solid #dde2df;padding-bottom:.3rem}
    a{color:#14556b}table{border-collapse:collapse;font-size:.9rem}td,th{border:1px solid #dde2df;padding:.3rem .5rem}
    details{border-left:3px solid #dde2df;padding:.2rem .8rem;margin:.8rem 0}summary{cursor:pointer;color:#14556b}
    blockquote{border-left:3px solid #14556b;margin:.8rem 0;padding:.1rem .9rem;color:#5c6b72}
    .bandeau{font-size:.8rem;color:#9a6b12;background:#f7f1e4;padding:.3rem .6rem;border-radius:4px;display:inline-block}`

  $: rendu = (() => {
    if (!ouvert) return ''
    const { meta, corps } = entete(texte)
    let html = ''
    try { html = marked.parse(corps.replace(/^# .*\n/, '')) } catch (e) { html = `<p>Rendu impossible : ${echapper(e.message)}</p>` }
    return `<!doctype html><meta charset="utf-8"><style>${STYLE}</style>`
      + `<p class="bandeau">Aperçu de l’atelier — non publié</p>`
      + `<h1>${echapper(meta.titre || ouvert.slug)}</h1>`
      + (meta.chapeau ? `<p class="chapeau">${echapper(meta.chapeau)}</p>` : '')
      + (meta.statut === 'a_developper' ? '<p class="bandeau">À développer : seul le titre et le chapeau sortent.</p>' : '')
      + html
  })()
</script>

<svelte:head><title>Dossiers — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <header>
    <div>
      <a class="retour" href="/atelier">← Aujourd'hui</a>
      <h1>Dossiers thématiques</h1>
      <p class="intro">
        Un dossier relie les faits d'un thème : qui décide, ce que ça coûte, et ce
        qu'on ne sait pas encore. On l'écrit ici, à plusieurs.
        <strong>Il ne sort sur le site que retenu par un validateur, et tel qu'il a été relu</strong> :
        une modification après relecture le retire jusqu'à la relecture suivante.
      </p>
    </div>
    {#if !loading}
      <p class="compte"><strong>{dossiers.filter(d => d.verdict !== 'retenu' || d.modifie || d.perime).length}</strong>
        à relire sur {dossiers.length}</p>
    {/if}
  </header>

  {#if avis}<p class="avis">{avis}</p>{/if}

  {#if ouvert}
    <section class="editeur">
      <div class="barre">
        <div>
          <strong>{ouvert.titre}</strong> <code>{ouvert.slug}.md</code>
          · <span class="verdict">{LIBELLE[ouvert.verdict]}</span>
          {#if ouvert.modifie}<span class="modifie">modifié depuis la relecture — ne sort plus</span>{/if}
          {#if ouvert.perime}<span class="modifie" title={perimeDetail(ouvert)}>à revoir : un acte cité a changé — reste en ligne</span>{/if}
          {#if ouvert.citations?.length}<span class="tag" title={citationsDetail(ouvert)}>{citationsResume(ouvert)}</span>{/if}
          {#if sale}<span class="sale">non enregistré</span>{/if}
        </div>
        <div class="actions">
          {#if ecrit}
            <button class="oui" disabled={occupe || !sale} on:click={enregistrer}>Enregistrer</button>
          {/if}
          <button disabled={occupe} on:click={fermer}>Fermer</button>
        </div>
      </div>
      <div class="deux">
        <label class="saisie">
          <span>Texte (markdown) — <code>## L'essentiel</code>, <code>&lt;details class="plus"&gt;</code>, <code>## Les mots du dossier</code></span>
          <textarea bind:value={texte} readonly={!ecrit} spellcheck="true"></textarea>
        </label>
        <div class="apercu">
          <span>Aperçu</span>
          <iframe title="Aperçu du dossier" sandbox="" srcdoc={rendu}></iframe>
        </div>
      </div>
      {#if tranche}
        <div class="decision">
          <textarea rows="2" placeholder="Note de relecture (ce qu'il faudrait corriger, ou pourquoi vous retenez)"
                    bind:value={note}></textarea>
          <div class="actions">
            <button class="oui" disabled={occupe || sale} title={sale ? 'Enregistrez d’abord' : ''}
                    on:click={() => decider(ouvert, 'retenu')}>Retenir ce texte</button>
            <button disabled={occupe || sale} on:click={() => decider(ouvert, 'a_revoir')}>À revoir</button>
            <button class="non" disabled={occupe || sale} on:click={() => decider(ouvert, 'ecarte')}>Écarter</button>
          </div>
        </div>
      {/if}
    </section>
  {/if}

  {#if loading}<p class="msg">Chargement…</p>
  {:else if error}<p class="msg erreur">La liste n'a pas pu être chargée ({error}).</p>
  {:else}
    {#if !dossiers.length}<p class="msg">Aucun dossier dans <code>dossiers/</code>.</p>{/if}
    <ul class="liens">
      {#each dossiers as d (d.slug)}
        <li class="lien" class:retenu={d.verdict === 'retenu' && !d.modifie} class:ecarte={d.verdict === 'ecarte'}
            class:actif={ouvert && ouvert.slug === d.slug}>
          <p class="paire">{d.titre} <code>{d.slug}</code>
            {#if d.a_developper}<span class="tag">à développer</span>{/if}</p>
          {#if d.chapeau}<p class="chapeau">{d.chapeau}</p>{/if}
          <p class="meta">
            {d.mots} mots{#if d.maj} · mis à jour le {d.maj}{/if} ·
            <span class="verdict">{LIBELLE[d.verdict]}</span>
            {#if d.reviewed_at} par {d.reviewed_by}, {heureLocale(d.reviewed_at)}{/if}
            {#if d.modifie}<span class="modifie">modifié depuis la relecture — ne sort plus</span>{/if}
            <!-- Un acte cité a changé depuis la relecture : le dossier RESTE en
                 ligne avec un bandeau. « À revoir » est un état déduit, pas le
                 verdict — qui, pour un dossier, le retirerait du site. -->
            {#if d.perime}<span class="modifie" title={perimeDetail(d)}>à revoir : un acte cité a changé — reste en ligne</span>{/if}
          </p>
          <div class="actions">
            <button on:click={() => ouvrir(d.slug)}>{ecrit ? 'Ouvrir et modifier' : 'Lire'}</button>
          </div>
        </li>
      {/each}
    </ul>

    {#if ecrit}
      <form class="nouveau" on:submit|preventDefault={creer}>
        <strong>Nouveau dossier</strong>
        <input placeholder="Titre (ex. : Les déchets à {COMMUNE})" bind:value={nouveau.titre} required />
        <input placeholder="identifiant (ex. : dechets)" bind:value={nouveau.slug} required
               pattern="[a-z0-9][a-z0-9\-]*" title="minuscules, chiffres et tirets" />
        <button disabled={occupe}>Créer</button>
      </form>
    {/if}
  {/if}
</div>

<style>
  .page { padding: 1.2rem 1.4rem 2rem; max-width: 90rem; display: flex; flex-direction: column; gap: .9rem; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .retour { font-size: .85rem; color: var(--info); text-decoration: none; }
  h1 { font-size: 1.35rem; font-weight: 700; color: var(--texte); margin: .3rem 0 0; }
  .intro { font-size: .92rem; line-height: 1.5; color: var(--texte-doux); margin: .4rem 0 0; max-width: 46rem; }
  .intro strong { color: var(--texte-2); }
  .compte { font-size: .9rem; color: var(--texte-doux); margin: 0; }
  .compte strong { font-size: 1.5rem; color: var(--texte); }
  .msg { font-size: .92rem; color: var(--texte-doux); }
  .msg.erreur { color: var(--danger-texte); }
  .avis { font-size: .9rem; color: var(--succes-texte); background: var(--succes-doux); border-radius: .3rem; padding: .5rem .7rem; margin: 0; }
  code { font-size: .8rem; color: var(--texte-doux); }
  .liens { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr)); gap: .6rem; }
  .lien { padding: .85rem 1rem; border: 1px solid var(--bordure); border-radius: .45rem; background: var(--fond);
          display: flex; flex-direction: column; gap: .4rem; }
  .lien.retenu { border-color: var(--succes-bordure); }
  .lien.ecarte { opacity: .65; }
  .lien.actif { outline: 2px solid var(--focus); }
  .paire { font-size: 1.05rem; color: var(--texte); margin: 0; }
  .chapeau { font-size: .85rem; color: var(--texte-doux); margin: 0; }
  .tag { font-size: .7rem; font-weight: 700; padding: .1rem .4rem; border-radius: .3rem; background: var(--alerte-doux); color: var(--alerte-texte); }
  .meta { font-size: .82rem; color: var(--texte-doux); margin: 0; }
  .verdict { color: var(--texte); font-weight: 600; }
  .modifie { margin-left: .4rem; font-size: .78rem; color: var(--alerte-texte); background: var(--alerte-doux); border-radius: .3rem; padding: .05rem .4rem; }
  .sale { margin-left: .4rem; font-size: .78rem; color: var(--danger-texte); }
  .editeur { border: 1px solid var(--bordure-forte); border-radius: .5rem; background: var(--fond); padding: .8rem; display: flex; flex-direction: column; gap: .7rem; }
  .barre { display: flex; justify-content: space-between; align-items: center; gap: .6rem; flex-wrap: wrap; color: var(--texte); }
  .deux { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; }
  @media (max-width: 1000px) { .deux { grid-template-columns: 1fr; } }
  .saisie, .apercu { display: flex; flex-direction: column; gap: .3rem; font-size: .8rem; color: var(--texte-doux); }
  .saisie textarea { height: 70vh; font: .85rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
  iframe { height: 70vh; width: 100%; border: 1px solid var(--bordure); border-radius: .3rem; background: var(--papier); }
  textarea, input { background: var(--fond); color: var(--texte); border: 1px solid var(--bordure); border-radius: .3rem;
                    padding: .4rem .5rem; font: inherit; font-size: .88rem; resize: vertical; }
  .decision { display: flex; flex-direction: column; gap: .5rem; }
  .actions { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .nouveau { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; color: var(--texte); font-size: .9rem;
             border: 1px dashed var(--bordure); border-radius: .45rem; padding: .7rem 1rem; }
  .nouveau input { min-width: 14rem; }
  button { font: inherit; font-size: .88rem; padding: .35rem .8rem; border-radius: .3rem; border: 1px solid var(--bordure-forte);
           background: var(--surface); color: var(--texte); cursor: pointer; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  button.oui { border-color: var(--succes-bordure); background: var(--succes-doux); color: var(--succes-texte); }
  button.non { border-color: var(--danger-bordure); background: var(--danger-doux); color: var(--danger-texte); }
</style>
