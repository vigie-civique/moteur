<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
  import Niveau from '$lib/components/Niveau.svelte'

  // Eau, risques naturels et installations classées. 27 652 analyses, 75 risques
  // recensés et 3 ICPE étaient en base depuis des mois sans aucune page publique.

  // Rendu au build par +page.server.js.
  export let data
  $: ({ stations, series, couverture, risques, icpe, catnat,
        servicesEau, indicateursEau } = data)
  $: dpe = data.dpe
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
  $: catnatRecents = catnat.slice(0, 8)

  const fmtDate = (d) => d
    ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' })
    : '—'
  const nb = (v) => v == null ? '—' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(v)
</script>

<svelte:head>
  <title>Environnement — {SITE_NOM}</title>
  <meta name="description" content="Prix de l'eau potable, qualité des cours d'eau, risques naturels recensés et installations classées {COMMUNE_A} et dans son intercommunalité." />
</svelte:head>

<section>
  <h1 class="avec-icone"><Icon name="environnement" size={26} />Environnement</h1>
  <p class="sub">
    Prix et performance de l'eau potable, qualité des cours d'eau, risques naturels
    recensés et installations classées. Données issues des registres publics
    (SISPEA, Naïades / Hub'Eau, Géorisques).
  </p>



  {#if stations.length || risques.length || icpe.length || eauPotable.length}
    <div class="tiles">
      <div class="tile"><span class="tval">{nb(totalAnalyses)}</span><span class="tlabel">analyses d'eau</span></div>
      <div class="tile"><span class="tval">{stations.length}</span><span class="tlabel">stations de mesure</span></div>
      <div class="tile"><span class="tval">{risquesParType.length}</span><span class="tlabel">types de risque</span></div>
      <div class="tile"><span class="tval">{catnat.length}</span><span class="tlabel">arrêtés catastrophe naturelle</span></div>
      {#if derniereAnalyse}
        <div class="tile"><span class="tval">{fmtDate(derniereAnalyse)}</span><span class="tlabel">dernier prélèvement</span></div>
      {/if}
    </div>

    <!-- ── L'eau du robinet ─────────────────────────────────────────── -->
    {#if eauPotable.length}
      <h2>L'eau du robinet</h2>
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
      Sources : SISPEA (prix et performance de l'eau potable),
      Naïades / Hub'Eau (qualité des cours d'eau), Géorisques (risques,
      ICPE, arrêtés CatNat), ADEME (diagnostics de performance énergétique,
      agrégés à la commune — aucune adresse n'est collectée). Aucune donnée n'est produite par ce site : tout
      provient des réseaux publics de mesure et de recensement.
    </p>
  {/if}
</section>

<style>
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
    .row { grid-template-columns: 1fr; }
    .rlabel { padding-bottom: .2rem; }
    .risques li { grid-template-columns: 1fr; }
  }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
