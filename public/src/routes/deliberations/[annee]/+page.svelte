<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import { euros } from '$lib/data.js'
  import { INSTITUTIONAL, instanceDe, libelleAnnee } from '$lib/actes.js'
  import { axesDe } from '$lib/provenance.js'

  // Rendu au build par +page.server.js : les actes du millésime sont déjà
  // dans le HTML.
  export let data
  $: ({ annee, items, nCM, nCC, precedente, suivante, annees } = data)

  let q = '', instance = 'all'

  const inst = (e) => instanceDe(e)
  $: filtered = items
    .filter((e) => instance === 'all' || inst(e) === instance)
    .filter((e) => !q || (e.title || '').toLowerCase().includes(q.toLowerCase()))

  const fmtDate = (d) => {
    if (!d) return '—'
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return d }
  }
</script>

<svelte:head>
  <title>Délibérations {libelleAnnee(annee)} — {SITE_NOM}</title>
  <meta name="description" content="Les {items.length} actes officiels de {libelleAnnee(annee)} {COMMUNE_A} et dans son intercommunalité : délibérations du conseil municipal, procès-verbaux communautaires, votes et montants." />
</svelte:head>

<section>
  <p class="fil"><a href="/deliberations">Délibérations &amp; actes officiels</a> › {libelleAnnee(annee)}</p>
  <h1>Actes de {libelleAnnee(annee)}</h1>
  <p class="sub">
    {items.length} acte{items.length > 1 ? 's' : ''} · {nCM} du conseil municipal ·
    {nCC} de l'intercommunalité
  </p>

  <nav class="annees" aria-label="Choisir une année">
    {#each annees as a}
      <a href="/deliberations/{a}" class:on={a === annee}>{libelleAnnee(a)}</a>
    {/each}
  </nav>

  <div class="filters">
    <input placeholder="Rechercher dans les titres de {libelleAnnee(annee)}…" bind:value={q} />
    <div class="seg">
      {#each [['all', 'Tout'], ['CM', 'Municipal'], ['CC', 'Intercommunal']] as [v, l]}
        <button class:on={instance === v} on:click={() => instance = v}>{l}</button>
      {/each}
    </div>
    <span class="count">{filtered.length}</span>
  </div>

  {#if !filtered.length}
    <p class="muted">Aucun acte ne correspond. <a href="/deliberations">Chercher sur toutes les années →</a></p>
  {/if}

  <ul class="list">
    {#each filtered as e (e.id)}
      <li id="a{e.id}">
        <span class="date">{fmtDate(e.date)}</span>
        <span class="badge {inst(e)}">{INSTITUTIONAL[e.type].label}</span>
        <span class="title">
          {e.title || '(sans titre)'}
          {#if e.categorie}<span class="cat">{e.categorie}</span>{/if}
          {#if e.nb_deliberations}<span class="cat">{e.nb_deliberations} délibérations</span>{/if}
          {#if e.copie_archivee}<span class="cat arch" title={e.archive_note}>copie archivée</span>{/if}
        </span>
        <span class="meta">
          {#if e.montant_principal}<b class="montant">{euros(e.montant_principal)}</b>{/if}
          {#if e.vote}
            <span class="vote" class:unanime={e.vote.unanimite}
                  class:divise={!e.vote.unanimite && (e.vote.contre || e.vote.abstention)}>
              {#if e.vote.unanimite}
                unanimité
              {:else}
                {e.vote.pour ?? '?'}&nbsp;pour
                {#if e.vote.contre}· {e.vote.contre}&nbsp;contre{/if}
                {#if e.vote.abstention}· {e.vote.abstention}&nbsp;abst.{/if}
              {/if}
            </span>
          {/if}
          {#if e.source_url}<a href={e.source_url} target="_blank" rel="noopener">source ↗</a>{/if}
          {#if e.pdf_url && e.pdf_url !== e.source_url}<a href={e.pdf_url} target="_blank" rel="noopener">PDF ↗</a>{/if}
        </span>

        <!-- Les trois axes portés par l'acte lui-même, pas renvoyés dans une
             note de méthode : personne ne lit /methode avant d'interpréter une
             ligne. Le `title` porte l'explication longue pour qui la cherche. -->
        <span class="axes">
          {#each axesDe(e) as a}
            <span class="axe {a.axe} {a.cle}" title={a.long}>{a.court}</span>
          {/each}
        </span>
      </li>
    {/each}
  </ul>

  <nav class="pager">
    {#if precedente}<a href="/deliberations/{precedente}">← {libelleAnnee(precedente)}</a>{:else}<span></span>{/if}
    <a class="sommaire" href="/deliberations">Toutes les années</a>
    {#if suivante}<a href="/deliberations/{suivante}">{libelleAnnee(suivante)} →</a>{:else}<span></span>{/if}
  </nav>
</section>

<style>
  section { max-width: 950px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a { color: var(--ardoise); }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0 0 1.25rem; }

  .annees { display: flex; flex-wrap: wrap; gap: .35rem; margin-bottom: 1.25rem; }
  .annees a { font-size: .82rem; padding: .25rem .6rem; border: 1px solid var(--trait);
              border-radius: 99px; color: var(--gris); background: #fff; text-decoration: none; }
  .annees a.on { background: var(--ardoise); border-color: var(--ardoise); color: #fff; font-weight: 600; }

  .filters { display: flex; gap: .75rem; align-items: center; margin-bottom: 1.25rem; flex-wrap: wrap; }
  input { flex: 1; min-width: 200px; padding: .5rem .7rem; border: 1px solid var(--trait); border-radius: 6px; }
  .seg { display: inline-flex; border: 1px solid var(--trait); border-radius: 6px; overflow: hidden; }
  .seg button { padding: .45rem .8rem; font-size: .85rem; background: #fff; color: var(--gris); border: none; border-left: 1px solid var(--trait); }
  .seg button:first-child { border-left: none; }
  .seg button.on { background: var(--ardoise); color: #fff; }
  .count { color: var(--gris); font-size: .85rem; }

  .list { list-style: none; padding: 0; margin: 0; }
  .list li { display: grid; grid-template-columns: 92px 130px 1fr auto; gap: .2rem .75rem; align-items: baseline; padding: .5rem .5rem; border-bottom: 1px solid var(--ardoise-pale); }

  /* Les axes occupent la colonne du titre, sous lui : ils qualifient l'acte,
     ils ne doivent pas concurrencer son intitulé. */
  .axes { grid-column: 3 / -1; display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .15rem; }
  .axe {
    font-size: .66rem; padding: .05rem .4rem; border-radius: 99px;
    border: 1px solid var(--trait); color: var(--gris); background: var(--blanc);
    cursor: help;
  }
  .axe.primaire   { border-color: #cfe0d6; color: var(--recette); }
  .axe.registre   { border-color: var(--trait); color: var(--gris); }
  .axe.secondaire { border-color: #eadfc6; color: var(--ambre); }
  .axe.acte       { border-color: #cfe0d6; color: var(--recette); }
  .axe.aucun      { border-color: #eadfc6; color: var(--ambre); }
  .axe.extraction { border-color: #eadfc6; color: var(--ambre); }
  .axe.rectifie   { border-color: var(--ardoise-pale); color: var(--ardoise); }
  @media (max-width: 680px) { .axes { grid-column: 1; } }
  .list li:target { background: var(--ambre-pale); border-radius: 6px; }
  .date { color: var(--gris); font-variant-numeric: tabular-nums; font-size: .82rem; white-space: nowrap; }
  .badge { font-size: .66rem; font-weight: 700; text-transform: uppercase; letter-spacing: .02em; padding: .12rem .5rem; border-radius: 99px; white-space: nowrap; align-self: start; }
  .badge.CM { background: var(--ardoise-pale); color: var(--ardoise-fonce); }
  .badge.CC { background: #e7f0ea; color: var(--recette); }
  .title { color: var(--encre); font-size: .9rem; }
  .cat { display: inline-block; font-size: .68rem; color: var(--gris); background: var(--trait-pale);
         border-radius: 99px; padding: .05rem .5rem; margin-left: .4rem; white-space: nowrap; }
  .cat.arch { background: var(--ambre-pale); color: var(--ambre); }
  .meta { display: flex; gap: .6rem; font-size: .8rem; align-items: baseline; white-space: nowrap; }
  .meta a { color: var(--ardoise); }
  .montant { color: var(--encre); font-variant-numeric: tabular-nums; }
  .vote { font-size: .75rem; color: var(--gris); }
  .vote.unanime { color: var(--recette); }
  .vote.divise { color: var(--ambre); font-weight: 600; }
  .muted { color: var(--gris-clair); }
  .muted a { color: var(--ardoise); }

  .pager { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
           margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--trait); font-size: .88rem; }
  .pager a { color: var(--ardoise); text-decoration: none; }
  .pager .sommaire { color: var(--gris); }

  @media (max-width: 680px) { .list li { grid-template-columns: 1fr; gap: .2rem; } }
</style>
