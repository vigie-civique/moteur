<script>
  import { COMMUNE, COMMUNE_A, INSEE, SITE_NOM } from '$lib/instance.js'
  import Niveau from '$lib/components/Niveau.svelte'
  import Icon from '$lib/components/Icon.svelte'

  // Portrait de territoire. 1 812 indicateurs INSEE (1968→2024) dormaient en
  // base sans page publique : c'est pourtant le contexte qui donne son sens au
  // reste du site — un budget, une subvention ou un prix au m² ne se lisent pas
  // sans savoir combien de personnes vivent ici, et depuis quand.

  // Rendu au build par +page.server.js.
  export let data
  $: insee = data.insee
  $: constat = data.constat
  // Calculées au build : le nom de commune n'est plus dans `insee` (projection).
  $: voisines = data.voisines || []
  $: anneeFilo = data.anneeFilo || ''
  $: equipements = data.equipements || {}
  $: mouvements = equipements.mouvements || {}
  $: mobilite = data.mobilite || {}
  $: dispositifs = data.dispositifs || []

  // Le collecteur ne renseigne pas tous les libellés : on complète les codes
  // qui portent le propos, plutôt que d'afficher « EMP_1_Y15T64 » au lecteur.
  const LABELS = {
    POP: 'Population', DWELLINGS: 'Logements',
    DWELLINGS_DW_MAIN: 'Résidences principales',
    DWELLINGS_DW_SEC_DW_OCC: 'Résidences secondaires',
    DWELLINGS_DW_VAC: 'Logements vacants',
    BRTH: 'Naissances', DEATH: 'Décès', SUP: 'Superficie (km²)',
    FILO_MED_SL: 'Niveau de vie médian (par unité de consommation)',
    POPREF_PMUN: 'Population municipale',
    EMP_1_Y15T64: 'Actifs occupés (15-64 ans)',
    EMP_1T2_Y15T64: 'Actifs (15-64 ans)',
    POP_AGE_Y_LT15: 'Moins de 15 ans', POP_AGE_Y15T24: '15-24 ans',
    POP_AGE_Y25T39: '25-39 ans', POP_AGE_Y40T54: '40-54 ans',
    POP_AGE_Y55T64: '55-64 ans', POP_AGE_Y65T79: '65-79 ans',
    POP_AGE_Y_GE80: '80 ans et plus',
  }
  const label = (r) => r.libelle || LABELS[r.indicateur] || r.indicateur

  // La ligne de la commune de collecte, repérée par son code INSEE.
  const estCommune = (r) => r.insee === INSEE

  // `$:` et non `const` : une fonction déclarée en `const` qui lit `insee` ne
  // crée aucune dépendance réactive. `$: pop = serie('POP')` ne mentionne pas
  // `insee`, Svelte ne le réexécutait donc jamais après le chargement — la page
  // restait sur le résultat calculé à vide, d'où « Aucun indicateur disponible »
  // alors que les 1 812 indicateurs étaient bien chargés. Déclarées ainsi, les
  // deux fonctions sont recréées quand `insee` change, et tout ce qui en dépend
  // se recalcule.
  $: val = (code, annee) => {
    const hits = insee.filter(r => estCommune(r) && r.indicateur === code
                                   && (!annee || r.annee === annee))
    if (!hits.length) return null
    return hits.sort((a, b) => (b.annee || '').localeCompare(a.annee || ''))[0]
  }
  $: serie = (code) => insee
    .filter(r => estCommune(r) && r.indicateur === code && r.valeur != null)
    .sort((a, b) => (a.annee || '').localeCompare(b.annee || ''))

  // Y a-t-il quoi que ce soit à montrer ? La page ne se juge plus sur la seule
  // série de population : n'importe laquelle de ses sections suffit.
  $: aQuelqueChose = pop.length || logements.length || ageTotal > 0
                     || voisines.length > 1 || revenu || superficie || actifs

  // Le titre et le commentaire de la section « population » suivent la COURBE
  // de cette commune-ci. Écrits en dur, ils annonçaient « une population revenue
  // à son niveau de 1968 » à une commune ayant perdu un quart de ses habitants,
  // et « regagné 0 % depuis son point bas » à une autre dont le point bas est
  // l'année en cours. Le régime est calculé dans +page.server.js.
  //
  // De même, la page ne tient plus à la seule série POP : une commune peut avoir
  // 152 indicateurs INSEE et aucune série historique de population. Elle
  // affichait alors « Aucun indicateur disponible » et masquait le logement, les
  // âges et les niveaux de vie, qui étaient là. Chaque section décide pour elle.
  //
  // Enfin le niveau de vie : « la moitié des habitants vit avec moins » était
  // faux et faisait paraître le chiffre trop élevé. FiLoSoFi mesure un niveau de
  // vie par UNITÉ DE CONSOMMATION — revenu disponible du ménage divisé par 1
  // pour le premier adulte, 0,5 par personne de 14 ans ou plus, 0,3 par enfant.
  // Un couple avec deux jeunes enfants compte 2,1 UC.
  $: pop = serie('POP')
  $: logements = serie('DWELLINGS')
  $: principales = serie('DWELLINGS_DW_MAIN')
  $: secondaires = serie('DWELLINGS_DW_SEC_DW_OCC')
  $: vacants = serie('DWELLINGS_DW_VAC')
  $: anneesLog = logements.map(r => r.annee)

  $: popActuelle = val('POPREF_PMUN') || pop[pop.length - 1]
  $: popMax = pop.reduce((m, r) => Math.max(m, r.valeur), 0)
  $: revenu = val('FILO_MED_SL')
  $: superficie = val('SUP')
  $: actifs = val('EMP_1_Y15T64')

  // Pyramide des âges du dernier recensement disponible.
  const AGES = ['POP_AGE_Y_LT15', 'POP_AGE_Y15T24', 'POP_AGE_Y25T39',
                'POP_AGE_Y40T54', 'POP_AGE_Y55T64', 'POP_AGE_Y65T79', 'POP_AGE_Y_GE80']
  $: anneeAge = insee.filter(r => estCommune(r) && AGES.includes(r.indicateur))
                     .reduce((mx, r) => (r.annee || '') > mx ? r.annee : mx, '')
  $: ages = AGES.map(c => {
    const r = insee.find(x => estCommune(x) && x.indicateur === c && x.annee === anneeAge)
    return { code: c, label: LABELS[c], valeur: r?.valeur ?? 0 }
  })
  $: ageTotal = ages.reduce((s, a) => s + a.valeur, 0)
  $: ageMax = Math.max(...ages.map(a => a.valeur), 1)

  // La part de résidences secondaires est mise en avant plutôt que noyée dans
  // le tableau : c'est le chiffre qui distingue une commune habitée à l'année
  // d'une commune de villégiature.
  $: partSecondaires = (r) => {
    const tot = logements.find(l => l.annee === r.annee)?.valeur
    return tot ? (r.valeur / tot) * 100 : null
  }
  $: dernierLog = logements[logements.length - 1]
  $: dernierSec = secondaires[secondaires.length - 1]
  $: dernierVac = vacants[vacants.length - 1]

  // Le niveau de vie est publié pour chaque commune de l'intercommunalité : la
  // comparaison situe la commune sans avoir à la chercher ailleurs. La liste
  // vient du serveur, où le nom de commune existe encore.
  $: voisinesMax = Math.max(...voisines.map(v => v.valeur), 1)

  const nb = (v, d = 0) => v == null ? '—'
    : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: d }).format(v)
  const eur = (v) => v == null ? '—'
    : new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(v)
  const pct = (v) => v == null ? '—' : `${v.toFixed(1).replace('.', ',')} %`
</script>

<svelte:head>
  <title>Le territoire en chiffres — {SITE_NOM}</title>
  <meta name="description" content="Population, logement, revenus et emploi {COMMUNE_A} — portrait statistique de la commune à partir des recensements INSEE." />
</svelte:head>

<section>
  <h1 class="avec-icone"><Icon name="territoire" size={26} />Le territoire en chiffres</h1>
  <p class="sub">
    Population, logement, revenus et emploi depuis 1968. Ces chiffres donnent
    l'échelle : un budget, une subvention ou un prix au m² ne se lisent pas sans
    savoir combien de personnes vivent ici, et depuis quand.
  </p>



  {#if constat}
    <Niveau type="calcul" base="les recensements INSEE de {constat.premier.annee} à {constat.dernier.annee}">
      {COMMUNE} comptait <b>{nb(constat.premier.valeur)}</b> habitants
      en {constat.premier.annee} et <b>{nb(constat.dernier.valeur)}</b> en
      {constat.dernier.annee}
      {#if constat.regime === 'stable'}
        — le même nombre à {Math.abs(constat.ecart)} près{#if constat.creuxInterne}, après un creux à
        {nb(constat.creux.valeur)} habitants en {constat.creux.annee}. La commune a donc regagné
        <b>{constat.reprise} %</b> depuis son point bas{/if}.
      {:else if constat.regime === 'baisse'}
        — <b>{Math.abs(constat.ecartTotal)} % de moins</b>, et son point bas est
        l'année la plus récente&nbsp;: la baisse n'est pas enrayée.
      {:else if constat.regime === 'reprise'}
        — <b>{Math.abs(constat.ecartTotal)} % de moins</b> qu'au départ, mais
        <b>{constat.reprise} % de plus</b> qu'au creux de {constat.creux.annee}
        ({nb(constat.creux.valeur)} habitants)&nbsp;: la population remonte sans avoir
        retrouvé son niveau de {constat.premier.annee}.
      {:else}
        — <b>{constat.ecartTotal} % de plus</b>{#if constat.creuxInterne}, après un creux à
        {nb(constat.creux.valeur)} habitants en {constat.creux.annee}{/if}.
      {/if}
    </Niveau>
    <p class="lecture">
      <b>Ce que ce chiffre ne dit pas.</b> Une population stable en nombre peut
      avoir entièrement changé de composition&nbsp;: le recensement compte des
      habitants, il ne dit pas s'il s'agit des mêmes familles, ni d'où viennent
      les nouveaux arrivants. La part des résidences secondaires, plus bas,
      éclaire une autre facette de la même question.
    </p>
  {/if}

  {#if aQuelqueChose}
    <div class="tiles">
      {#if popActuelle}
        <div class="tile">
          <span class="tval">{nb(popActuelle.valeur)}</span>
          <span class="tlabel">habitants ({popActuelle.annee})</span>
        </div>
      {/if}
      {#if superficie}
        <div class="tile">
          {#if popActuelle}
            <span class="tval">{nb(popActuelle.valeur / superficie.valeur, 1)}</span>
            <span class="tlabel">hab./km² · {nb(superficie.valeur, 1)} km²</span>
          {:else}
            <span class="tval">{nb(superficie.valeur, 1)}</span>
            <span class="tlabel">km²</span>
          {/if}
        </div>
      {/if}
      {#if revenu}
        <div class="tile" title="Revenu disponible du ménage rapporté à sa composition (unité de consommation), et non revenu par personne.">
          <span class="tval">{eur(revenu.valeur)}</span>
          <span class="tlabel">niveau de vie médian par UC ({revenu.annee})</span>
        </div>
      {/if}
      {#if dernierSec && dernierLog}
        <div class="tile">
          <span class="tval">{pct((dernierSec.valeur / dernierLog.valeur) * 100)}</span>
          <span class="tlabel">de résidences secondaires</span>
        </div>
      {/if}
      {#if dernierVac && dernierLog}
        <div class="tile" title="Recensement : tout logement inoccupé au 1er janvier, quelle que soit la durée de la vacance.">
          <span class="tval">{pct((dernierVac.valeur / dernierLog.valeur) * 100)}</span>
          <span class="tlabel">de logements vacants ({dernierVac.annee})</span>
        </div>
      {/if}
      {#if actifs}
        <div class="tile">
          <span class="tval">{nb(actifs.valeur)}</span>
          <span class="tlabel">actifs occupés ({actifs.annee})</span>
        </div>
      {/if}
    </div>

    {#if pop.length}
    <h2>
      {#if !constat}Population au recensement
      {:else if constat.regime === 'stable'}Une population stable depuis {constat.premier.annee}
      {:else if constat.regime === 'baisse'}Une population en recul depuis {constat.premier.annee}
      {:else if constat.regime === 'reprise'}Une population qui remonte depuis {constat.creux.annee}
      {:else}Une population en hausse depuis {constat.premier.annee}{/if}
    </h2>
    <p class="note">
      Population au recensement, de {pop[0]?.annee} à {pop[pop.length - 1]?.annee}.
      {#if constat && constat.creuxInterne}Le point bas date de {constat.creux.annee}
      ({nb(constat.creux.valeur)} habitants).{/if}
      Survolez une barre pour le détail.
    </p>
    <div class="chart-wrap">
      <div class="chart pop">
        {#each pop as p}
          <div class="slot" title="{p.annee} : {nb(p.valeur)} habitants">
            <div class="bar" style="height:{(p.valeur / popMax) * 100}%"></div>
            <span class="year">{p.annee}</span>
          </div>
        {/each}
      </div>
    </div>

    {:else}
      <h2>Population</h2>
      <p class="note">La série historique des recensements n'a pas été collectée
         pour cette commune. Les autres indicateurs ci-dessous, eux, l'ont été.</p>
    {/if}

    {#if logements.length}
    <!-- ── Logement ─────────────────────────────────────────────────── -->
    <h2>Logement : la part des résidences secondaires</h2>
    <p class="note">
      Répartition du parc de logements à chaque recensement. La part des
      résidences secondaires conditionne l'école, les commerces ouverts à
      l'année et la pression sur le foncier.
    </p>
    <div class="chart-wrap">
      <table>
        <thead>
          <tr>
            <th>Année</th><th class="r">Logements</th>
            <th class="r">Principales</th><th class="r">Secondaires</th>
            <th class="r">Vacants</th><th>Répartition</th>
          </tr>
        </thead>
        <tbody>
          {#each anneesLog as a}
            {@const tot = logements.find(r => r.annee === a)?.valeur}
            {@const pr = principales.find(r => r.annee === a)?.valeur ?? 0}
            {@const se = secondaires.find(r => r.annee === a)?.valeur ?? 0}
            {@const va = vacants.find(r => r.annee === a)?.valeur ?? 0}
            <tr>
              <td>{a}</td>
              <td class="r">{nb(tot)}</td>
              <td class="r">{nb(pr)}</td>
              <td class="r">{nb(se)} <span class="muted">({pct(tot ? se / tot * 100 : null)})</span></td>
              <td class="r">{nb(va)} <span class="muted">({pct(tot ? va / tot * 100 : null)})</span></td>
              <td>
                <div class="stack" title="Principales {nb(pr)} · Secondaires {nb(se)} · Vacants {nb(va)}">
                  <span class="s1" style="width:{tot ? pr / tot * 100 : 0}%"></span>
                  <span class="s2" style="width:{tot ? se / tot * 100 : 0}%"></span>
                  <span class="s3" style="width:{tot ? va / tot * 100 : 0}%"></span>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="legend">
      <span><i class="s1"></i> Résidences principales</span>
      <span><i class="s2"></i> Résidences secondaires</span>
      <span><i class="s3"></i> Logements vacants</span>
    </p>
    <p class="lecture">
      <b>Ce que « vacant » recouvre ici.</b> Le recensement compte tout logement
      inoccupé au 1<sup>er</sup> janvier, sans distinguer la durée&nbsp;: un bien
      entre deux locataires y figure comme un logement fermé depuis dix ans. La
      <b>vacance de plus de deux ans</b>, celle qui pèse vraiment sur le
      logement d'une commune, est mesurée par le fichier LOVAC du Cerema, dont
      la diffusion est soumise à convention parce qu'il désigne des logements et
      leurs propriétaires&nbsp;: elle n'est pas publiée ici.
    </p>
    {/if}

    <!-- ── Âges ─────────────────────────────────────────────────────── -->
    {#if ageTotal > 0}
      <h2>Structure par âge ({anneeAge})</h2>
      <div class="ages">
        {#each ages as a}
          <div class="agerow">
            <span class="alabel">{a.label}</span>
            <div class="abar"><span style="width:{(a.valeur / ageMax) * 100}%"></span></div>
            <span class="aval">{nb(a.valeur)} <em>{pct((a.valeur / ageTotal) * 100)}</em></span>
          </div>
        {/each}
      </div>
    {/if}

    {#if voisines.length > 1}
      <h2>Niveau de vie dans l'intercommunalité</h2>
      <p class="note">
        Niveau de vie médian par commune ({anneeFilo}) : la moitié des habitants
        appartient à un ménage dont le niveau de vie est inférieur à ce montant,
        l'autre moitié supérieur. Ce n'est ni un salaire ni un revenu par
        personne&nbsp;: c'est le revenu disponible du ménage — impôts directs
        déduits, prestations comprises — rapporté à sa composition (1 unité pour
        le premier adulte, 0,5 par personne de 14 ans ou plus, 0,3 par enfant).
      </p>
      <div class="ages">
        {#each voisines as v}
          <div class="agerow">
            <span class="alabel">{v.commune}</span>
            <div class="abar"><span class:me={v.insee === INSEE}
                                    style="width:{(v.valeur / voisinesMax) * 100}%"></span></div>
            <span class="aval">{eur(v.valeur)}</span>
          </div>
        {/each}
      </div>
    {/if}

    <p class="src">
      Source : INSEE — recensements de la population, séries historiques,
      dispositif FiLoSoFi (niveaux de vie), récupérés via l'API Melodi. Le
      niveau de vie médian est publié à l'échelle communale, en euros par an et
      par unité de consommation ; l'INSEE le couvre du secret statistique sur
      les communes les plus petites, qui sont alors absentes de la comparaison.
      La structure par âge porte sur le recensement {anneeAge}.
    </p>
  {:else}
    <p class="muted">Aucun indicateur disponible.</p>
  {/if}

  {#if equipements.etat?.length}
    <h2>Ce qu'il y a sur place</h2>
    <p class="note">Équipements et services recensés dans la commune par la base
      permanente des équipements de l'INSEE{#if equipements.total} — {equipements.total} au total{/if}.</p>
    <div class="chart-wrap">
      <table>
        <thead><tr><th>Équipement ou service</th><th class="r">Nombre</th></tr></thead>
        <tbody>
          {#each equipements.etat as e}
            <tr><td>{e.libelle || e.code}</td><td class="r">{e.nombre}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if mouvements.pertes?.length || mouvements.gains?.length}
      <h3>Ce qui a fermé, ce qui a ouvert</h3>
      <Niveau type="fait" source="INSEE — base permanente des équipements">
        🔴 Cette évolution n'est <b>pas communale</b> : l'INSEE ne publie la série
        qu'à partir de l'intercommunalité. Elle porte sur
        {equipements.epciNom || "l'intercommunalité"}, entre {mouvements.debut} et {mouvements.fin}.
      </Niveau>
      <div class="chart-wrap">
        <table>
          <thead><tr><th>Équipement</th><th class="r">{mouvements.debut}</th><th class="r">{mouvements.fin}</th><th class="r">Écart</th></tr></thead>
          <tbody>
            {#each [...(mouvements.pertes || []), ...(mouvements.gains || [])] as m}
              <tr>
                <td>{m.libelle || m.code}</td>
                <td class="r">{m.debut}</td><td class="r">{m.fin}</td>
                <td class="r" class:perte={m.ecart < 0}>{m.ecart > 0 ? '+' : ''}{m.ecart}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}

  {#if mobilite.aom || dispositifs.length}
    <h2>Desserte et dispositifs de l'État</h2>
    {#if mobilite.aom}
      <Niveau type="fait" source="transport.data.gouv.fr">
        L'autorité qui organise les transports ici est <b>{mobilite.aom.nom}</b>
        ({mobilite.aom.forme}, SIREN {mobilite.aom.siren}).
        {#if mobilite.arrets}Les réseaux déclarent <b>{mobilite.arrets}</b> arrêt(s)
          dans la commune{#if mobilite.horsCommune} ({mobilite.horsCommune} autres
          tombent dans le rectangle interrogé mais hors des limites communales,
          et ne sont pas comptés){/if}.{:else}<b>Aucun arrêt</b> n'est déclaré
          dans la commune par les fichiers horaires publiés.{/if}
      </Niveau>
      {#if mobilite.reseaux?.length}
        <ul class="liste">
          {#each mobilite.reseaux as r}<li>{r.reseau} — {r.n} arrêt(s)</li>{/each}
        </ul>
      {/if}
    {/if}
    {#if dispositifs.length}
      <p class="note">Programmes nationaux dont la commune bénéficie, d'après la
        table de croisement de l'Agence nationale de la cohésion des territoires.</p>
      <ul class="liste">
        {#each dispositifs as d}<li>{d.libelle || d.code}<span class="muted"> — {d.reference}</span></li>{/each}
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

  section { max-width: 950px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  h1 { margin: 0 0 .25rem; }
  h2 { margin: 2.2rem 0 .3rem; font-size: 1.2rem; }
  .sub { color: var(--gris); margin: 0 0 1.2rem; max-width: 70ch; }
  .note { color: var(--gris); font-size: .84rem; max-width: 72ch; margin: .2rem 0 .9rem; }
  .muted { color: var(--gris); font-size: .85rem; }

  .tiles { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 1.6rem; }
  .tile { background: var(--papier); border: 1px solid var(--trait); border-radius: 10px;
          padding: .6rem .9rem; display: flex; flex-direction: column; min-width: 9rem; }
  .tval { font-size: 1.2rem; font-weight: 600; }
  .tlabel { font-size: .72rem; color: var(--gris); text-transform: uppercase; letter-spacing: .03em; }

  .chart-wrap { overflow-x: auto; }
  .chart.pop { display: flex; gap: .5rem; align-items: flex-end;
               height: 170px; min-width: 480px; margin-bottom: .5rem; }
  .chart.pop .slot { flex: 1; height: 100%; display: flex; flex-direction: column;
                     justify-content: flex-end; align-items: center; }
  .chart.pop .bar { width: 100%; max-width: 42px; background: var(--ardoise);
                    border-radius: 3px 3px 0 0; }
  .chart.pop .year { font-size: .68rem; color: var(--gris-clair); margin-top: .25rem; }

  table { width: 100%; border-collapse: collapse; font-size: .88rem; min-width: 620px; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--trait); }
  th { color: var(--gris); font-weight: 500; }
  .r { text-align: right; }
  td .muted { font-size: .78rem; }

  h3 { margin: 1.4rem 0 .3rem; font-size: 1rem; }
  .liste { margin: .4rem 0 1rem; padding-left: 1.1rem; font-size: .9rem; line-height: 1.7; }
  .perte { color: var(--brique, #b8341f); font-weight: 600; }

  .stack { display: flex; height: 10px; border-radius: 3px; overflow: hidden; min-width: 120px; }
  .stack span { display: block; height: 100%; }
  .s1, i.s1 { background: var(--ardoise); } .s2, i.s2 { background: var(--ambre); } .s3, i.s3 { background: var(--trait); }
  .legend { display: flex; gap: 1.2rem; flex-wrap: wrap; font-size: .78rem;
            color: var(--gris); margin-top: .5rem; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
              margin-right: .3rem; vertical-align: middle; }

  .ages { margin-top: .6rem; }
  .agerow { display: grid; grid-template-columns: 10rem 1fr 7rem; gap: .7rem;
            align-items: center; padding: .18rem 0; font-size: .86rem; }
  .alabel { color: var(--gris); }
  .abar { background: var(--trait-pale); border-radius: 3px; height: 14px; }
  .abar span { display: block; height: 100%; background: var(--ardoise); border-radius: 3px; }
  .abar span.me { background: var(--ardoise-fonce); }
  .aval { text-align: right; color: var(--gris); }
  .aval em { color: var(--gris-clair); font-style: normal; font-size: .78rem; }

  .src { margin-top: 2rem; padding-top: .8rem; border-top: 1px solid var(--trait);
         color: var(--gris); font-size: .8rem; max-width: 72ch; }

  @media (max-width: 700px) {
    .agerow { grid-template-columns: 7.5rem 1fr 5.5rem; font-size: .8rem; }
  }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
