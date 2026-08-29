<script>
  import { COMMUNE_DE, SITE_NOM } from '$lib/instance.js'
  import { libelleAnnee } from '$lib/actes.js'
  import Niveau from '$lib/components/Niveau.svelte'
  import SourceAbsente from '$lib/components/SourceAbsente.svelte'

  // Rendu au build par +page.server.js : sommaire des millésimes + index
  // compact des titres. Les actes eux-mêmes vivent sur /deliberations/<année>.
  export let data
  $: ({ annees, index, total, nCM, nCC, anneeCourante, nCourante, votes } = data)
  // Aucune délibération collectée : ne pas afficher « 0 acte », qui se lit
  // « le conseil n'a rien décidé » au lieu de « nous n'avons pas collecté les
  // comptes rendus ». C'est le cas de tout dossier national.
  $: source = data.source || { etat: 'servie', sources: [] }

  let q = '', instance = 'all'

  const fold = (s) => (s || '').toLowerCase()
  $: needle = fold(q.trim())
  $: resultats = needle.length < 2 ? [] : index
    .filter((e) => instance === 'all' || e.instance === instance)
    .filter((e) => fold(e.titre).includes(needle))
    .slice(0, 80)
  $: nTrouves = needle.length < 2 ? 0 : index
    .filter((e) => instance === 'all' || e.instance === instance)
    .filter((e) => fold(e.titre).includes(needle)).length

  const fmtDate = (d) => {
    if (!d) return '—'
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return d }
  }
</script>

<svelte:head><title>Délibérations &amp; actes officiels — {SITE_NOM}</title>
  <meta name="description" content="Les {total} actes officiels {COMMUNE_DE} et de son intercommunalité, année par année : délibérations du conseil municipal, procès-verbaux communautaires, votes, montants et documents source." /></svelte:head>

<section>
  <h1>Délibérations &amp; actes officiels</h1>
  <p class="sub">Conseil municipal, communauté de communes et actes issus des sources officielles. (Agenda culturel → <a href="/vie-locale">Vie locale</a>.)</p>

  {#if source.etat === 'absente'}
    <SourceAbsente etat={source.etat} sources={source.sources} dernier={source.dernier} travailManuel
                   quoi="Les actes des assemblées" />
  {:else if !total}
    <p class="err">Aucun acte dans ce jeu de données.</p>
  {:else}
    <!-- « 592 actes » ne figure dans aucun document : c'est le compte de ce que
         la collecte a trouvé. Un acte non collecté n'y est pas. -->
    <Niveau type="calcul" compact base="les actes collectés depuis les sources officielles" />
    <div class="tiles">
      <div class="tile"><span class="tval">{total}</span><span class="tlabel">actes recensés</span></div>
      <div class="tile"><span class="tval">{nCM}</span><span class="tlabel">conseil municipal</span></div>
      <div class="tile"><span class="tval">{nCC}</span><span class="tlabel">intercommunalité</span></div>
      <div class="tile"><span class="tval">{nCourante}</span><span class="tlabel">en {anneeCourante}</span></div>
    </div>

    <div class="filters">
      <input placeholder="Rechercher un acte, toutes années confondues…" bind:value={q} />
      <div class="seg">
        {#each [['all', 'Tout'], ['CM', 'Municipal'], ['CC', 'Intercommunal']] as [v, l]}
          <button class:on={instance === v} on:click={() => instance = v}>{l}</button>
        {/each}
      </div>
    </div>

    {#if needle.length >= 2}
      <p class="count">
        {nTrouves} acte{nTrouves > 1 ? 's' : ''} trouvé{nTrouves > 1 ? 's' : ''}
        {#if nTrouves > resultats.length}· {resultats.length} premiers affichés{/if}
      </p>
      {#if resultats.length}
        <ul class="res">
          {#each resultats as e (e.id)}
            <li>
              <a href="/deliberations/{e.annee}#a{e.id}">
                <span class="date">{fmtDate(e.date)}</span>
                <span class="badge {e.instance}">{e.label}</span>
                <span class="titre">{e.titre || '(sans titre)'}</span>
              </a>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Aucun acte ne correspond.</p>
      {/if}
    {:else}
      {#if votes}
        <Niveau type="calcul" base="les actes dont le compte rendu détaille le vote">
          Sur <b>{votes.connus}</b> actes dont le vote est connu,
          <b>{votes.sansOpposition}</b> ont été adoptés sans une voix contre ni une
          abstention — soit <b>{Math.round(100 * votes.sansOpposition / votes.connus)} %</b>.
          <b>{votes.divises}</b> ont donné lieu à un désaccord exprimé.
        </Niveau>
        <p class="lecture">
          <b>Ce que ce chiffre ne dit pas.</b> Un vote unanime ne signifie pas
          qu'il n'y a pas eu de débat&nbsp;: le compte rendu enregistre le
          résultat, rarement la discussion. Il ne signifie pas non plus que la
          décision allait de soi — dans un conseil de quinze personnes, un
          désaccord se règle souvent avant le vote. Le vote n'est d'ailleurs
          détaillé que pour {votes.connus} des {total} actes recensés.
        </p>

        {#if votes.exemples.length}
          <h2>Les décisions qui ont fait débat</h2>
          <ul class="debats">
            {#each votes.exemples as e}
              <li>
                <a href="/deliberations/{e.annee}#a{e.id}">
                  <span class="date">{fmtDate(e.date)}</span>
                  <span class="titre">{e.titre || '(sans titre)'}</span>
                  <span class="vote">
                    {e.vote.pour ?? '?'} pour{#if e.vote.contre} · {e.vote.contre} contre{/if}{#if e.vote.abstention} · {e.vote.abstention} abst.{/if}
                  </span>
                </a>
              </li>
            {/each}
          </ul>
        {/if}
      {/if}

      <h2>Par année</h2>
      <ul class="annees">
        {#each annees as a}
          <li>
            <a href="/deliberations/{a.annee}">
              <span class="an">{libelleAnnee(a.annee)}</span>
              <span class="n">{a.total} acte{a.total > 1 ? 's' : ''}</span>
              <span class="detail">{a.cm} municipal · {a.cc} intercommunal</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .lecture {
    margin: .5rem 0 1.5rem; padding: .7rem .9rem;
    border-left: 3px solid var(--ambre); background: var(--ambre-pale);
    border-radius: 0 var(--rayon) var(--rayon) 0;
    font-size: .9rem; line-height: 1.55; color: var(--gris);
  }
  .lecture b { color: var(--encre); }

  .debats { list-style: none; padding: 0; margin: 0 0 1.5rem; }
  .debats li { border-bottom: 1px solid var(--ardoise-pale); }
  .debats a { display: grid; grid-template-columns: 92px 1fr auto; gap: .75rem;
              align-items: baseline; padding: .5rem; text-decoration: none; }
  .debats a:hover { background: var(--papier); }
  .debats .vote { font-size: .8rem; color: var(--ambre); font-weight: 600; white-space: nowrap; }
  @media (max-width: 680px) { .debats a { grid-template-columns: 1fr; gap: .2rem; } }

  section { max-width: 950px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0 0 1.25rem; }
  .sub a { color: var(--ardoise); }
  h2 { font-size: 1rem; margin: 1.5rem 0 .6rem; }

  .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; margin-bottom: 1.25rem; }
  .tile { background: #fff; border: 1px solid var(--trait); border-radius: 8px; padding: .7rem .9rem; display: flex; flex-direction: column; }
  .tval { font-size: 1.5rem; font-weight: 700; }
  .tlabel { font-size: .72rem; color: var(--gris); text-transform: uppercase; letter-spacing: .02em; }

  .filters { display: flex; gap: .75rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
  input { flex: 1; min-width: 200px; padding: .5rem .7rem; border: 1px solid var(--trait); border-radius: 6px; }
  .seg { display: inline-flex; border: 1px solid var(--trait); border-radius: 6px; overflow: hidden; }
  .seg button { padding: .45rem .8rem; font-size: .85rem; background: #fff; color: var(--gris); border: none; border-left: 1px solid var(--trait); }
  .seg button:first-child { border-left: none; }
  .seg button.on { background: var(--ardoise); color: #fff; }
  .count { color: var(--gris); font-size: .85rem; margin: 0 0 .6rem; }

  .annees { list-style: none; padding: 0; margin: 0; display: grid; gap: .5rem;
            grid-template-columns: repeat(auto-fill, minmax(215px, 1fr)); }
  .annees a { display: grid; gap: .1rem; padding: .7rem .9rem; background: #fff;
              border: 1px solid var(--trait); border-radius: 8px; text-decoration: none; }
  .annees a:hover { border-color: var(--ardoise); }
  .an { font-size: 1.15rem; font-weight: 700; color: var(--encre); }
  .n { font-size: .85rem; color: var(--ardoise); }
  .detail { font-size: .74rem; color: var(--gris); }

  .res { list-style: none; padding: 0; margin: 0; }
  .res li { border-bottom: 1px solid var(--ardoise-pale); }
  .res a { display: grid; grid-template-columns: 92px 130px 1fr; gap: .75rem; align-items: baseline;
           padding: .5rem; text-decoration: none; }
  .res a:hover { background: var(--papier); }
  .date { color: var(--gris); font-variant-numeric: tabular-nums; font-size: .82rem; white-space: nowrap; }
  .badge { font-size: .66rem; font-weight: 700; text-transform: uppercase; letter-spacing: .02em;
           padding: .12rem .5rem; border-radius: 99px; white-space: nowrap; align-self: start; }
  .badge.CM { background: var(--ardoise-pale); color: var(--ardoise-fonce); }
  .badge.CC { background: #e7f0ea; color: var(--recette); }
  .titre { color: var(--encre); font-size: .9rem; }

  .muted { color: var(--gris-clair); } .err { color: var(--depense); }
  @media (max-width: 680px) {
    .tiles { grid-template-columns: repeat(2, 1fr); }
    .res a { grid-template-columns: 1fr; gap: .2rem; }
  }
</style>
