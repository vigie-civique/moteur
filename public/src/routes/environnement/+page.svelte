<script>
  import { COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // Eau, risques naturels et installations classées. 27 652 analyses, 75 risques
  // recensés et 3 ICPE étaient en base depuis des mois sans aucune page publique.

  // Rendu au build par +page.server.js.
  export let data
  $: ({ stations, series, couverture, risques, icpe, catnat } = data)
  let parametre = 'Nitrates'

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
  <meta name="description" content="Qualité de l'eau, risques naturels recensés et installations classées {COMMUNE_A} et dans son intercommunalité." />
</svelte:head>

<section>
  <h1 class="avec-icone"><Icon name="environnement" size={26} />Environnement</h1>
  <p class="sub">
    Qualité des cours d'eau, risques naturels recensés et installations classées.
    Données issues des réseaux de mesure publics (Naïades / Hub'Eau, Géorisques).
  </p>



  {#if stations.length || risques.length || icpe.length}
    <div class="tiles">
      <div class="tile"><span class="tval">{nb(totalAnalyses)}</span><span class="tlabel">analyses d'eau</span></div>
      <div class="tile"><span class="tval">{stations.length}</span><span class="tlabel">stations de mesure</span></div>
      <div class="tile"><span class="tval">{risquesParType.length}</span><span class="tlabel">types de risque</span></div>
      <div class="tile"><span class="tval">{catnat.length}</span><span class="tlabel">arrêtés catastrophe naturelle</span></div>
      {#if derniereAnalyse}
        <div class="tile"><span class="tval">{fmtDate(derniereAnalyse)}</span><span class="tlabel">dernier prélèvement</span></div>
      {/if}
    </div>

    <!-- ── Qualité de l'eau ─────────────────────────────────────────── -->
    <h2>Qualité de l'eau</h2>
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

    <p class="src">
      Sources : Naïades / Hub'Eau (qualité des cours d'eau), Géorisques (risques,
      ICPE, arrêtés CatNat). Aucune donnée n'est produite par ce site : tout
      provient des réseaux publics de mesure et de recensement.
    </p>
  {/if}
</section>

<style>
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
