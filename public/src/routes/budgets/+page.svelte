<script>
  import { COMMUNE, COMMUNE_DE, INSEE, SITE_NOM } from '$lib/instance.js'
  import Niveau from '$lib/components/Niveau.svelte'
  import { euros } from '$lib/data.js'

  // Rendu au build par +page.server.js.
  export let data
  $: annuel = data.budget.annuel || []
  $: annexe = data.budget.annexe || []
  $: ofgl = data.ofgl.ofgl || []
  $: vote = data.budgetVote.budget_vote || []
  // Exercice par défaut = année OFGL la plus récente (réalisé consolidé).
  // Calculé au premier rendu seulement : ensuite `year` suit le sélecteur.
  let year = null
  $: if (year === null && (ofgl.length || annuel.length)) {
    const ys = [...new Set(ofgl.map((r) => r.year))].sort((a, b) => b - a)
    year = ys[0] ?? [...new Set(annuel.map((r) => r.year))].sort((a, b) => b - a)[0] ?? null
  }

  // Années « réalisées » (OFGL, repli DGFiP) et années « budget voté » (CR, hors OFGL).
  $: ofglYearsSet = new Set(ofgl.map(r => r.year))
  $: voteYears = [...new Set(vote.map(r => r.year))]
  $: realizedYears = ofgl.length
    ? [...new Set(ofgl.map(r => r.year))]
    : [...new Set(annuel.map(r => r.year))]
  $: years = [...new Set([...realizedYears, ...voteYears])].sort((a, b) => b - a)
  const isVoteOnly = (y) => voteYears.includes(y) && !ofglYearsSet.has(y)
  $: isVoteYear = isVoteOnly(year)
  // Données du budget voté pour l'exercice choisi.
  $: voteRows = vote.filter(r => r.year === year)
  $: votePrincipal = voteRows.filter(r => r.scope === 'principal')
  $: voteAnnexes = voteRows.filter(r => r.scope !== 'principal')
  $: voteSource = voteRows[0]?.source ?? ''
  $: voteSourceUrl = voteRows[0]?.source_url ?? ''
  $: voteRec = votePrincipal.find(r => r.agregat === 'Recettes de fonctionnement')?.value ?? null
  $: voteDep = votePrincipal.find(r => r.agregat === 'Dépenses de fonctionnement')?.value ?? null
  $: voteEquilScale = Math.max(voteRec || 0, voteDep || 0, 1)
  function fmtVote(r) {
    if (r.value == null) return '—'
    if (r.unit === 'pct') return r.value.toLocaleString('fr-FR') + ' %'
    if (r.unit === 'annees') return r.value.toLocaleString('fr-FR') + ' ans'
    return (r.approx ? '≈ ' : '') + eurosC(r.value)
  }

  // Années où le détail par compte DGFiP existe (colonnes "Où va / D'où vient l'argent").
  $: dgfipYears = new Set(annuel.filter(r => r.categorie === 'depenses_fonctionnement').map(r => r.year))
  $: hasDetail = dgfipYears.has(year)
  $: lastDetailYear = Math.max(...dgfipYears, 0) || null

  // ─── OFGL : agrégats propres + €/habitant (source des chiffres-clés) ───────────
  $: ofglYearRows = ofgl.filter(r => r.year === year)
  $: population = ofglYearRows[0]?.population ?? null
  const ofglOf = (rows, name) => rows.find(r => r.agregat === name) || null
  $: gV = (name) => { const r = ofglOf(ofglYearRows, name); return r ? r.montant : null }
  $: gH = (name) => { const r = ofglOf(ofglYearRows, name); return r ? r.euros_par_habitant : null }

  // ─── DGFiP : détail par compte (où va / d'où vient l'argent) ───────────────────
  const lines = (cat) => annuel
    .filter(r => r.year === year && r.categorie === cat && (r.montant || 0) > 0)
    .sort((a, b) => b.montant - a.montant)
  $: depRows = lines('depenses_fonctionnement')
  $: recRows = lines('recettes_fonctionnement')
  $: depTotalDG = depRows.reduce((s, r) => s + r.montant, 0)
  $: recTotalDG = recRows.reduce((s, r) => s + r.montant, 0)
  $: depMax = Math.max(...depRows.map(r => r.montant), 1)
  $: recMax = Math.max(...recRows.map(r => r.montant), 1)

  // ─── Chiffres-clés (OFGL en priorité, DGFiP en repli) ──────────────────────────
  $: recF = gV('Recettes de fonctionnement') ?? recTotalDG
  $: depF = gV('Dépenses de fonctionnement') ?? depTotalDG
  $: epargne = gV('Epargne brute') ?? ((recF != null && depF != null) ? recF - depF : null)
  $: epargneNette = gV('Epargne nette')
  $: dette = gV('Encours de dette')
  $: detteH = gH('Encours de dette')
  $: annuite = gV('Annuité de la dette')
  $: equipement = gV("Dépenses d'équipement")
  $: recFH = gH('Recettes de fonctionnement')
  $: depFH = gH('Dépenses de fonctionnement')
  $: epargneH = gH('Epargne brute')
  $: equilScale = Math.max(recF || 0, depF || 0, 1)
  $: epargnePct = (recF && epargne != null) ? Math.round(100 * epargne / recF) : null

  // ─── Évolution de l'épargne brute (toutes années OFGL) ─────────────────────────
  $: ofglYears = [...new Set(ofgl.map(r => r.year))].sort((a, b) => a - b)
  $: epargneSerie = ofglYears
    .map(y => { const r = ofgl.find(x => x.year === y && x.agregat === 'Epargne brute'); return { year: y, val: r ? r.montant : null } })
    .filter(d => d.val != null)
  $: epSerieMax = Math.max(...epargneSerie.map(d => Math.abs(d.val)), 1)

  // ─── Agrégats OFGL : vue annualisée, groupée par thème (pivot année) ───────────
  const OFGL_GROUPS = [
    { title: 'Fonctionnement', items: ['Recettes de fonctionnement', 'Dépenses de fonctionnement', 'Frais de personnel', 'Achats et charges externes'] },
    { title: 'Épargne',        items: ['Epargne brute', 'Epargne nette', 'Epargne de gestion'] },
    { title: 'Investissement', items: ["Dépenses d'équipement", "Recettes d'investissement", 'FCTVA'] },
    { title: 'Dette',          items: ['Encours de dette', 'Annuité de la dette', 'Charges financières'] },
    { title: 'Fiscalité & dotations', items: ['Impôts locaux', 'Impôts et taxes', "Concours de l'Etat", 'Dotation globale de fonctionnement'] },
  ]
  let showPerHab = false
  $: ofglIndex = (() => { const m = new Map(); for (const r of ofgl) m.set(r.agregat + '|' + r.year, r); return m })()
  const ofglCell = (name, y) => ofglIndex.get(name + '|' + y) || null
  // Un agrégat n'est affiché que s'il a au moins une valeur sur la période.
  $: ofglGroupsShown = OFGL_GROUPS
    .map(g => ({ title: g.title, items: g.items.filter(name => ofglYears.some(y => ofglCell(name, y))) }))
    .filter(g => g.items.length)

  // ─── Budgets annexes : synthèse par structure et par année ─────────────────────
  const pickRow = (rows, re) => rows.find(r => re.test(r.libelle || ''))
  $: annexeByStruct = (() => {
    const m = new Map()
    for (const r of annexe) {
      const name = r.entity_name || 'Budget annexe'
      if (!m.has(name)) m.set(name, new Map())
      const yrs = m.get(name)
      if (!yrs.has(r.year)) yrs.set(r.year, [])
      yrs.get(r.year).push(r)
    }
    return [...m.entries()].map(([name, yrs]) => ({
      name,
      years: [...yrs.values()].map(rows => {
        const solde = rows.find(r => r.sens === 'solde')
        const subv = pickRow(rows, /subvention.*(commune|exploitation)/i)
        return {
          year: rows[0].year,
          soldeVal: solde ? solde.montant : null,
          soldeLbl: solde ? (solde.libelle || '') : '',
          subvComm: subv ? subv.montant : null,
          source: rows.find(r => r.source)?.source || '',
          rows,
        }
      }).sort((a, b) => a.year - b.year),
    })).sort((a, b) => a.name.localeCompare(b.name))
  })()

  // ─── Formatage ─────────────────────────────────────────────────────────────────
  function eurosC(n) {
    if (n == null) return '—'
    const a = Math.abs(n)
    if (a >= 1e6) return (n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€'
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString('fr-FR') + ' k€'
    return euros(n)
  }
  const perHab = (n) => n == null ? '—' : Math.round(n).toLocaleString('fr-FR') + ' €/hab.'

  // Un montant seul n'apprend rien : 1,83 M€, est-ce beaucoup ? Trois questions
  // rendent un chiffre lisible — combien, comparé à quoi, comment ça évolue.
  // Le €/hab répond à la deuxième, la série à la troisième.
  const serieDe = (agregat) => {
    const m = new Map()
    for (const r of ofgl) if (r.agregat === agregat && r.montant != null) m.set(r.year, r.montant)
    return m
  }
  const evolution = (agregat, depuis) => {
    const m = serieDe(agregat)
    const av = m.get(depuis), ap = m.get(year)
    if (av == null || ap == null || !av) return null
    return Math.round(100 * (ap - av) / av)
  }
  $: anneesOfgl = [...new Set(ofgl.map((r) => r.year))].sort((a, b) => a - b)
  $: premiereAnnee = anneesOfgl[0] ?? null
  $: evolRec1 = evolution('Recettes de fonctionnement', year - 1)
  $: evolDep1 = evolution('Dépenses de fonctionnement', year - 1)
  $: evolDette1 = evolution('Encours de dette', year - 1)
  $: evolDetteTot = premiereAnnee ? evolution('Encours de dette', premiereAnnee) : null

  // Point bas de la dette sur la série : c'est lui qui donne l'échelle du
  // retournement, pas la première année observée.
  $: detteSerie = [...serieDe('Encours de dette').entries()].sort((a, b) => a[0] - b[0])
  $: detteMin = detteSerie.length ? detteSerie.reduce((min, e) => (e[1] < min[1] ? e : min)) : null
  $: detteFacteur = (detteMin && dette && detteMin[1]) ? (dette / detteMin[1]) : null
  $: facteurDette = detteFacteur
    ? detteFacteur.toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    : null

  const signe = (n) => (n == null ? '' : (n > 0 ? '+' : '') + n + ' %')
  const pct = (n, total) => total ? Math.round(100 * n / total) + ' %' : ''
</script>

<svelte:head><title>Budget communal — {SITE_NOM}</title>
  <meta name="description" content="Budget de la commune {COMMUNE_DE} : recettes, dépenses, budgets annexes et comparaison avec les communes semblables (OFGL)." /></svelte:head>

<section>
  <header class="head">
    <div>
      <h1>Budget communal</h1>
      <p class="sub">Ce que la commune perçoit, dépense, épargne et doit — en un coup d'œil.</p>
    </div>
    {#if years.length}
      <label class="year">Exercice
        <select bind:value={year}>{#each years as y}<option value={y}>{y}{isVoteOnly(y) ? ' · voté' : ''}</option>{/each}</select>
      </label>
    {/if}
  </header>

  {#if !ofgl.length && !annuel.length}<p class="muted">Aucune donnée budgétaire.</p>{/if}

  {#if year}
    {#if isVoteYear}
      <!-- Budget primitif VOTÉ (prévisionnel) — source unique provisoire : CR du CM -->
      <div class="votebanner">
        <b>Budget primitif voté {year}</b> — chiffres <b>prévisionnels</b> adoptés par le conseil municipal,
        non encore consolidés par la DGFiP / OFGL. Source unique provisoire :
        {voteSource}{#if voteSourceUrl} · <a href={voteSourceUrl} target="_blank" rel="noopener">voir le CR ↗</a>{/if}.
      </div>

      {#if voteRec && voteDep}
        <h2>L'équilibre du fonctionnement (voté)</h2>
        <div class="equil">
          <div class="erow">
            <span class="ekey"><i class="sw in"></i> Recettes</span>
            <div class="etrack"><div class="efill in" style="width:{100 * voteRec / voteEquilScale}%"></div></div>
            <span class="eval">{eurosC(voteRec)}</span>
          </div>
          <div class="erow">
            <span class="ekey"><i class="sw out"></i> Dépenses</span>
            <div class="etrack"><div class="efill out" style="width:{100 * voteDep / voteEquilScale}%"></div></div>
            <span class="eval">{eurosC(voteDep)}</span>
          </div>
        </div>
      {/if}

      <h2>Chiffres-clés du budget voté</h2>
      <div class="tiles">
        {#each votePrincipal as r}
          <div class="tile vote">
            <span class="tlabel">{r.agregat}</span>
            <span class="tval">{fmtVote(r)}</span>
            {#if r.note}<span class="tsub">{r.note}</span>{/if}
          </div>
        {/each}
      </div>

      {#if voteAnnexes.length}
        <h3>Budgets annexes votés {year}</h3>
        <ul class="votelist">
          {#each voteAnnexes as r}
            <li>
              <span class="vname">{r.scope}</span>
              <span class="vval">{fmtVote(r)}</span>
              {#if r.note}<span class="vnote">{r.note}</span>{/if}
            </li>
          {/each}
        </ul>
      {/if}

      <p class="hint">Ces montants proviennent exclusivement de la délibération budgétaire ; ils seront remplacés par le réalisé (comptes administratifs / OFGL) dès sa publication (~18 mois plus tard).</p>
    {:else}
    <!-- 1 ─ Synthèse en une phrase -->
    <p class="lede">
      En <b>{year}</b>{#if population}, {COMMUNE} (<b>{population.toLocaleString('fr-FR')}</b> hab.){/if}
      a perçu <b class="in">{eurosC(recF)}</b> de recettes de fonctionnement
      et dépensé <b class="out">{eurosC(depF)}</b>,
      {#if epargne != null}dégageant <b class="save">{eurosC(epargne)}</b> d'épargne{#if epargnePct != null}{' '}({epargnePct} % des recettes){/if} pour investir et se désendetter{/if}.
      {#if dette != null}Sa dette atteint <b class="debt">{eurosC(dette)}</b>{#if detteH != null}{' '}({perHab(detteH)}){/if}.{/if}
    </p>

    <!-- Deux chiffres de population coexistent sur le site : celui retenu par
         OFGL pour les ratios financiers (1 148) et la population municipale
         INSEE affichée sur /territoire (1 202). Les deux sont justes — elles ne
         comptent pas la même chose ni la même année — mais un lecteur qui passe
         d'une page à l'autre y voit une contradiction si personne ne le dit. -->
    {#if population}
      <p class="pop-note">
        Population retenue par l'Observatoire des finances locales pour cet
        exercice. Elle peut différer de la population municipale publiée par
        l'INSEE, indiquée sur <a href="/territoire">la page Territoire</a>&nbsp;:
        les deux ne portent ni sur la même année ni sur la même définition.
      </p>
    {/if}

    <!-- Combien / comparé à quoi / comment ça évolue. Sans la troisième
         question, « 1,78 M€ de dette » ne se distingue pas d'une situation
         stable depuis dix ans. -->
    {#if evolRec1 != null || evolDette1 != null}
      <p class="evolution">
        {#if evolRec1 != null}Recettes <b>{signe(evolRec1)}</b> sur un an{/if}
        {#if evolDep1 != null} · dépenses <b>{signe(evolDep1)}</b>{/if}
        {#if evolDette1 != null} · dette <b>{signe(evolDette1)}</b>{/if}
        <!-- Cette phrase ne regardait que la trajectoire longue, et ignorait
             l'exercice affiché juste avant elle : sur 2025, la page écrivait
             « dette -4 % » puis, trois mots plus loin, « multipliée par 3,4 ».
             Les deux chiffres étaient justes et la page se contredisait quand
             même. Quand la dette recule sur l'exercice, c'est ce recul qui se
             dit en premier ; l'échelle longue vient ensuite, comme mesure de ce
             qui reste à rembourser. -->
        {#if detteFacteur && detteFacteur > 1.5 && detteMin}
          <br />
          {#if evolDette1 != null && evolDette1 < 0}
            Elle recule sur l'exercice, mais reste <b>{facteurDette}</b> fois
            son point bas de {detteMin[0]} ({eurosC(detteMin[1])}).
          {:else}
            La dette a été multipliée par <b>{facteurDette}</b> depuis
            son point bas de {detteMin[0]} ({eurosC(detteMin[1])}).
          {/if}
        {/if}
        <span class="courants">Montants en euros courants, non corrigés de l'inflation&nbsp;: une hausse de quelques pour cent sur un an ne signifie pas une hausse en pouvoir d'achat.</span>
      </p>

      {#if detteFacteur && detteFacteur > 1.5}
        <p class="lecture">
          <!-- « Une dette qui augmente » affirmait une hausse au moment même où
               l'exercice affichait une baisse : ce paragraphe se déclenche sur
               le facteur pluriannuel, pas sur l'année. Formulation sans
               direction — elle reste vraie que la dette monte ou reflue. -->
          <b>Ce que ce chiffre ne dit pas.</b> Un endettement élevé n'est pas en
          soi un mauvais signe&nbsp;: la dette finance des investissements, et emprunter
          quand les taux sont bas pour réaliser des travaux durables est une
          décision courante. Ce que ces chiffres ne disent pas, c'est
          <em>ce qui</em> a été financé — cela se cherche dans
          <a href="/deliberations">les délibérations</a> des années concernées.
        </p>
      {/if}
    {/if}

    <!-- 2 ─ Chiffres-clés -->
    <!-- Distinction importante : ces montants ne sont PAS nos calculs. Ce sont
         les agrégats publiés par l'Observatoire des finances locales à partir
         des comptes de la commune. Les étiqueter « calcul » les affaiblirait à
         tort — ils sont plus solides que ce que nous savons produire. -->
    <Niveau type="fait" compact source="Agrégats publiés par OFGL / DGFiP, d'après les comptes de la commune" />
    <div class="tiles">
      <div class="tile in">
        <span class="tlabel">Recettes de fonctionnement</span>
        <span class="tval">{eurosC(recF)}</span>
        <span class="tsub">{perHab(recFH)}</span>
      </div>
      <div class="tile out">
        <span class="tlabel">Dépenses de fonctionnement</span>
        <span class="tval">{eurosC(depF)}</span>
        <span class="tsub">{perHab(depFH)}</span>
      </div>
      <div class="tile save">
        <span class="tlabel">Épargne brute</span>
        <span class="tval">{eurosC(epargne)}</span>
        <span class="tsub">{perHab(epargneH)}</span>
      </div>
      <div class="tile debt">
        <span class="tlabel">Dette (encours)</span>
        <span class="tval">{eurosC(dette)}</span>
        <span class="tsub">{perHab(detteH)}</span>
      </div>
    </div>

    <!-- 3 ─ Équilibre du fonctionnement -->
    {#if recF && depF}
      <h2>L'équilibre du fonctionnement</h2>
      <p class="hint">Ce qui reste entre recettes et dépenses courantes forme l'épargne — la capacité de la commune à investir sans emprunter.</p>
      <div class="equil">
        <div class="erow">
          <span class="ekey"><i class="sw in"></i> Recettes</span>
          <div class="etrack"><div class="efill in" style="width:{100 * recF / equilScale}%"></div></div>
          <span class="eval">{eurosC(recF)}</span>
        </div>
        <div class="erow">
          <span class="ekey"><i class="sw out"></i> Dépenses</span>
          <div class="etrack"><div class="efill out" style="width:{100 * depF / equilScale}%"></div></div>
          <span class="eval">{eurosC(depF)}</span>
        </div>
        {#if epargne != null}
          <div class="erow save-row">
            <span class="ekey"><i class="sw save"></i> Épargne</span>
            <div class="etrack"><div class="efill save" style="width:{100 * Math.max(epargne, 0) / equilScale}%"></div></div>
            <span class="eval">{eurosC(epargne)}</span>
          </div>
        {/if}
      </div>
    {/if}

    <!-- 4 ─ Où va l'argent / D'où vient l'argent (détail DGFiP par compte) -->
    {#if !hasDetail}
      <p class="note">Le détail comptable par poste (« où va / d'où vient l'argent ») n'est pas encore publié pour {year} — la DGFiP diffuse les comptes détaillés avec environ 18 mois de décalage. Les chiffres-clés et l'épargne ci-dessus proviennent des agrégats OFGL, disponibles plus tôt.{#if lastDetailYear}{' '}Dernier exercice détaillé : <b>{lastDetailYear}</b>.{/if}</p>
    {/if}
    <div class="cols">
      {#if depRows.length}
        <div class="col">
          <h2 class="out-h">Où va l'argent</h2>
          <p class="hint">Dépenses de fonctionnement {year} — {eurosC(depTotalDG)}</p>
          <ul class="bars">
            {#each depRows as r}
              <li>
                <span class="blabel" title={r.libelle}>{r.libelle}</span>
                <span class="btrack"><span class="bfill out" style="width:{100 * r.montant / depMax}%"></span></span>
                <span class="bval">{eurosC(r.montant)}</span>
                <span class="bpct">{pct(r.montant, depTotalDG)}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if recRows.length}
        <div class="col">
          <h2 class="in-h">D'où vient l'argent</h2>
          <p class="hint">Recettes de fonctionnement {year} — {eurosC(recTotalDG)}</p>
          <ul class="bars">
            {#each recRows as r}
              <li>
                <span class="blabel" title={r.libelle}>{r.libelle}</span>
                <span class="btrack"><span class="bfill in" style="width:{100 * r.montant / recMax}%"></span></span>
                <span class="bval">{eurosC(r.montant)}</span>
                <span class="bpct">{pct(r.montant, recTotalDG)}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </div>

    <!-- 5 ─ Dette, épargne, investissement -->
    <h2>Dette &amp; capacité d'action</h2>
    <div class="tiles small">
      <div class="tile"><span class="tlabel">Annuité de la dette</span><span class="tval">{eurosC(annuite)}</span><span class="tsub">{perHab(gH('Annuité de la dette'))}</span></div>
      <div class="tile"><span class="tlabel">Épargne nette</span><span class="tval">{eurosC(epargneNette)}</span><span class="tsub">{perHab(gH('Epargne nette'))}</span></div>
      <div class="tile"><span class="tlabel">Dépenses d'équipement</span><span class="tval">{eurosC(equipement)}</span><span class="tsub">{perHab(gH("Dépenses d'équipement"))}</span></div>
      <div class="tile"><span class="tlabel">Concours de l'État</span><span class="tval">{eurosC(gV("Concours de l'Etat"))}</span><span class="tsub">{perHab(gH("Concours de l'Etat"))}</span></div>
    </div>
    {/if}

    {#if epargneSerie.length > 1}
      <h3>Évolution de l'épargne brute</h3>
      <div class="trend">
        {#each epargneSerie as d}
          <div class="tcol" class:cur={d.year === year} title="{d.year} : {eurosC(d.val)}">
            <span class="tbar-val">{Math.round(d.val / 1000)}k</span>
            <span class="tbar" class:neg={d.val < 0} style="height:{Math.max(4, 100 * Math.abs(d.val) / epSerieMax)}%"></span>
            <span class="tyear">{d.year}</span>
          </div>
        {/each}
      </div>
    {/if}

    <!-- 6 ─ Agrégats OFGL : vue annualisée par thème -->
    {#if ofglGroupsShown.length}
      <div class="secthead">
        <h3>Agrégats financiers, année par année</h3>
        <div class="seg">
          <button class:on={!showPerHab} on:click={() => showPerHab = false}>Montant</button>
          <button class:on={showPerHab} on:click={() => showPerHab = true}>€/hab.</button>
        </div>
      </div>
      <p class="hint">Les grands équilibres financiers de la commune sur {Math.min(...ofglYears)}–{Math.max(...ofglYears)} (source OFGL). Colonne <b>{year}</b> surlignée.</p>
      <div class="scrollx">
        <table class="matrix">
          <thead>
            <tr><th class="ag">Agrégat</th>{#each ofglYears as y}<th class="r" class:cur={y === year}>{y}</th>{/each}</tr>
          </thead>
          <tbody>
            {#each ofglGroupsShown as g}
              <tr class="grp"><td colspan={ofglYears.length + 1}>{g.title}</td></tr>
              {#each g.items as name}
                <tr>
                  <td class="ag" title={name}>{name}</td>
                  {#each ofglYears as y}
                    {@const c = ofglCell(name, y)}
                    <td class="r" class:cur={y === year}>
                      {#if c}{showPerHab ? (c.euros_par_habitant != null ? Math.round(c.euros_par_habitant) + ' €' : '—') : eurosC(c.montant)}{:else}·{/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    <!-- 7 ─ Budgets annexes : synthèse par structure et par année -->
    {#if annexeByStruct.length}
      <h3>Budgets annexes — par structure</h3>
      <p class="hint">Régies et budgets rattachés (hors budget principal). Solde de fonctionnement et subvention versée par la commune, année par année.</p>
      {#each annexeByStruct as s}
        <div class="annexe-struct">
          <h4>{s.name}</h4>
          <div class="scrollx">
            <table class="annexe">
              <thead><tr><th>Année</th><th class="r">Solde de fonctionnement</th><th class="r">Subvention communale</th><th>Source</th></tr></thead>
              <tbody>
                {#each s.years as y}
                  <tr>
                    <td>{y.year}</td>
                    <td class="r">
                      {#if y.soldeVal != null}
                        <span class:neg={y.soldeVal < 0} class:pos={y.soldeVal >= 0}>{eurosC(y.soldeVal)}</span>
                        {#if y.soldeLbl}<span class="sublbl">{y.soldeLbl}</span>{/if}
                      {:else}—{/if}
                    </td>
                    <td class="r">{y.subvComm != null ? eurosC(y.subvComm) : '—'}</td>
                    <td class="src">{y.source}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          <details class="raw">
            <summary>Détail ligne à ligne</summary>
            <table>
              <thead><tr><th>Année</th><th>Section</th><th>Sens</th><th>Libellé</th><th class="r">Montant</th></tr></thead>
              <tbody>
                {#each s.years as y}{#each y.rows as r}
                  <tr><td>{r.year}</td><td>{r.section || ''}</td><td>{r.sens || ''}</td><td>{r.libelle || ''}</td><td class="r">{euros(r.montant)}</td></tr>
                {/each}{/each}
              </tbody>
            </table>
          </details>
        </div>
      {/each}
    {/if}

    <p class="foot">Sources : comptes administratifs DGFiP (détail par compte), agrégats OFGL (€/habitant), délibérations budgétaires du CM (budgets votés {voteYears.length ? voteYears.slice().sort((a,b)=>a-b).join(', ') : '—'}). Les agrégats OFGL couvrent {ofglYears.length ? `${Math.min(...ofglYears)}–${Math.max(...ofglYears)}` : '—'} ; le détail par compte court jusqu'à {lastDetailYear ?? '—'}.</p>
  {/if}
</section>

<style>
  .pop-note { margin: -.25rem 0 1rem; font-size: .78rem; color: var(--gris-clair); line-height: 1.5; max-width: 60ch; }
  .pop-note a { color: var(--ardoise); }

  .evolution { margin: .25rem 0 1rem; font-size: .92rem; color: var(--gris); line-height: 1.6; }
  .evolution b { color: var(--encre); font-variant-numeric: tabular-nums; }
  .courants { display: block; margin-top: .3rem; font-size: .76rem; color: var(--gris-clair); }
  .lecture {
    margin: .5rem 0 1.5rem; padding: .7rem .9rem;
    border-left: 3px solid var(--ambre); background: var(--ambre-pale);
    border-radius: 0 var(--rayon) var(--rayon) 0;
    font-size: .9rem; line-height: 1.55; color: var(--gris);
  }
  .lecture b { color: var(--encre); }
  .lecture a { color: var(--ardoise); }

  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }

  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0; }
  .year { color: var(--gris); font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; }
  select { padding: .4rem .6rem; border: 1px solid var(--trait); border-radius: 6px; font-size: .95rem; }

  /* Couleurs sémantiques (toujours doublées d'un libellé texte) */
  .in   { color: var(--recette); }
  .out  { color: var(--depense); }
  .save { color: var(--ardoise); }
  .debt { color: var(--ambre); }

  .lede { font-size: 1.05rem; line-height: 1.6; margin: 1.25rem 0 1.5rem; color: var(--gris); }
  .lede b { font-weight: 700; }

  /* Tuiles chiffres-clés */
  .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; margin-bottom: 1.75rem; }
  .tiles.small { margin-top: .75rem; }
  .tile { background: #fff; border: 1px solid var(--trait); border-top: 3px solid var(--trait); border-radius: 8px; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem; }
  .tile.in   { border-top-color: var(--recette); }
  .tile.out  { border-top-color: var(--depense); }
  .tile.save { border-top-color: var(--ardoise); }
  .tile.debt { border-top-color: var(--ambre); }
  .tlabel { font-size: .72rem; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
  .tval { font-size: 1.45rem; font-weight: 700; color: var(--encre); }
  .tsub { font-size: .78rem; color: var(--gris-clair); font-variant-numeric: tabular-nums; }

  h2 { color: var(--encre); margin: 1.75rem 0 .25rem; font-size: 1.15rem; }
  h3 { color: var(--encre); margin: 1.5rem 0 .5rem; font-size: 1rem; }
  h2.out-h { color: #b3312f; } h2.in-h { color: var(--recette); }
  .hint { color: var(--gris); font-size: .85rem; margin: 0 0 .9rem; }

  /* Équilibre */
  .equil { display: flex; flex-direction: column; gap: .5rem; margin-bottom: .5rem; }
  .erow { display: grid; grid-template-columns: 90px 1fr auto; align-items: center; gap: .75rem; }
  .ekey { font-size: .85rem; color: var(--gris); display: flex; align-items: center; gap: .4rem; white-space: nowrap; }
  .sw { width: 11px; height: 11px; border-radius: 3px; flex-shrink: 0; }
  .sw.in { background: var(--recette); } .sw.out { background: var(--depense); } .sw.save { background: var(--ardoise); }
  .etrack { background: var(--trait-pale); border-radius: 5px; height: 22px; overflow: hidden; }
  .efill { height: 100%; border-radius: 5px; }
  .efill.in { background: var(--recette); } .efill.out { background: var(--depense); } .efill.save { background: var(--ardoise); }
  .eval { font-variant-numeric: tabular-nums; font-weight: 700; font-size: .9rem; white-space: nowrap; }
  .save-row .ekey, .save-row .eval { color: var(--ardoise-fonce); }

  /* Deux colonnes dépenses / recettes */
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 1rem; }
  .bars { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .5rem; }
  .bars li { display: grid; grid-template-columns: 1fr; gap: .15rem; }
  .blabel { font-size: .82rem; color: var(--gris); }
  .btrack { display: block; background: var(--trait-pale); border-radius: 4px; height: 14px; overflow: hidden; }
  .bfill { display: block; height: 100%; border-radius: 4px; }
  .bfill.out { background: var(--depense); } .bfill.in { background: var(--recette); }
  .bval { font-size: .82rem; font-weight: 700; color: var(--encre); font-variant-numeric: tabular-nums; }
  .bpct { font-size: .75rem; color: var(--gris-clair); }
  .bars li { grid-template-columns: minmax(0, 1fr) 70px 42px; align-items: center; column-gap: .6rem; }
  .blabel { grid-column: 1 / -1; }
  .btrack { grid-column: 1; }
  .bval { grid-column: 2; text-align: right; }
  .bpct { grid-column: 3; text-align: right; }

  /* Tendance épargne */
  .trend { display: flex; align-items: flex-end; gap: .5rem; height: 130px; padding: .5rem 0; border-bottom: 1px solid var(--trait); }
  .tcol { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: .25rem; }
  .tbar { width: 60%; max-width: 34px; background: var(--ardoise); border-radius: 4px 4px 0 0; min-height: 4px; }
  .tbar.neg { background: var(--depense); }
  .tcol.cur .tbar { outline: 2px solid var(--ardoise-fonce); outline-offset: 1px; }
  .tbar-val { font-size: .68rem; color: var(--gris-clair); font-variant-numeric: tabular-nums; }
  .tyear { font-size: .72rem; color: var(--gris); }
  .tcol.cur .tyear { color: var(--encre); font-weight: 700; }

  details { margin-top: 1.25rem; border-top: 1px solid var(--trait); padding-top: .5rem; }
  summary { cursor: pointer; color: var(--gris); font-size: .9rem; font-weight: 600; padding: .35rem 0; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--ardoise-pale); }
  th { color: var(--gris); font-weight: 600; }
  .r { text-align: right; font-variant-numeric: tabular-nums; }

  /* Vues annualisées (agrégats + annexes) */
  h4 { margin: 1rem 0 .35rem; font-size: .95rem; color: var(--encre); }
  .secthead { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin: 1.75rem 0 .25rem; }
  .secthead h3 { margin: 0; }
  .seg { display: inline-flex; border: 1px solid var(--trait); border-radius: 6px; overflow: hidden; }
  .seg button { padding: .35rem .7rem; font-size: .8rem; background: #fff; color: var(--gris); border: none; border-left: 1px solid var(--trait); cursor: pointer; }
  .seg button:first-child { border-left: none; }
  .seg button.on { background: var(--ardoise); color: #fff; }
  .scrollx { overflow-x: auto; }
  table.matrix { min-width: 640px; }
  table.matrix th.ag, table.matrix td.ag { text-align: left; white-space: nowrap; max-width: 260px; overflow: hidden; text-overflow: ellipsis; position: sticky; left: 0; background: #fff; }
  table.matrix th { font-size: .78rem; }
  table.matrix td { font-size: .82rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
  table.matrix .grp td { background: var(--trait-pale); font-weight: 700; font-size: .74rem; text-transform: uppercase; letter-spacing: .03em; color: var(--gris); }
  table.matrix th.cur, table.matrix td.cur { background: var(--ardoise-pale); }
  table.matrix td.ag { color: var(--gris); }
  .annexe-struct { margin: .5rem 0 1.25rem; }
  table.annexe { min-width: 520px; font-size: .85rem; }
  table.annexe .neg { color: var(--depense); font-weight: 700; }
  table.annexe .pos { color: var(--recette); font-weight: 700; }
  table.annexe .sublbl { display: block; font-size: .72rem; color: var(--gris-clair); font-weight: 400; }
  table.annexe .src { color: var(--gris-clair); font-size: .76rem; }
  details.raw { margin-top: .4rem; border: none; padding: 0; }
  details.raw summary { font-size: .8rem; color: var(--gris); font-weight: 500; }

  .muted { color: var(--gris); }
  .note { background: var(--ambre-pale); border: 1px solid #eadfc6; color: var(--ambre); border-radius: 8px; padding: .6rem .8rem; font-size: .85rem; margin: 1rem 0; max-width: 80ch; }

  /* Budget voté (prévisionnel, source CR) */
  .votebanner { background: #eef2ff; border: 1px solid #c7d2fe; border-left: 3px solid var(--ardoise-fonce); color: var(--ardoise-fonce); border-radius: 8px; padding: .7rem .9rem; font-size: .88rem; line-height: 1.5; margin: 1.25rem 0 1.5rem; }
  .votebanner a { color: var(--ardoise-fonce); font-weight: 600; }
  .tile.vote { border-top-color: var(--ardoise); }
  .votelist { list-style: none; padding: 0; margin: .25rem 0 1rem; display: flex; flex-direction: column; gap: .4rem; }
  .votelist li { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: baseline; column-gap: .8rem; row-gap: .1rem; border-bottom: 1px solid var(--ardoise-pale); padding: .35rem 0; }
  .votelist .vname { font-weight: 600; color: var(--encre); font-size: .9rem; }
  .votelist .vval { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--ardoise-fonce); }
  .votelist .vnote { grid-column: 1 / -1; font-size: .78rem; color: var(--gris-clair); }
  .note b { font-weight: 700; }
  .foot { color: var(--gris-clair); font-size: .78rem; margin-top: 1.5rem; }

  @media (max-width: 720px) {
    .tiles { grid-template-columns: repeat(2, 1fr); }
    .cols { grid-template-columns: 1fr; gap: 1.25rem; }
  }
</style>
