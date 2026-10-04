<script>
  import { COMMUNE, COMMUNE_A, INSEE, SITE_NOM } from '$lib/instance.js'
  import VersDossier from '$lib/components/VersDossier.svelte'
  import Icon from '$lib/components/Icon.svelte'
  import Niveau from '$lib/components/Niveau.svelte'

  // Eau, risques naturels et installations classées. 27 652 analyses, 75 risques
  // recensés et 3 ICPE étaient en base depuis des mois sans aucune page publique.

  // Rendu au build par +page.server.js.
  export let data
  $: ({ stations, series, couverture, risques, icpe, catnat,
        servicesEau, indicateursEau } = data)
  $: dpe = data.dpe
  $: controleEau = data.controleEau
  $: dechets = data.dechets
  $: incendie = data.incendie

  // ── Les déchets ────────────────────────────────────────────────────────────
  const DECHETS = {
    omr: 'Ordures ménagères (la poubelle ordinaire)',
    // SINOE compte le verre DANS la collecte séparée : les deux lignes ne
    // s'ajoutent pas, et le total est ordures + collecte séparée + déchèterie.
    tri: 'Collecte séparée (emballages, papiers et verre)',
    papier: '— dont emballages et papiers',
    verre: '— dont verre', decheterie: 'Apports en déchèterie', total: 'Total',
  }
  // Le rang se dit en quarts, pas en « bon » ou « mauvais » : beaucoup de tri
  // est une bonne nouvelle, beaucoup d'ordures résiduelles non. La page situe,
  // elle ne note pas.
  const QUARTS = ['', 'dans le quart le plus bas', 'sous la médiane',
                  'au-dessus de la médiane', 'dans le quart le plus élevé']
  const kg = (v) => v == null ? '—' : `${Math.round(v)} kg`
  // Un syndicat départemental en tient des dizaines : au-delà de ce seuil, la
  // page ne nomme que celles de la commune et compte les autres.
  const DECHETERIES_MAX = 8
  const tonnes = (v) => `${nb(Math.round(v))} t`
  const part = (v, lignes) => {
    const total = lignes.reduce((s, l) => s + l.tonnes, 0)
    return total ? `${Math.round(100 * v / total)} %` : ''
  }

  // ── La forêt et le feu ─────────────────────────────────────────────────────
  // Un feu de 12 m² et un feu de 50 ha ne se lisent pas dans la même unité :
  // « 0,0012 ha » ne dit rien à personne.
  const surface = (ha) => ha == null ? '—'
    : ha < 1 ? `${nb(Math.round(ha * 10000))} m²` : `${nb(ha)} ha`
  const fmtAlerte = (a) => a ? fmtDate(a.slice(0, 10)) : '—'
  let parametre = 'Nitrates'

  // ── L'eau du robinet ───────────────────────────────────────────────────────
  // Un service par ligne, avec sa série de prix. Deux services peuvent
  // desservir la même commune à des prix différents : afficher « le prix de
  // l'eau » serait un chiffre juste sous un cadre faux.
  const valeurs = (service, code) => indicateursEau
    .filter(i => i.code_service === service && i.code === code && i.valeur != null)
    .sort((a, b) => a.annee - b.annee)
  const derniere = (service, code) => valeurs(service, code).at(-1) || null

  $: eauPotable = servicesEau
    .filter(s => s.competence === 'AEP')
    .map(s => {
      const prix = valeurs(s.code_service, 'D102.0')
      const premier = prix[0]
      const dernier = prix.at(-1)
      return {
        ...s,
        prix,
        dernier,
        // L'évolution ne se calcule que sur DEUX exercices distincts : sur un
        // seul, « + 0 % » se lirait comme une stabilité constatée.
        evolution: premier && dernier && premier.annee !== dernier.annee
          ? { depuis: premier.annee, jusqu: dernier.annee,
              pourcent: ((dernier.valeur - premier.valeur) / premier.valeur) * 100 }
          : null,
        rendement: derniere(s.code_service, 'P104.3'),
        renouvellement: derniere(s.code_service, 'P107.2'),
        conformite: derniere(s.code_service, 'P101.1'),
        nbCommunes: (s.communes || '').split(',').filter(Boolean).length,
      }
    })
    .sort((a, b) => (b.dernier?.annee ?? 0) - (a.dernier?.annee ?? 0))
  $: assainissement = servicesEau
    .filter(s => s.competence === 'AC')
    .map(s => ({ ...s, dernier: derniere(s.code_service, 'D204.0') }))
    .filter(s => s.dernier)
  $: anneesPrix = [...new Set(eauPotable.flatMap(s => s.prix.map(p => p.annee)))].sort()
  const euros = (v) => v == null ? '—'
    : new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + ' €'

  $: parametres = [...new Set(series.map(s => s.parametre))].sort()
  $: serie = series.filter(s => s.parametre === parametre)
  $: unite = serie[0]?.unite || ''
  $: annees = [...new Set(serie.map(s => s.annee))].sort()
  $: parStation = [...new Set(serie.map(s => s.station))].sort().map(st => ({
    station: st,
    points: annees.map(a => serie.find(s => s.station === st && s.annee === a) || null),
  }))
  $: maxi = Math.max(...serie.map(s => s.maxi ?? 0), 0.0001)

  // Risques regroupés par intitulé : le même aléa vaut souvent pour plusieurs
  // communes du secteur, l'afficher une fois par commune n'apprend rien.
  $: risquesParType = Object.entries(
    risques.reduce((acc, r) => {
      (acc[r.libelle] ||= []).push(r.commune)
      return acc
    }, {})
  ).sort((a, b) => b[1].length - a[1].length)

  $: derniereAnalyse = series.reduce(
    (mx, s) => (s.dernier_prelevement || '') > mx ? s.dernier_prelevement : mx, '')
  $: totalAnalyses = couverture.reduce((s, c) => s + (c.analyses || 0), 0)
  // « 91 621 analyses d'eau » se lisait comme l'eau du robinet d'ici. Ce sont
  // des analyses de cours d'eau et de captages, sur seize ans, aux stations des
  // communes suivies — et aucune n'est à Lasalle. Le compteur dit donc sa
  // période, son objet et son périmètre au point de lecture.
  $: anneesAnalyses = couverture.map(c => c.annee).filter(Boolean).sort()
  $: periodeAnalyses = anneesAnalyses.length
    ? (anneesAnalyses[0] === anneesAnalyses.at(-1) ? anneesAnalyses[0]
       : `${anneesAnalyses[0]}–${anneesAnalyses.at(-1)}`) : ''
  $: communesStations = new Set(stations.map(s => s.code_commune).filter(Boolean))
  $: stationsIci = stations.filter(s => s.code_commune === INSEE).length
  // Les stations sont celles du BASSIN déclaré par l'instance — les cours d'eau
  // qui traversent la commune ou la reçoivent en aval —, pas celles des
  // communes voisines prises au hasard du périmètre administratif.
  $: coursSuivis = [...new Set(stations.map(s => (s.cours_eau || '').trim()).filter(Boolean))]
  $: catnatRecents = catnat.slice(0, 8)

  const fmtDate = (d) => d
    ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' })
    : '—'
  const nb = (v) => v == null ? '—' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(v)
</script>

<svelte:head>
  <title>Environnement — {SITE_NOM}</title>
  <meta name="description" content="Prix et contrôle sanitaire de l'eau potable, qualité des cours d'eau, forêt et feux, déchets ménagers, risques naturels recensés et installations classées {COMMUNE_A} et dans son intercommunalité." />
</svelte:head>

<section>
  <h1 class="avec-icone"><Icon name="environnement" size={26} />Environnement</h1>
  <p class="sub">
    Prix et contrôle sanitaire de l'eau potable, qualité des cours d'eau,
    risques naturels recensés, forêt et feux, installations classées, déchets
    ménagers. Données issues des registres publics (SISPEA, Hub'Eau,
    Géorisques, IGN, ADEME).
  </p>



  {#if stations.length || risques.length || icpe.length || eauPotable.length
       || controleEau || dechets || incendie}
    <div class="tiles">
      <div class="tile"><span class="tval">{nb(totalAnalyses)}</span><span class="tlabel">analyses de cours d'eau et captages{#if periodeAnalyses}, {periodeAnalyses}{/if}</span></div>
      <div class="tile"><span class="tval">{stations.length}</span><span class="tlabel">stations de mesure, dans {communesStations.size} commune{communesStations.size > 1 ? 's' : ''}</span></div>
      <div class="tile"><span class="tval">{risquesParType.length}</span><span class="tlabel">types de risque</span></div>
      <div class="tile"><span class="tval">{catnat.length}</span><span class="tlabel">arrêtés catastrophe naturelle</span></div>
      {#if derniereAnalyse}
        <div class="tile"><span class="tval">{fmtDate(derniereAnalyse)}</span><span class="tlabel">dernier prélèvement</span></div>
      {/if}
    </div>
    {#if stations.length}
      <p class="note">
        Les analyses sont celles des stations de surveillance des rivières et
        des captages (Naïades), pas celles de l'eau distribuée au robinet —
        qui a sa propre section ci-dessous.
        {#if coursSuivis.length}Cours d'eau suivis&nbsp;: {coursSuivis.join(', ')}.{/if}
        {#if stationsIci}{stationsIci} station{stationsIci > 1 ? 's sont' : ' est'} {COMMUNE_A}&nbsp;;
        les autres sont en amont ou en aval.
        {:else}Aucune station n'est {COMMUNE_A}&nbsp;: toutes sont en amont
        ou en aval, et leurs mesures décrivent le bassin, pas la commune.{/if}
      </p>
    {/if}

    <!-- ── L'eau du robinet ─────────────────────────────────────────── -->
    {#if eauPotable.length || controleEau}
      <h2 id="eau-du-robinet">L'eau du robinet</h2>
      <VersDossier dossier={data.dossiers?.["eau-du-robinet"]} />
    {/if}
    {#if eauPotable.length}
      <p class="note">
        Ce que coûte le mètre cube, et l'état du réseau qui l'apporte. Ces chiffres
        viennent de l'observatoire national des services d'eau (SISPEA), alimenté
        par les services eux-mêmes. Ils portent sur un EXERCICE : le dernier
        publié, jamais le prix d'aujourd'hui.
      </p>

      {#each eauPotable as s}
        <h3>
          {s.nom || s.libelle || `Service n° ${s.code_service}`}
          {#if s.mode_gestion}<span class="muted"> — {s.mode_gestion}</span>{/if}
        </h3>
        <p class="note">
          {#if s.type_collectivite}{s.type_collectivite}{/if}{#if s.nbCommunes > 1}, {s.nbCommunes} communes desservies{/if}{#if s.siren} <span class="muted">· SIREN {s.siren}</span>{/if}
        </p>
        <div class="tiles">
          {#if s.dernier}
            <div class="tile">
              <span class="tval">{euros(s.dernier.valeur)}</span>
              <span class="tlabel">le m³ TTC en {s.dernier.annee} (facture de 120 m³)</span>
            </div>
          {/if}
          {#if s.evolution}
            <div class="tile">
              <span class="tval">{s.evolution.pourcent >= 0 ? '+' : ''}{nb(s.evolution.pourcent)} %</span>
              <span class="tlabel">entre {s.evolution.depuis} et {s.evolution.jusqu}</span>
            </div>
          {/if}
          {#if s.rendement}
            <div class="tile">
              <span class="tval">{nb(s.rendement.valeur)} %</span>
              <span class="tlabel">rendement du réseau ({s.rendement.annee})</span>
            </div>
          {/if}
          {#if s.renouvellement}
            <div class="tile">
              <span class="tval">{nb(s.renouvellement.valeur)} %</span>
              <span class="tlabel">réseau renouvelé dans l'année ({s.renouvellement.annee})</span>
            </div>
          {/if}
          {#if s.conformite}
            <div class="tile">
              <span class="tval">{nb(s.conformite.valeur)} %</span>
              <span class="tlabel">conformité microbiologique ({s.conformite.annee})</span>
            </div>
          {/if}
        </div>
      {/each}

      {#if anneesPrix.length > 1}
        <h3>Le prix du mètre cube, exercice par exercice</h3>
        <table>
          <thead>
            <tr><th>Exercice</th>{#each eauPotable as s}<th class="r">{s.nom || s.libelle}</th>{/each}</tr>
          </thead>
          <tbody>
            {#each anneesPrix as a}
              <tr>
                <td>{a}</td>
                {#each eauPotable as s}
                  <td class="r">{euros(s.prix.find(p => p.annee === a)?.valeur)}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="note">
          Une case vide signifie que le service n'a rien déclaré cette année-là :
          l'observatoire est déclaratif, et un exercice manquant ne dit rien du prix
          pratiqué alors.
        </p>
      {/if}

      {#if assainissement.length}
        <h3>Assainissement collectif</h3>
        <p class="note">
          La facture d'eau additionne les deux services. Le prix ci-dessus ne porte
          que sur l'eau potable.
        </p>
        <ul class="plain">
          {#each assainissement as s}
            <li><strong>{euros(s.dernier.valeur)} le m³</strong> en {s.dernier.annee}
              <span class="muted">— {s.nom || s.libelle || `service n° ${s.code_service}`}</span></li>
          {/each}
        </ul>
      {/if}
    {/if}

    <!-- ── Le contrôle sanitaire (ARS) ──────────────────────────────── -->
    {#if controleEau}
      <h3 id="controle-sanitaire">Ce qui sort du robinet : le contrôle sanitaire</h3>
      <Niveau type="fait" source="Agence régionale de santé, via Hub'Eau — qualité de l'eau potable">
        {#if controleEau.reseaux.length > 1}
          L'eau n'arrive pas partout par le même réseau&nbsp;:
          <b>{controleEau.reseaux.length} réseaux</b> desservent {COMMUNE} en
          {controleEau.annee_desserte}, chacun avec son responsable. L'agence
          régionale de santé prélève sur chacun.
        {:else}
          Un réseau dessert {COMMUNE} en {controleEau.annee_desserte}. L'agence
          régionale de santé y prélève tout au long de l'année.
        {/if}
      </Niveau>
      <table>
        <thead>
          <tr><th>Réseau</th><th class="r">Prélèvements</th>
            <th class="r">Hors limites<br>bactériologie</th>
            <th class="r">Hors limites<br>chimie</th><th>Dernier hors limites</th></tr>
        </thead>
        <tbody>
          {#each controleEau.reseaux as r}
            <tr>
              <td>
                <strong>{r.nom || `Réseau ${r.code}`}</strong>
                {#if r.quartiers.length}<span class="sub2">{r.quartiers.join(', ')}</span>{/if}
                {#if r.maitre_ouvrage}<span class="sub2">Responsable&nbsp;: {r.maitre_ouvrage}{#if r.exploitant && r.exploitant !== r.maitre_ouvrage}{' '}· exploitant&nbsp;: {r.exploitant}{/if}</span>{/if}
              </td>
              {#if r.prelevements}
                <td class="r">{r.prelevements}<span class="sub2">{r.du.slice(0, 4)}–{r.au.slice(0, 4)}</span></td>
                <td class="r">{r.bacteriologie}</td>
                <td class="r">{r.chimie}</td>
                <td>{r.hors_limites.length ? fmtDate(r.hors_limites[0].date) : 'aucun'}</td>
              {:else}
                <!-- Un réseau sans prélèvement publié n'est pas un réseau conforme. -->
                <td colspan="4" class="muted">Aucun prélèvement publié pour ce réseau — ce qui ne dit rien de son eau.</td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="note">
        «&nbsp;Hors limites&nbsp;»&nbsp;: le prélèvement dépasse une <b>limite de
        qualité</b>, le seuil que l'eau doit respecter (bactéries d'origine
        fécale, nitrates, pesticides…). Un dépassement ne vaut pas interdiction de
        boire&nbsp;: c'est l'agence régionale de santé qui en juge, cas par cas.
        Les écarts aux <b>références de qualité</b> — des témoins du bon
        fonctionnement des installations, sans effet direct sur la santé — ne
        sont pas comptés dans ce tableau. Un même prélèvement peut valoir pour
        plusieurs réseaux&nbsp;: les colonnes ne s'additionnent pas.
      </p>
      {#each controleEau.reseaux.filter(r => r.hors_limites.length) as r}
        <details class="plus">
          <summary>{r.nom || r.code}&nbsp;: année par année</summary>
          <table>
            <thead><tr><th>Année</th><th class="r">Prélèvements</th>
              <th class="r">Hors limites bactériologie</th><th class="r">Hors limites chimie</th></tr></thead>
            <tbody>
              {#each r.par_annee as a}
                <tr><td>{a.annee}</td><td class="r">{a.prelevements}</td>
                  <td class="r">{a.bacteriologie || '—'}</td><td class="r">{a.chimie || '—'}</td></tr>
              {/each}
            </tbody>
          </table>
        </details>
      {/each}
    {/if}

    <!-- ── Qualité de l'eau ─────────────────────────────────────────── -->
    <h2>Qualité des cours d'eau</h2>
    <p class="note">
      Moyenne annuelle par station. Le suivi porte sur près de 800 paramètres ;
      ceux présentés ici sont les indicateurs interprétables sans expertise.
      La barre indique la moyenne, le trait fin l'étendue min–max de l'année.
    </p>

    <div class="chips">
      {#each parametres as p}
        <button class:on={parametre === p} on:click={() => parametre = p}>{p}</button>
      {/each}
    </div>

    {#if serie.length}
      <div class="chart-wrap">
        <div class="chart">
          {#each parStation as row}
            <div class="row">
              <span class="rlabel">{row.station}</span>
              <div class="bars">
                {#each row.points as pt, i}
                  <div class="slot" title={pt
                      ? `${annees[i]} — moyenne ${nb(pt.moyenne)} ${unite} (min ${nb(pt.mini)}, max ${nb(pt.maxi)}, ${pt.n} mesures)`
                      : `${annees[i]} — aucune mesure`}>
                    {#if pt}
                      <div class="range" style="height:{Math.max(2, (pt.maxi / maxi) * 100)}%"></div>
                      <div class="bar" style="height:{Math.max(2, (pt.moyenne / maxi) * 100)}%"></div>
                    {/if}
                    <span class="year">{annees[i].slice(2)}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/each}
        </div>
        <p class="axis">Échelle commune : 0 → {nb(maxi)} {unite}</p>
      </div>
    {:else}
      <p class="muted">Aucune mesure pour ce paramètre.</p>
    {/if}

    {#if couverture.length}
      <h3>Étendue de la surveillance</h3>
      <table>
        <thead><tr><th>Année</th><th class="r">Analyses</th><th class="r">Paramètres recherchés</th><th class="r">Détectés</th></tr></thead>
        <tbody>
          {#each couverture as c}
            <tr>
              <td>{c.annee}</td>
              <td class="r">{nb(c.analyses)}</td>
              <td class="r">{nb(c.parametres_recherches)}</td>
              <td class="r">{nb(c.parametres_detectes)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="note">
        « Détecté » signifie que le paramètre a été quantifié au-dessus du seuil de
        détection du laboratoire — pas qu'un seuil réglementaire est dépassé.
      </p>
    {/if}

    <h3>Stations de mesure</h3>
    <ul class="plain">
      {#each stations as s}
        <li><strong>{s.libelle.trim()}</strong>{#if s.cours_eau} — {s.cours_eau}{/if} <span class="muted">({s.code_station})</span></li>
      {/each}
    </ul>

    <!-- ── Risques ──────────────────────────────────────────────────── -->
    <h2>Risques naturels et technologiques recensés</h2>
    <p class="note">Recensement Géorisques, par type d'aléa et communes concernées.</p>
    <ul class="risques">
      {#each risquesParType as [libelle, communes]}
        <li>
          <span class="rl">{libelle}</span>
          <span class="rc">{[...new Set(communes)].sort().join(' · ')}</span>
        </li>
      {/each}
    </ul>

    {#if catnatRecents.length}
      <h3>Arrêtés de catastrophe naturelle</h3>
      <ul class="plain">
        {#each catnatRecents as c}
          <li>
            <span class="date">{fmtDate(c.date)}</span> {c.title}
            {#if c.source_url}<a href={c.source_url} target="_blank" rel="noopener">source ↗</a>{/if}
          </li>
        {/each}
      </ul>
      {#if catnat.length > catnatRecents.length}
        <p class="note">{catnat.length} arrêtés au total depuis 1982.</p>
      {/if}
    {/if}

    <!-- ── La forêt et le feu ───────────────────────────────────────── -->
    {#if incendie}
      <h2 id="foret-et-feu">La forêt et le feu</h2>
      <VersDossier dossier={data.dossiers?.["foret-et-feu"]} />
      {#if incendie.boisement}
        {@const b = incendie.boisement}
        <Niveau type="fait" source="IGN — Observatoire des forêts, prises de vue de {b.annee_pva}">
          La forêt couvre <b>{nb(b.surface_foret)} des {nb(b.surface_commune)} hectares</b>
          de la commune, soit <b>{nb(b.taux_boisement)}&nbsp;%</b>&nbsp;:
          {nb(b.feuillus)}&nbsp;ha de feuillus, {nb(b.coniferes)}&nbsp;ha de
          conifères, {nb(b.mixtes)}&nbsp;ha de peuplements mêlés.
          {#if incendie.forets_publiques}
            {#if incendie.forets_publiques.length}
              Forêts publiques&nbsp;: {incendie.forets_publiques.map(f => f.nom).join(', ')}.
            {:else}
              Aucune forêt publique n'y est recensée par la BD TOPO.
            {/if}
          {/if}
        </Niveau>
      {/if}

      {#if incendie.debroussaillement}
        {@const d = incendie.debroussaillement}
        <h3>Qui doit débroussailler</h3>
        <Niveau type="calcul" base="les adresses de la Base adresse nationale, placées sur le zonage des obligations légales de débroussaillement (Géoplateforme)">
          {#if d.polygones === 0}
            Aucun zonage d'obligation de débroussaillement n'est publié dans
            l'emprise de la commune.
          {:else if d.dans_zonage === d.adresses}
            <b>Les {nb(d.adresses)} adresses</b> de la commune sont toutes dans
            le périmètre où la loi impose de débroussailler autour des constructions.
          {:else}
            <b>{nb(d.dans_zonage)} des {nb(d.adresses)} adresses</b> de la commune
            sont dans le périmètre où la loi impose de débroussailler autour
            des constructions.
          {/if}
          {#if d.arrete}Zonage arrêté par le préfet le {d.arrete}.{/if}
        </Niveau>
        <p class="note">
          L'obligation pèse sur le propriétaire de la construction, pas sur la
          commune&nbsp;; le maire est chargé de la faire respecter. Ce calcul
          dit où tombent les adresses, pas si les terrains sont débroussaillés.
          {#if d.url}<a href={d.url} target="_blank" rel="noopener">La règle dans le département ↗</a>{/if}
        </p>
      {/if}

      {#if incendie.feux}
        {@const f = incendie.feux}
        <h3>Ce qui a brûlé</h3>
        <Niveau type="fait" source="Base de données sur les incendies de forêts en France (BDIFF), {f.debut}–{f.fin}">
          {#if f.nombre === 0}
            <b>Aucun feu</b> n'est recensé dans la commune de {f.debut} à {f.fin}.
          {:else}
            <b>{f.nombre} feu{f.nombre > 1 ? 'x' : ''}</b> recensé{f.nombre > 1 ? 's' : ''}
            dans la commune de {f.debut} à {f.fin}, pour <b>{surface(f.surface_ha)}</b>
            au total{#if f.nombre > 1}. Le plus grand, le {fmtAlerte(f.plus_grand.alerte)},
            a couvert {surface(f.plus_grand.surface_ha)}{/if}.
          {/if}
        </Niveau>
        {#if f.liste.length}
          <table>
            <thead><tr><th>Alerte</th><th class="r">Surface</th><th class="r">dont forêt</th><th>Cause retenue</th></tr></thead>
            <tbody>
              {#each [...f.liste].reverse() as feu}
                <tr><td>{fmtAlerte(feu.alerte)}</td><td class="r">{surface(feu.surface_ha)}</td>
                  <td class="r">{surface(feu.foret_ha)}</td><td>{feu.cause || 'non renseignée'}</td></tr>
              {/each}
            </tbody>
          </table>
        {/if}
        <p class="note">
          La BDIFF recense les feux que les services de l'État et les pompiers y
          versent&nbsp;; l'année en cours n'y figure qu'après la saison.
        </p>
      {/if}
    {/if}

    <!-- ── ICPE ─────────────────────────────────────────────────────── -->
    {#if icpe.length}
      <h2>Installations classées (ICPE)</h2>
      <table>
        <thead><tr><th>Exploitant</th><th>Commune</th><th>Régime</th><th>État</th></tr></thead>
        <tbody>
          {#each icpe as i}
            <tr>
              <td><strong>{i.raison_sociale}</strong>{#if i.adresse}<span class="sub2">{i.adresse}</span>{/if}</td>
              <td>{i.commune}</td>
              <td>{i.regime || '—'}{#if i.seveso && i.seveso !== 'Non Seveso'}<span class="tag">{i.seveso}</span>{/if}</td>
              <td>{i.etat_activite || '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <!-- ── Les déchets ménagers ─────────────────────────────────────── -->
    {#if dechets}
      <h2 id="dechets">Les déchets ménagers</h2>
      <VersDossier dossier={data.dossiers?.dechets} />
      {#if dechets.acteurs.length > 1}
        <p class="note">
          {dechets.acteurs.length} collectivités se partagent les déchets ici.
          Chacune ne déclare que ce qu'elle prend en charge&nbsp;: un tiret
          signale un service qu'elle n'exerce pas, et leurs totaux ne
          s'additionnent pas — ils ne portent ni sur les mêmes déchets ni sur
          les mêmes habitants.
        </p>
      {/if}
      {#each dechets.acteurs as a}
        {@const dernier = a.serie.at(-1)}
        {@const ici = a.decheteries.filter(d => d.insee === INSEE)}
        {@const montrees = a.decheteries.length > DECHETERIES_MAX ? ici : a.decheteries}
        <Niveau type="fait" source="ADEME — SINOE®, enquête sur la collecte des déchets">
          {#if dechets.acteurs.length > 1}<b>{a.nom}</b> prend en charge une partie
          des déchets ici.{:else}Ici, les déchets sont collectés par <b>{a.nom}</b>.{/if}
          {#if dernier}Tous les chiffres qui suivent portent sur <b>l'ensemble
          de son territoire</b>{#if dernier.population}{' '}({nb(dernier.population)}
          habitants en {dernier.annee}){/if}, pas sur {COMMUNE} seule&nbsp;:
          l'enquête ne descend pas à la commune.{/if}
        </Niveau>

        {#if a.situer?.length}
          <h3>Combien par habitant ({dernier.annee})</h3>
          <table>
            <thead><tr><th>Par habitant et par an</th><th class="r">Ici</th>
              <th class="r">Médiane<br>France</th><th class="r">Médiane<br>département</th>
              <th>Parmi les collectivités de France</th></tr></thead>
            <tbody>
              {#each a.situer as s}
                <tr>
                  <td>{DECHETS[s.indicateur]}</td>
                  <td class="r"><strong>{kg(s.valeur)}</strong></td>
                  <td class="r">{kg(s.france?.p50)}</td>
                  <td class="r">{kg(s.departement?.p50)}</td>
                  <td class="muted">{QUARTS[s.quart] || '—'}{#if s.france?.p95 != null && s.valeur > s.france.p95}, au-delà de 19 collectivités sur 20{/if}</td>
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="note">
            Hors gravats. La médiane est celle des collectivités qui déclarent ce
            service la même année{#if a.situer[0].france}{' '}({nb(a.situer[0].france.collectivites)} en
            France{#if a.situer[0].departement}, {a.situer[0].departement.collectivites} dans le
            département{/if}){/if}.
            {#if /touristique/i.test(dernier.typologie || '')}
              L'ADEME classe ce territoire «&nbsp;{dernier.typologie.toLowerCase()}&nbsp;»&nbsp;:
              les kilos sont divisés par le nombre d'habitants à l'année, alors
              que les déchets des visiteurs et des résidences secondaires y sont
              comptés.
            {/if}
          </p>
        {/if}

        {#if a.serie.length > 1}
          <h3>D'une enquête à l'autre</h3>
          <table>
            <thead><tr><th>Année</th><th class="r">Ordures ménagères</th><th class="r">Collecte séparée</th>
              <th class="r">dont emballages<br>et papiers</th>
              <th class="r">dont verre</th><th class="r">Déchèterie</th><th class="r">Total</th></tr></thead>
            <tbody>
              {#each a.serie as s}
                <tr><td>{s.annee}</td><td class="r">{kg(s.omr)}</td><td class="r">{kg(s.tri)}</td>
                  <td class="r">{kg(s.papier)}</td><td class="r">{kg(s.verre)}</td><td class="r">{kg(s.decheterie)}</td>
                  <td class="r">{kg(s.total)}</td></tr>
              {/each}
            </tbody>
          </table>
          <p class="note">
            Kilos par habitant et par an, hors gravats. L'ADEME n'enquête pas
            tous les ans&nbsp;: une année absente n'est pas une année sans déchets.
          </p>
        {/if}

        {#if a.destinations.lignes.length}
          <h3>Où ils partent ({a.destinations.annee})</h3>
          <ul class="plain">
            {#each a.destinations.lignes as l}
              <li><strong>{tonnes(l.tonnes)}</strong> — {l.libelle}
                <span class="muted">({part(l.tonnes, a.destinations.lignes)})</span></li>
            {/each}
          </ul>
          <p class="note">Tonnes déclarées par la collectivité, gravats compris.</p>
        {/if}

        {#if a.decheteries.length}
          <h3>Les déchèteries</h3>
          {#if montrees.length < a.decheteries.length}
            <p class="note">
              Cette collectivité tient {a.decheteries.length} déchèteries sur
              son territoire{#if ici.length}&nbsp;; seule{ici.length > 1 ? 's' : ''}
              celle{ici.length > 1 ? 's' : ''} {COMMUNE_A} figure{ici.length > 1 ? 'nt' : ''} ici{:else},
              aucune {COMMUNE_A}{/if}.
            </p>
          {/if}
          <ul class="plain">
            {#each montrees as d}
              <li><strong>{d.nom}</strong>{#if d.lieu}{' '}— {d.lieu}{/if}
                <span class="muted">{#if d.ouverte_le}ouverte en {d.ouverte_le.slice(0, 4)}{/if}{#if d.gestion}{' '}· {d.gestion.toLowerCase().replace('regie', 'en régie')}{/if}</span></li>
            {/each}
          </ul>
        {/if}
      {/each}
      <p class="note">
        Ce que la collecte coûte aux habitants est sur la page
        <a href="/impots">Impôts locaux</a> (taxe d'enlèvement des ordures ménagères).
      </p>
    {/if}

    {#if dpe}
      <h2>L'état énergétique des logements</h2>
      <Niveau type="calcul" base="les diagnostics de performance énergétique établis depuis juillet 2021">
        <b>{dpe.partPassoires.toLocaleString('fr-FR')} %</b> des logements diagnostiqués
        sont des passoires thermiques — étiquette F ou G au sens de la loi Climat
        et résilience —, soit {dpe.passoires} sur {dpe.total} diagnostics.
      </Niveau>
      <div class="dpe">
        {#each dpe.etiquettes as e}
          <div class="dpe-col" title="{e.n} diagnostic(s) en {e.lettre}">
            <span class="dpe-n">{e.n || ''}</span>
            <span class="dpe-bar" class:passoire={e.lettre === 'F' || e.lettre === 'G'}
                  style="height:{Math.max(2, 100 * e.n / Math.max(...dpe.etiquettes.map((x) => x.n), 1))}%"></span>
            <span class="dpe-l">{e.lettre}</span>
          </div>
        {/each}
      </div>
      <p class="note">
        Un diagnostic n'est pas un logement : seuls les biens vendus, loués ou
        rénovés depuis juillet 2021 en ont un, et un même logement peut en avoir
        plusieurs. Ces parts décrivent donc le parc DIAGNOSTIQUÉ, pas le parc
        entier.
        {#if dpe.sansCommune}⚠️ {dpe.sansCommune} diagnostic(s) du code postal
          {dpe.codePostal} ne sont rattachés à aucune commune par la base adresse
          nationale : ils ne sont pas comptés ici.{/if}
        {#if dpe.tertiaire}{dpe.tertiaire} diagnostic(s) portent sur des bâtiments
          tertiaires et ne sont pas mêlés à ceux des logements.{/if}
        Les diagnostics d'avant juillet 2021 ne sont pas repris : la réforme a
        changé la méthode de calcul, et les comparer ferait passer un changement
        de règle pour une évolution du parc.
      </p>
    {/if}

    <p class="src">
      Sources : SISPEA (prix et performance de l'eau potable), agences
      régionales de santé via Hub'Eau (contrôle sanitaire de l'eau distribuée),
      Naïades / Hub'Eau (qualité des cours d'eau), Géorisques (risques,
      ICPE, arrêtés CatNat), IGN (boisement, forêts publiques, zonage du
      débroussaillement), BDIFF (feux de forêt), ADEME (SINOE® pour les
      déchets ; diagnostics de performance énergétique,
      agrégés à la commune — aucune adresse n'est collectée). Aucune donnée n'est produite par ce site : tout
      provient des réseaux publics de mesure et de recensement.
    </p>
  {/if}
</section>

<style>
  details.plus { margin: .4rem 0 1rem; font-size: .88rem; }
  details.plus summary { cursor: pointer; color: var(--ardoise-fonce); }

  .dpe { display: flex; align-items: flex-end; gap: .5rem; height: 150px;
         margin: .8rem 0 .4rem; max-width: 460px; }
  .dpe-col { flex: 1; height: 100%; display: flex; flex-direction: column;
             justify-content: flex-end; align-items: center; gap: .2rem; }
  .dpe-bar { width: 100%; background: var(--ardoise); border-radius: 3px 3px 0 0; }
  .dpe-bar.passoire { background: var(--brique, #b8341f); }
  .dpe-n { font-size: .72rem; color: var(--gris); }
  .dpe-l { font-size: .8rem; font-weight: 600; }

  section { max-width: 950px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  h1 { margin: 0 0 .25rem; }
  h2 { margin: 2.2rem 0 .4rem; font-size: 1.25rem; }
  h3 { margin: 1.6rem 0 .4rem; font-size: 1rem; color: var(--gris); }
  .sub { color: var(--gris); margin: 0 0 1.2rem; max-width: 70ch; }
  .note { color: var(--gris); font-size: .84rem; max-width: 72ch; margin: .3rem 0 .8rem; }
  .muted { color: var(--gris); }

  .tiles { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 1.6rem; }
  .tile { background: var(--papier); border: 1px solid var(--trait); border-radius: 10px;
          padding: .6rem .9rem; display: flex; flex-direction: column; min-width: 8rem; }
  .tval { font-size: 1.15rem; font-weight: 600; }
  .tlabel { font-size: .72rem; color: var(--gris); text-transform: uppercase; letter-spacing: .03em; }

  .chips { display: flex; flex-wrap: wrap; gap: .35rem; margin: .8rem 0; }
  .chips button { padding: .28rem .7rem; border: 1px solid var(--trait); border-radius: 99px;
                  background: #fff; color: var(--gris); font-size: .8rem; cursor: pointer; }
  .chips button.on { border-color: var(--ardoise); background: var(--ardoise-pale); color: var(--ardoise-fonce); }

  .chart-wrap { overflow-x: auto; }
  .chart { min-width: 520px; }
  .row { display: grid; grid-template-columns: 15rem 1fr; gap: .8rem;
         align-items: end; margin-bottom: .9rem; }
  .rlabel { font-size: .82rem; color: var(--gris); padding-bottom: 1.2rem; }
  .bars { display: flex; gap: .3rem; align-items: flex-end; height: 90px; }
  .slot { position: relative; flex: 1; height: 100%; display: flex;
          align-items: flex-end; justify-content: center; }
  .range { position: absolute; bottom: 1.1rem; width: 2px; background: #99f6e4; }
  .bar { position: relative; width: 100%; max-width: 26px; background: var(--ardoise);
         border-radius: 2px 2px 0 0; margin-bottom: 1.1rem; }
  .year { position: absolute; bottom: 0; font-size: .65rem; color: var(--gris-clair); }
  .axis { font-size: .75rem; color: var(--gris-clair); margin: .2rem 0 0; }

  table { width: 100%; border-collapse: collapse; font-size: .88rem; margin-top: .4rem; }
  th, td { text-align: left; padding: .45rem .5rem; border-bottom: 1px solid var(--trait); vertical-align: top; }
  th { color: var(--gris); font-weight: 500; }
  .r { text-align: right; }
  .sub2 { display: block; color: var(--gris); font-size: .78rem; }
  .tag { font-size: .68rem; background: #f6e7e5; color: var(--depense);
         padding: .05rem .4rem; border-radius: 99px; margin-left: .3rem; }

  .plain { list-style: none; padding: 0; margin: .3rem 0; }
  .plain li { padding: .3rem 0; border-bottom: 1px solid var(--trait-pale); font-size: .9rem; }
  .plain .date { color: var(--ardoise); font-size: .82rem; margin-right: .5rem; }
  .plain a { font-size: .78rem; color: var(--gris); margin-left: .4rem; }

  .risques { list-style: none; padding: 0; margin: .3rem 0; }
  .risques li { display: grid; grid-template-columns: 1fr 18rem; gap: .8rem;
                padding: .4rem .2rem; border-bottom: 1px solid var(--trait-pale); font-size: .88rem; }
  .risques .rc { color: var(--gris); font-size: .8rem; }

  .src { margin-top: 2rem; padding-top: .8rem; border-top: 1px solid var(--trait);
         color: var(--gris); font-size: .8rem; max-width: 72ch; }

  @media (max-width: 700px) {
    /* Le tableau des installations classées (« En exploitation avec titre »,
       noms d'exploitants) dépassait de 11 px à 390 px : il se coupe. */
    th, td { padding: .4rem .3rem; overflow-wrap: anywhere; hyphens: auto; }
    .row { grid-template-columns: 1fr; }
    .rlabel { padding-bottom: .2rem; }
    .risques li { grid-template-columns: 1fr; }
  }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
