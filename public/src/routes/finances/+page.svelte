<script>
  import { COMMUNE, COMMUNE_A, SITE_NOM } from '$lib/instance.js'
  import Niveau from '$lib/components/Niveau.svelte'
  import { euros } from '$lib/data.js'

  const COMMUNE_ID = 63
  const isRequest = (f) => /demand[eé]e/i.test(f.type || '')
  // Une cession de patrimoine est une VENTE : la commune cède un bien et ENCAISSE
  // le prix. Le flux est stocké commune → acheteur (sens du bien), mais l'argent va
  // dans l'autre sens. On la traite donc à part, comme une recette, jamais comme un
  // versement de subvention/marché. (Le snapshot ne garde que les cessions où la commune est partie.)
  const isCession = (f) => /cession/i.test(f.type || '')
  const isInflow  = (f) => f.to_id === COMMUNE_ID && !isCession(f)
  const isOutflow = (f) => f.from_id === COMMUNE_ID && !isCession(f)
  const unknownName = (n) => !n || n === '?' || n === '∅'

  const TYPE_LABELS = {
    subvention: 'Subvention', subvention_region: 'Subvention Région',
    subventions_recues: 'Subventions reçues', subvention_demandee: 'Subvention demandée',
    marche_public: 'Marché public', 'marché': 'Marché public',
    concours_etat: "Concours de l'État", DGF: 'Dotation (DGF)',
    dotations_subventions: 'Dotations & subventions', dotation: 'Dotation',
    dotation_fonctionnement: 'Dotation de fonctionnement',
    bail: 'Bail', emprunt: 'Emprunt', credit_relais: 'Crédit-relais',
    fonds_de_concours: 'Fonds de concours', fonds_concours: 'Fonds de concours',
    cession_fonds: 'Cession de fonds', cession_patrimoine: 'Cession de patrimoine',
  }
  const typeLabel = (t) => TYPE_LABELS[t] || (t || '—')

  // Rendu au build par +page.server.js.
  export let data
  $: all = data.flows.slice().sort((a, b) => (b.year || 0) - (a.year || 0) || (b.amount || 0) - (a.amount || 0))
  // Une année précise, toujours : l'option « Toutes » agrégeait des exercices
  // aux périmètres inégaux (dotations connues sur certaines années seulement),
  // ce qui donnait des totaux impossibles à interpréter.
  let year = null

  $: yearsAvail = [...new Set(all.map(f => f.year).filter(Boolean))].sort((a, b) => b - a)
  $: years = yearsAvail
  $: if (year === null && yearsAvail.length) year = yearsAvail[0]   // dernier exercice connu
  $: base = all.filter(f => !isRequest(f) && f.year === year)

  $: cessions = base.filter(isCession).sort((a, b) => (b.year || 0) - (a.year || 0) || (b.amount || 0) - (a.amount || 0))
  $: inflows  = base.filter(isInflow)
  $: outflows = base.filter(isOutflow)
  $: others   = base.filter(f => !isCession(f) && !isInflow(f) && !isOutflow(f))
  const sum = (L) => L.reduce((s, f) => s + (f.amount || 0), 0)
  $: inTotal = sum(inflows)
  $: outTotal = sum(outflows)
  $: othTotal = sum(others)
  $: cessionTotal = sum(cessions)

  $: requests = all.filter(f => isRequest(f) && f.year === year)
  $: reqTotal = sum(requests)

  // Vue annualisée : reçu et versé par an (échelles distinctes, ordres de grandeur différents).
  $: flowYears = [...new Set(all.filter(f => !isRequest(f) && f.year).map(f => f.year))].sort((a, b) => a - b)
  $: flowsByYear = flowYears.map(y => {
    const inY = all.filter(f => !isRequest(f) && f.year === y)
    return { year: y, in: sum(inY.filter(isInflow)), out: sum(inY.filter(isOutflow)) }
  })
  $: inYrMax = Math.max(...flowsByYear.map(d => d.in), 1)
  $: outYrMax = Math.max(...flowsByYear.map(d => d.out), 1)

  // La commune reçoit-elle une dotation pour l'année choisie ? (sinon, couverture partielle)
  $: dotationCovered = inflows.some(f => ['DGF', 'concours_etat', 'dotations_subventions'].includes(f.type))

  function group(rows, keyFn, idFn) {
    const named = new Map(), unknownTotal = { key: 'Bénéficiaire non précisé', total: 0, count: 0, id: null, unknown: true }
    for (const r of rows) {
      const name = keyFn(r)
      if (unknownName(name)) { unknownTotal.total += r.amount || 0; unknownTotal.count++; continue }
      const g = named.get(name) || { key: name, total: 0, count: 0, id: idFn ? idFn(r) : null }
      g.total += r.amount || 0; g.count++
      if (idFn && !g.id) g.id = idFn(r)
      named.set(name, g)
    }
    const arr = [...named.values()].sort((a, b) => b.total - a.total)
    if (unknownTotal.count) arr.push(unknownTotal)
    return arr
  }
  $: outByBenef = group(outflows, f => f.to_name, f => f.to_id)
  $: inBySource = group(inflows, f => f.from_name)
  $: outMax = Math.max(...outByBenef.map(g => g.total), 1)
  $: inMax = Math.max(...inBySource.map(g => g.total), 1)

  const TOP = 12
  let showAllOut = false, showAllIn = false
  $: outShown = showAllOut ? outByBenef : outByBenef.slice(0, TOP)
  $: inShown = showAllIn ? inBySource : inBySource.slice(0, TOP)

  function eurosC(n) {
    if (n == null) return '—'
    const a = Math.abs(n)
    if (a >= 1e6) return (n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€'
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString('fr-FR') + ' k€'
    return euros(n)
  }
  const pct = (n, t) => t ? Math.round(100 * n / t) + ' %' : ''
  const sens = (f) => isInflow(f) ? 'in' : (isOutflow(f) ? 'out' : 'oth')
  $: periode = year == null ? '—' : String(year)
</script>

<svelte:head><title>Flux financiers publics — {SITE_NOM}</title>
  <meta name="description" content="Où va l'argent public {COMMUNE_A} : subventions versées, dotations reçues, marchés attribués." /></svelte:head>

<section>
  <header class="head">
    <div>
      <h1>Flux financiers publics</h1>
      <p class="sub">Ce que la commune reçoit et ce qu'elle verse — subventions, marchés, dotations et baux recensés dans les données ouvertes et les délibérations.</p>
    </div>
    <label class="year">Période
      <select bind:value={year}>
        {#each years as y}<option value={y}>{y}</option>{/each}
      </select>
    </label>
  </header>

  {#if !all.length}<p class="muted">Aucun flux dans ce jeu de données.</p>{/if}

  {#if all.length}
    <p class="lede">
      Sur la période <b>{periode}</b>, la commune a reçu <b class="in">{eurosC(inTotal)}</b>
      (dotations de l'État, concours, emprunts) et versé <b class="out">{eurosC(outTotal)}</b>
      de subventions et marchés à des acteurs locaux.{#if cessionTotal > 0}&nbsp;Elle a par ailleurs <b class="ces">cédé pour {eurosC(cessionTotal)}</b> de patrimoine (ventes de terrains).{/if}
    </p>

    {#if !dotationCovered}
      <p class="note">⚠ Les dotations de l'État (DGF, concours) pour {year} ne figurent pas encore dans le jeu de données — le « reçu » de cette année est donc incomplet. Le graphique année par année ci-dessous montre les exercices renseignés.</p>
    {/if}

    <!-- Ces totaux sont nos sommes, pas un compte administratif : ils ne
         valent que pour les flux que nous avons recensés. -->
    <Niveau type="calcul" base="les flux financiers recensés dans les délibérations et les données ouvertes">
      {#if data.constat}
        Sur {data.constat.periode ? `${data.constat.periode[0]}–${data.constat.periode[1]}` : 'la période'},
        <b>{eurosC(data.constat.total)}</b> de versements de la commune sont recensés,
        répartis entre <b>{data.constat.beneficiaires}</b> bénéficiaires.
        <b>{data.constat.pour80}</b> d'entre eux réunissent 80&nbsp;% des montants.
      {:else}
        Les montants ci-dessous sont la somme des flux que la collecte a trouvés.
      {/if}
    </Niveau>
    {#if data.constat}
      <p class="lecture">
        <b>Ce que ce chiffre ne dit pas.</b> Les ventes de biens communaux sont
        exclues de ce total&nbsp;: une cession est une recette pour la commune, pas
        un versement, même si le bien va de la commune vers l'acquéreur. Les
        compter ici ferait passer l'acheteur d'un terrain communal pour le premier
        bénéficiaire de l'argent public alors qu'il a payé. Elles sont recensées
        à part, plus bas.
      </p>
    {/if}
    <div class="tiles">
      <div class="tile in">
        <span class="tlabel">Reçu par la commune</span>
        <span class="tval">{eurosC(inTotal)}</span>
        <span class="tsub">{inflows.length} flux · {periode}</span>
      </div>
      <div class="tile out">
        <span class="tlabel">Versé par la commune</span>
        <span class="tval">{eurosC(outTotal)}</span>
        <span class="tsub">{outflows.length} flux · {periode}</span>
      </div>
      {#if reqTotal > 0}
        <div class="tile req">
          <span class="tlabel">Demandes en cours</span>
          <span class="tval">{eurosC(reqTotal)}</span>
          <span class="tsub">{requests.length} subvention(s) sollicitée(s)</span>
        </div>
      {/if}
    </div>

    <!-- Vue annualisée : reçu / versé par an -->
    {#if flowsByYear.length > 1}
      <h2>Reçu &amp; versé, année par année</h2>
      <p class="hint">Deux échelles distinctes : le « reçu » (dotations, concours, emprunts) est bien plus élevé que le « versé » (subventions et marchés locaux).</p>
      <div class="yr2">
        <div class="yrblock">
          <span class="yrhead in">Reçu par la commune</span>
          <div class="yrbars">
            {#each flowsByYear as d}
              <button class="ycol" class:sel={d.year === year} title="{d.year} : {eurosC(d.in)} reçu — cliquer pour voir le détail"
                      on:click={() => year = d.year}>
                <span class="yval">{d.in ? eurosC(d.in) : ''}</span>
                <span class="ybar in" style="height:{Math.max(2, 100 * d.in / inYrMax)}%"></span>
                <span class="yyear">{d.year}</span>
              </button>
            {/each}
          </div>
        </div>
        <div class="yrblock">
          <span class="yrhead out">Versé par la commune</span>
          <div class="yrbars">
            {#each flowsByYear as d}
              <button class="ycol" class:sel={d.year === year} title="{d.year} : {eurosC(d.out)} versé — cliquer pour voir le détail"
                      on:click={() => year = d.year}>
                <span class="yval">{d.out ? eurosC(d.out) : ''}</span>
                <span class="ybar out" style="height:{Math.max(2, 100 * d.out / outYrMax)}%"></span>
                <span class="yyear">{d.year}</span>
              </button>
            {/each}
          </div>
        </div>
      </div>
    {/if}

    <!-- Cessions de patrimoine communal (ventes = recettes, sens inverse du flux stocké) -->
    {#if cessions.length}
      <h2 class="ces-h">Cessions de patrimoine communal</h2>
      <p class="hint">Ventes de biens de la commune (terrains, domaine public déclassé) — <b class="ces">{eurosC(cessionTotal)}</b> sur {periode}. La commune <b>vend et encaisse</b> le prix : c'est une recette, ni une subvention ni un marché.</p>
      <ul class="clist">
        {#each cessions as f (f.id)}
          <li>
            <span class="cyear">{f.year || '—'}</span>
            <span class="cbody">
              <span class="cbuyer">Vendu à {f.to_name || 'acquéreur non précisé'}</span>
              {#if f.description}<span class="cdesc">{f.description}</span>{/if}
            </span>
            <span class="camt">+{eurosC(f.amount)}</span>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- Versé par la commune -->
    {#if outByBenef.length}
      <h2 class="out-h">Ce que la commune verse</h2>
      <p class="hint">Subventions et marchés payés par la commune — {eurosC(outTotal)} sur {periode}.</p>
      <ul class="bars">
        {#each outShown as g}
          <li>
            <span class="blabel" class:unk={g.unknown}>
              {#if g.id}<a href="/entite/{g.id}">{g.key}</a>{:else}{g.key}{/if}
              {#if g.count > 1}<em>· {g.count} flux</em>{/if}
            </span>
            <span class="btrack"><span class="bfill out" style="width:{100 * g.total / outMax}%"></span></span>
            <span class="bval">{eurosC(g.total)}</span>
            <span class="bpct">{pct(g.total, outTotal)}</span>
          </li>
        {/each}
      </ul>
      {#if outByBenef.length > TOP}
        <button class="more" on:click={() => showAllOut = !showAllOut}>
          {showAllOut ? '− Réduire' : `+ ${outByBenef.length - TOP} autres`}
        </button>
      {/if}
    {/if}

    <!-- Reçu par la commune -->
    {#if inBySource.length}
      <h2 class="in-h">D'où vient l'argent reçu</h2>
      <p class="hint">Financeurs de la commune — {eurosC(inTotal)} sur {periode}.</p>
      <ul class="bars">
        {#each inShown as g}
          <li>
            <span class="blabel" class:unk={g.unknown}>{g.key}{#if g.count > 1}<em>· {g.count} flux</em>{/if}</span>
            <span class="btrack"><span class="bfill in" style="width:{100 * g.total / inMax}%"></span></span>
            <span class="bval">{eurosC(g.total)}</span>
            <span class="bpct">{pct(g.total, inTotal)}</span>
          </li>
        {/each}
      </ul>
      {#if inBySource.length > TOP}
        <button class="more" on:click={() => showAllIn = !showAllIn}>
          {showAllIn ? '− Réduire' : `+ ${inBySource.length - TOP} autres`}
        </button>
      {/if}
    {/if}

    <!-- Flux tiers -->
    {#if others.length}
      <details>
        <summary>Autres flux publics recensés sur le territoire ({others.length} · {eurosC(othTotal)})</summary>
        <p class="hint">Flux n'impliquant pas directement le budget communal : subventions Région, marchés et emprunts de l'intercommunalité, cessions entre acteurs privés.</p>
        <table>
          <thead><tr><th>Année</th><th>Type</th><th>De → vers</th><th class="r">Montant</th></tr></thead>
          <tbody>
            {#each [...others].sort((a, b) => (b.amount || 0) - (a.amount || 0)) as f (f.id)}
              <tr>
                <td>{f.year || '—'}</td><td>{typeLabel(f.type)}</td>
                <td class="who">{f.from_name || '—'} → {#if f.to_id}<a href="/entite/{f.to_id}">{f.to_name || '?'}</a>{:else}{f.to_name || '—'}{/if}</td>
                <td class="r">{euros(f.amount)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </details>
    {/if}

    <!-- Détail commune -->
    <details>
      <summary>Détail des flux de la commune ({inflows.length + outflows.length})</summary>
      <table>
        <thead><tr><th>Année</th><th>Sens</th><th>Type</th><th>Financeur → bénéficiaire</th><th>Description</th><th class="r">Montant</th></tr></thead>
        <tbody>
          {#each [...inflows, ...outflows].sort((a, b) => (b.year || 0) - (a.year || 0) || (b.amount || 0) - (a.amount || 0)) as f (f.id)}
            <tr>
              <td>{f.year || '—'}</td>
              <td>{#if isInflow(f)}<span class="tag in">reçu</span>{:else}<span class="tag out">versé</span>{/if}</td>
              <td>{typeLabel(f.type)}</td>
              <td class="who">{f.from_name || '—'} → {#if f.to_id}<a href="/entite/{f.to_id}">{f.to_name || '?'}</a>{:else}{f.to_name || '—'}{/if}</td>
              <td class="desc">{f.description || ''}</td>
              <td class="r">{euros(f.amount)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </details>

    <p class="foot">Sources : DECP (marchés), subventions État/Région, délibérations du conseil municipal. « Reçu » / « versé » = la commune (SIREN {COMMUNE}) est respectivement destinataire ou émetteur du flux ; les flux entre tiers sont regroupés à part. Les demandes non accordées sont exclues des totaux.</p>
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

  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0; max-width: 62ch; }
  .year { color: var(--gris); font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; }
  select { padding: .4rem .6rem; border: 1px solid var(--trait); border-radius: 6px; font-size: .95rem; }

  .in  { color: var(--recette); }
  .out { color: var(--ardoise); }

  .lede { font-size: 1.05rem; line-height: 1.6; margin: 1.25rem 0 1rem; color: var(--gris); }
  .lede b { font-weight: 700; }
  .note { background: var(--ambre-pale); border: 1px solid #eadfc6; color: var(--ambre); border-radius: 8px; padding: .6rem .8rem; font-size: .85rem; margin: 0 0 1.25rem; }

  .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin-bottom: 1.75rem; }
  .tile { background: #fff; border: 1px solid var(--trait); border-top: 3px solid var(--trait); border-radius: 8px; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem; }
  .tile.in  { border-top-color: var(--recette); }
  .tile.out { border-top-color: var(--ardoise); }
  .tile.req { border-top-color: var(--ambre); }
  .tlabel { font-size: .72rem; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
  .tval { font-size: 1.45rem; font-weight: 700; color: var(--encre); }
  .tsub { font-size: .78rem; color: var(--gris-clair); }

  h2 { margin: 1.75rem 0 .25rem; font-size: 1.15rem; }
  h2.out-h { color: var(--ardoise-fonce); } h2.in-h { color: var(--recette); } h2.ces-h { color: var(--ardoise); }
  .hint { color: var(--gris); font-size: .85rem; margin: 0 0 .9rem; }
  .ces { color: var(--ardoise); }

  /* Cessions de patrimoine (recettes exceptionnelles) */
  .clist { list-style: none; padding: 0; margin: 0 0 .5rem; display: flex; flex-direction: column; gap: .5rem; }
  .clist li { display: grid; grid-template-columns: 52px 1fr auto; align-items: baseline; gap: .7rem;
              background: #faf5ff; border: 1px solid var(--ardoise-pale); border-left: 3px solid var(--ardoise); border-radius: 8px; padding: .55rem .75rem; }
  .cyear { font-size: .82rem; font-weight: 700; color: var(--ardoise); font-variant-numeric: tabular-nums; }
  .cbody { display: flex; flex-direction: column; gap: .1rem; min-width: 0; }
  .cbuyer { font-size: .88rem; color: var(--encre); font-weight: 600; }
  .cdesc { font-size: .78rem; color: var(--gris); line-height: 1.35; }
  .camt { font-size: .95rem; font-weight: 700; color: var(--ardoise); white-space: nowrap; font-variant-numeric: tabular-nums; }

  /* Vue annualisée reçu / versé */
  .yr2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: .5rem; }
  .yrhead { display: block; font-size: .8rem; font-weight: 700; margin-bottom: .4rem; }
  .yrhead.in { color: var(--recette); } .yrhead.out { color: var(--ardoise-fonce); }
  .yrbars { display: flex; align-items: flex-end; gap: .35rem; height: 130px; padding: .5rem 0; border-bottom: 1px solid var(--trait); overflow-x: auto; }
  .ycol { flex: 1; min-width: 26px; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: .12rem;
          background: none; border: 0; padding: 0 0 .1rem; cursor: pointer; border-bottom: 2px solid transparent; }
  .ycol.sel { border-bottom-color: var(--encre); }
  .ycol.sel .yyear, .ycol.sel .yval { color: var(--encre); font-weight: 700; }
  .yval { font-size: .6rem; color: var(--gris-clair); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ybar { width: 60%; max-width: 30px; border-radius: 4px 4px 0 0; min-height: 2px; }
  .ybar.in { background: var(--recette); } .ybar.out { background: var(--ardoise); }
  .yyear { font-size: .64rem; color: var(--gris); transform: rotate(-45deg); transform-origin: center; white-space: nowrap; }
  @media (max-width: 640px) { .yr2 { grid-template-columns: 1fr; } }

  .bars { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .55rem; }
  .bars li { display: grid; grid-template-columns: minmax(0, 1fr) 72px 42px; align-items: center; column-gap: .6rem; row-gap: .15rem; }
  .blabel { grid-column: 1 / -1; font-size: .82rem; color: var(--gris); }
  .blabel.unk { color: var(--gris-clair); font-style: italic; }
  .blabel a { color: var(--ardoise-fonce); } .blabel em { color: var(--gris-clair); font-style: normal; font-size: .75rem; }
  .btrack { grid-column: 1; display: block; background: var(--trait-pale); border-radius: 4px; height: 14px; overflow: hidden; }
  .bfill { display: block; height: 100%; border-radius: 4px; }
  .bfill.out { background: var(--ardoise); } .bfill.in { background: var(--recette); }
  .bval { grid-column: 2; text-align: right; font-size: .82rem; font-weight: 700; color: var(--encre); font-variant-numeric: tabular-nums; }
  .bpct { grid-column: 3; text-align: right; font-size: .75rem; color: var(--gris-clair); }

  .more { margin-top: .75rem; background: var(--trait-pale); border: 1px solid var(--trait); border-radius: 6px; padding: .35rem .8rem; font-size: .82rem; color: var(--gris); cursor: pointer; }
  .more:hover { background: var(--trait); }

  details { margin-top: 1.5rem; border-top: 1px solid var(--trait); padding-top: .5rem; }
  summary { cursor: pointer; color: var(--gris); font-size: .9rem; font-weight: 600; padding: .35rem 0; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--ardoise-pale); vertical-align: top; }
  th { color: var(--gris); font-weight: 600; }
  .r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .who a { color: var(--ardoise-fonce); } .desc { color: var(--gris); }
  .tag { font-size: .68rem; font-weight: 700; padding: 1px 6px; border-radius: 999px; }
  .tag.in { background: #e7f0ea; color: var(--recette); } .tag.out { background: var(--ardoise-pale); color: var(--ardoise-fonce); }

  .muted { color: var(--gris); }
  .foot { color: var(--gris-clair); font-size: .78rem; margin-top: 1.5rem; max-width: 72ch; }

  @media (max-width: 720px) { .tiles { grid-template-columns: 1fr; } }
</style>
