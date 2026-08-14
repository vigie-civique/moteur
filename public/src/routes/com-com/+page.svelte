<script>
  import { COMMUNE, COMMUNE_DE, EPCI, EPCI_COURT, SITE_NOM } from '$lib/instance.js'

  // Cette page répond à une seule question : qu'est-ce qui ne se décide plus
  // à la mairie, et qui le décide à la place ?
  //
  // Elle lit `intercommunalite.json`, exporté par build_public_snapshot.py
  // depuis BANATIC. La version précédente reconstruisait la liste des délégués
  // en croisant relations et conseils municipaux avec des expressions
  // régulières : elle ratait les délégués des autres communes et se trompait
  // dès qu'une relation manquait. Les compétences, elles, n'existaient nulle
  // part — c'était pourtant l'information centrale.

  // Rendu au build par +page.server.js (le filtrage des actes CC y est fait).
  export let data
  $: cc = data.cc
  $: events = data.events

  // Les compétences obligatoires sont imposées par la loi, les facultatives
  // ont été transférées par choix des communes : la distinction dit qui a
  // décidé du transfert, elle mérite deux blocs séparés.
  $: obligatoires = (cc?.competences || []).filter(c => c.obligatoire)
  $: facultatives = (cc?.competences || []).filter(c => !c.obligatoire)

  $: communeDuSite = (cc?.membres || []).find(m => m.est_commune_du_site)
  $: totalSieges = (cc?.membres || []).reduce((s, m) => s + (m.sieges || 0), 0)
  $: maxSieges = Math.max(1, ...(cc?.membres || []).map(m => m.sieges || 0))

  // Habitants par siège : le chiffre qui dit si une commune pèse plus ou moins
  // que son poids démographique. Sans lui, un tableau de sièges ne se compare
  // pas — 5 sièges pour 1 202 habitants ne veut rien dire seul.
  const parSiege = (m) => m.sieges ? Math.round(m.population / m.sieges) : null

  // Deux sources, deux rôles, et il ne faut pas les intervertir :
  //   · les NOMS viennent du Répertoire National des Élus (publication du
  //     11/08/2026), postérieur aux municipales de mars 2026 ;
  //   · la RÉPARTITION DES SIÈGES vient de BANATIC, parce qu'elle est fixée par
  //     arrêté préfectoral et ne bouge pas avec le scrutin.
  // Jusqu'au 12/08/2026 les noms venaient aussi de BANATIC (état du 10/2025) :
  // la page affichait un président et deux vice-présidents qui n'étaient plus
  // délégués. Ne pas revenir en arrière sur ce point.
  //
  // Le rattachement communal n'est affiché que quand il est vérifié
  // (`commune_fiable`) : le RNE range une partie des délégués sous la commune
  // commune du siège de l'intercommunalité et non leur commune d'élection.
  $: delegues = cc?.delegues || []
  $: delegesCommune = delegues.filter(d => d.commune_fiable && d.commune === communeDuSite?.nom)
  $: delegesAutres = delegues.filter(d => !(d.commune_fiable && d.commune === communeDuSite?.nom))

  const nb = (n) => n?.toLocaleString('fr-FR') ?? '—'
</script>

<svelte:head>
  <title>Intercommunalité ({EPCI_COURT}) — {SITE_NOM}</title>
  <meta name="description"
        content="Ce que la {EPCI} décide à la place {COMMUNE_DE} : compétences transférées, délégués, poids de chaque commune." />
</svelte:head>

<section>
  <h1>L'intercommunalité</h1>
  <p class="sub">
    {COMMUNE} est membre de la <strong>{EPCI}</strong>.
    Une part des décisions qui concernent la commune ne se prend plus au conseil municipal,
    mais dans cette assemblée. Voici laquelle, et par qui.
  </p>



  {#if cc}
    <div class="reperes">
      <div class="repere">
        <span class="chiffre">{cc.membres?.length ?? '—'}</span>
        <span class="libelle">communes membres</span>
      </div>
      <div class="repere">
        <span class="chiffre">{nb(cc.population)}</span>
        <span class="libelle">habitants</span>
      </div>
      <div class="repere">
        <span class="chiffre">{cc.competences?.length ?? '—'}</span>
        <span class="libelle">compétences exercées</span>
      </div>
      <div class="repere accent">
        <span class="chiffre">{communeDuSite?.sieges ?? '—'}<span class="sur">/{totalSieges}</span></span>
        <span class="libelle">sièges pour {COMMUNE}</span>
      </div>
    </div>

    <!-- 1. La question centrale -->
    <h2>Ce qui ne se décide plus à la mairie</h2>
    <p class="chapeau">
      Une compétence transférée sort du conseil municipal : la commune ne peut plus décider seule
      sur ce sujet. Les <strong>obligatoires</strong> sont imposées par la loi ; les
      <strong>facultatives</strong> ont été transférées par choix des communes.
    </p>

    <h3 class="ss-titre">
      Compétences obligatoires <span class="compte">{obligatoires.length}</span>
    </h3>
    <ul class="competences">
      {#each obligatoires as c (c.code)}
        <li>
          <span class="comp-libelle">{c.libelle}</span>
          {#if c.categorie}<span class="comp-cat">{c.categorie}</span>{/if}
          {#if c.interet_communautaire}
            <span class="comp-flag" title="Le périmètre exact de cette compétence est défini par le conseil communautaire lui-même">intérêt communautaire</span>
          {/if}
        </li>
      {/each}
    </ul>

    <h3 class="ss-titre">
      Compétences facultatives <span class="compte">{facultatives.length}</span>
    </h3>
    <ul class="competences">
      {#each facultatives as c (c.code)}
        <li>
          <span class="comp-libelle">{c.libelle}</span>
          {#if c.categorie}<span class="comp-cat">{c.categorie}</span>{/if}
        </li>
      {/each}
    </ul>

    <!-- 2. Le poids relatif -->
    <h2>Le poids de chaque commune</h2>
    <p class="chapeau">
      Le nombre de sièges détermine le pouvoir de vote. Rapporté à la population, il dit si une
      commune pèse plus ou moins que son poids démographique.
    </p>
    <div class="tableau-wrap">
      <table>
        <thead>
          <tr>
            <th>Commune</th>
            <th class="num">Habitants</th>
            <th class="num">Sièges</th>
            <th>Part des sièges</th>
            <th class="num" title="Nombre d'habitants représentés par un siège : plus le chiffre est bas, plus la commune est surreprésentée">Hab. par siège</th>
          </tr>
        </thead>
        <tbody>
          {#each cc.membres as m (m.insee)}
            <tr class:ici={m.est_commune_du_site}>
              <td>
                {m.nom}
                {#if m.est_commune_du_site}<span class="ici-tag">ici</span>{/if}
              </td>
              <td class="num">{nb(m.population)}</td>
              <td class="num">{m.sieges || '—'}</td>
              <td class="barre-cell">
                <span class="barre" style="width:{(m.sieges / maxSieges) * 100}%"
                      aria-hidden="true"></span>
              </td>
              <td class="num">{parSiege(m) ? nb(parSiege(m)) : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- 3. Qui siège -->
    <h2>Qui y siège</h2>
    <p class="chapeau">
      L'assemblée issue des élections municipales de mars 2026, telle qu'elle figure au
      <strong>Répertoire National des Élus</strong>. Le nombre de sièges par commune, lui,
      est fixé par arrêté préfectoral et ne change pas avec le scrutin&nbsp;: il vient de BANATIC.
    </p>

    {#if delegesCommune.length}
      <h3 class="ss-titre">
        Pour {COMMUNE}
        <span class="compte">{delegesCommune.length} délégué{delegesCommune.length > 1 ? 's' : ''}</span>
      </h3>
      <ul class="delegues">
        {#each delegesCommune as d}
          <li>
            <span class="nom">{d.name}</span>
            <span class="fonction">{d.fonction}</span>
          </li>
        {/each}
      </ul>
    {/if}

    {#if delegesAutres.length}
      <h3 class="ss-titre">
        Pour les autres communes <span class="compte">{delegesAutres.length}</span>
      </h3>
      <ul class="delegues autres">
        {#each delegesAutres as d}
          <li>
            <span class="nom">{d.name}</span>
            <span class="commune">{d.commune_fiable ? d.commune : 'commune à confirmer'}</span>
            <span class="fonction">{d.fonction}</span>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- 4. Le deuxième étage de délégation -->
    {#if cc.syndicats?.length}
      <h2>Un deuxième étage de délégation</h2>
      <p class="chapeau">
        Une compétence transférée à l'intercommunalité peut être re-transférée à un syndicat.
        La décision s'éloigne alors d'un cran de plus du conseil municipal.
      </p>
      <ul class="syndicats">
        {#each cc.syndicats as s (s.id)}
          <li><a href="/entite/{s.id}">{s.name}</a></li>
        {/each}
      </ul>
    {/if}

    <!-- 5. Les actes -->
    {#if events.length}
      <h2>Les actes du conseil communautaire</h2>
      <p class="chapeau">
        Délibérations, procès-verbaux et arrêtés préfectoraux — les 40 plus récents.
        Le site de la communauté de communes ne conserve pas tout en ligne : ces documents
        sont archivés à mesure de leur publication.
      </p>
      <ul class="liste">
        {#each events as e (e.id)}
          <li>
            <span class="date">{e.date || '—'}</span>
            <span class="titre">{e.title || '(sans titre)'}</span>
            {#if e.source_url}
              <a href={e.source_url} target="_blank" rel="noopener">source ↗</a>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    <!-- 6. Ce que cette page ne sait pas -->
    <aside class="sources">
      <h3>D'où viennent ces données</h3>
      <p>
        Compétences et répartition des sièges proviennent de <strong>BANATIC</strong>, la base
        nationale de l'intercommunalité tenue par le ministère de l'Intérieur. Les délégués
        proviennent du <strong>Répertoire National des Élus</strong>, tenu par la DGCL.
      </p>
      {#if cc.note_sources}
        <p class="reserve">{cc.note_sources}</p>
      {/if}
      <p class="lien-methode">
        Délégués : {cc.delegues_source ?? 'Répertoire National des Élus'}. ·
        Répartition des sièges : {cc.sieges_source}. ·
        <a href="/comprendre/intercommunalite">Comprendre l'intercommunalité</a> ·
        <a href="/methode">Méthode &amp; sources</a>
      </p>
    </aside>
  {/if}
</section>

<style>
  section { max-width: 950px; margin: 0 auto; padding: 1.5rem; }

  h1 { font-family: var(--display); color: var(--encre); margin: 0 0 .4rem; }
  h2 {
    font-family: var(--display); color: var(--encre);
    margin: 2.4rem 0 .4rem; font-size: 1.35rem;
    padding-top: 1.2rem; border-top: 1px solid var(--trait);
  }
  h3.ss-titre {
    font-family: var(--texte); font-size: .78rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: .07em; color: var(--gris);
    margin: 1.4rem 0 .5rem;
  }
  .compte {
    font-variant-numeric: tabular-nums; color: var(--gris-clair);
    font-weight: 400; margin-left: .2rem;
  }
  .sub { color: var(--gris); margin: 0 0 1.4rem; max-width: 62ch; line-height: 1.5; }
  .chapeau { color: var(--gris); margin: .2rem 0 1rem; max-width: 66ch; line-height: 1.5; }

  /* Repères chiffrés */
  .reperes {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: .8rem; margin: 1.4rem 0 .5rem;
  }
  .repere {
    background: var(--blanc); border: 1px solid var(--trait);
    border-radius: var(--rayon); padding: .8rem .9rem; box-shadow: var(--ombre);
  }
  .repere.accent { border-color: var(--ardoise); background: var(--ardoise-pale); }
  .chiffre {
    display: block; font-family: var(--data); font-size: 1.6rem;
    font-variant-numeric: tabular-nums; color: var(--encre); line-height: 1.1;
  }
  .repere.accent .chiffre { color: var(--ardoise); }
  .sur { font-size: .9rem; color: var(--gris-clair); }
  .libelle {
    display: block; font-size: .76rem; color: var(--gris);
    margin-top: .25rem; line-height: 1.3;
  }

  /* Compétences */
  .competences { list-style: none; padding: 0; margin: 0; }
  .competences li {
    padding: .5rem .1rem; border-bottom: 1px solid var(--trait-pale);
    display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap;
  }
  .comp-libelle { color: var(--encre); flex: 1 1 22ch; }
  .comp-cat {
    font-size: .74rem; color: var(--gris); background: var(--papier);
    border: 1px solid var(--trait); border-radius: 99px; padding: .1rem .55rem;
  }
  .comp-flag {
    font-size: .72rem; color: var(--ambre); background: var(--ambre-pale);
    border-radius: 99px; padding: .1rem .55rem;
  }

  /* Tableau des communes */
  .tableau-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .92rem; }
  th {
    text-align: left; font-size: .74rem; text-transform: uppercase;
    letter-spacing: .05em; color: var(--gris); font-weight: 600;
    padding: .4rem .5rem; border-bottom: 1px solid var(--trait); white-space: nowrap;
  }
  td { padding: .45rem .5rem; border-bottom: 1px solid var(--trait-pale); }
  .num { text-align: right; font-family: var(--data); font-variant-numeric: tabular-nums; }
  tr.ici { background: var(--ardoise-pale); }
  tr.ici td { font-weight: 600; color: var(--encre); }
  .ici-tag {
    font-size: .68rem; text-transform: uppercase; letter-spacing: .05em;
    background: var(--ardoise); color: #fff; border-radius: 99px;
    padding: .05rem .45rem; margin-left: .4rem; font-weight: 600;
  }
  .barre-cell { width: 26%; min-width: 90px; }
  .barre {
    display: block; height: 9px; border-radius: 99px;
    background: var(--gris-clair); min-width: 2px;
  }
  tr.ici .barre { background: var(--ardoise); }

  /* Délégués */
  .delegues { list-style: none; padding: 0; margin: 0; }
  .delegues li {
    padding: .45rem .1rem; border-bottom: 1px solid var(--trait-pale);
    display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap;
  }
  .delegues .nom { color: var(--encre); font-weight: 600; flex: 1 1 16ch; }
  .delegues.autres .nom { font-weight: 400; }
  .commune { font-size: .82rem; color: var(--gris); }
  .fonction {
    font-size: .74rem; color: var(--recette); background: #e7f0ea;
    border-radius: 99px; padding: .1rem .55rem;
  }

  /* Syndicats */
  .syndicats { list-style: none; padding: 0; margin: 0; }
  .syndicats li { padding: .4rem .1rem; border-bottom: 1px solid var(--trait-pale); }
  .syndicats a { color: var(--encre); }

  /* Délibérations */
  .liste { list-style: none; padding: 0; margin: 0; }
  .liste li {
    display: grid; grid-template-columns: 105px 1fr auto; gap: 1rem;
    align-items: baseline; padding: .45rem .1rem;
    border-bottom: 1px solid var(--trait-pale);
  }
  .date { color: var(--gris); font-family: var(--data); font-size: .85rem; }
  .titre { color: var(--encre); }

  /* Réserves de source */
  .sources {
    margin-top: 2.4rem; padding: 1rem 1.1rem;
    background: var(--papier); border: 1px solid var(--trait);
    border-radius: var(--rayon);
  }
  .sources h3 {
    font-family: var(--texte); font-size: .78rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: .07em; color: var(--gris);
    margin: 0 0 .5rem;
  }
  .sources p { margin: .35rem 0; font-size: .88rem; color: var(--encre); line-height: 1.5; }
  .reserve { color: var(--gris); }
  .lien-methode { font-size: .82rem; color: var(--gris); margin-top: .7rem; }


  @media (max-width: 640px) {
    .liste li { grid-template-columns: 1fr; gap: .15rem; }
    h2 { font-size: 1.2rem; }
  }
</style>
