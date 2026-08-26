<script>
  import { COMMUNE_DE, EPCI, EPCI_COURT, SITE_NOM } from '$lib/instance.js'
  import { euros } from '$lib/data.js'
  import Niveau from '$lib/components/Niveau.svelte'
  import FiltrePortee from '$lib/components/FiltrePortee.svelte'

  // Rendu au build par +page.server.js : le tableau est déjà dans le HTML.
  export let data
  $: marches = data.marches
  $: constat = data.constat

  let year = 'all'
  // Un marché de la communauté de communes n'est pas un marché de la commune,
  // même exécuté sur son territoire : ce ne sont ni le même budget ni le même
  // acheteur. La page les additionnait sans le dire. Par défaut « tout », parce
  // que la page compare les deux — le choix, lui, doit exister.
  let portee = 'tout'

  const yearOf = (m) => (m.date_notif || '').slice(0, 4)
  const isAttrib = (m) => m.titulaire_nom && m.montant
  const sum = (L) => L.reduce((s, m) => s + (m.montant || 0), 0)

  // Étiquette de source compacte + libellé long.
  function srcTag(s) {
    s = s || ''
    if (s.startsWith('CR')) return 'CR'
    if (s.startsWith('DECP')) return 'DECP'
    if (s.startsWith('BOAMP')) return 'BOAMP'
    if (s.includes('caussesaigoual')) return `${EPCI_COURT}`
    return s.slice(0, 8)
  }

  $: comptePortee = marches.reduce(
    (a, m) => { const p = m.portee || 'territoire'; a[p] = (a[p] || 0) + 1; return a }, {})
  $: dansPortee = portee === 'tout'
    ? marches : marches.filter(m => (m.portee || 'territoire') === portee)
  $: yearsAvail = [...new Set(dansPortee.map(yearOf).filter(Boolean))].sort((a, b) => b - a)
  $: base = dansPortee.filter(m => year === 'all' || yearOf(m) === year)
  $: attribues = base.filter(isAttrib).sort((a, b) => (b.montant || 0) - (a.montant || 0))
  $: avis = base.filter(m => !isAttrib(m))
  $: totalAttrib = sum(attribues)
  $: attribMax = Math.max(...attribues.map(m => m.montant || 0), 1)
  $: acheteurs = [...new Set(marches.map(m => m.acheteur_nom).filter(Boolean))]
  $: periode = yearsAvail.length ? `${yearsAvail[yearsAvail.length - 1]}–${yearsAvail[0]}` : '—'

  // Nombre de marchés attribués par an (vue annualisée).
  $: attribByYear = (() => {
    const m = new Map()
    for (const y of yearsAvail) m.set(y, { year: y, n: 0, montant: 0 })
    for (const mk of marches.filter(isAttrib)) {
      const y = yearOf(mk); if (!m.has(y)) m.set(y, { year: y, n: 0, montant: 0 })
      m.get(y).n++; m.get(y).montant += mk.montant || 0
    }
    return [...m.values()].filter(d => d.n).sort((a, b) => a.year.localeCompare(b.year))
  })()
  $: yrMontantMax = Math.max(...attribByYear.map(d => d.montant), 1)

  function eurosC(n) {
    if (n == null) return '—'
    const a = Math.abs(n)
    if (a >= 1e6) return (n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€'
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString('fr-FR') + ' k€'
    return euros(n)
  }
</script>

<svelte:head>
  <title>Marchés publics — {SITE_NOM}</title>
  <meta name="description" content="Marchés publics de la commune {COMMUNE_DE} et de la {EPCI} : attributions, titulaires, montants — recensés dans les délibérations et les données ouvertes." />
</svelte:head>

<section>
  <header class="head">
    <div>
      <h1>Marchés publics</h1>
      <p class="sub">Qui obtient les marchés de la commune et de l'intercommunalité — travaux, études, fournitures. Attributions recensées dans les délibérations du conseil municipal et les données ouvertes.</p>
    </div>
    {#if yearsAvail.length}
      <label class="year">Année
        <select bind:value={year}>
          <option value="all">Toutes</option>
          {#each yearsAvail as y}<option value={y}>{y}</option>{/each}
        </select>
      </label>
    {/if}
  </header>

  {#if marches.length}
    <FiltrePortee bind:valeur={portee} compte={comptePortee}
      libelleTerritoire="Autres acheteurs"
      aide="L'acheteur donne la portée, jamais le titulaire : une entreprise
            extérieure qui remporte un marché de la commune ne le rend pas
            extérieur." />
  {/if}

  {#if !marches.length}<p class="err">Aucun marché dans ce jeu de données.</p>{/if}

  {#if marches.length}
    <!-- Aucun document ne dit « 2,57 M€ de marchés sur 2016-2026 » : c'est une
         somme que nous faisons, et elle vaut ce que vaut la collecte. Un
         marché non recensé ne s'y voit pas. -->
    <Niveau type="calcul" base="les marchés recensés dans les délibérations et les données ouvertes">
      Sur la période <b>{periode}</b>, <b>{dansPortee.filter(isAttrib).length}</b> marchés attribués sont recensés
      (titulaire et montant connus), pour <b>{eurosC(sum(dansPortee.filter(isAttrib)))}</b>,
      auxquels s'ajoutent <b>{dansPortee.filter(m => !isAttrib(m)).length}</b> avis de consultation.
      {#if constat}
        <br />
        <b>{constat.pourMoitie}</b> titulaires réunissent à eux seuls
        <b>{constat.partMoitie} %</b> des montants attribués, répartis entre
        <b>{constat.titulaires}</b> entreprises différentes.
      {/if}
    </Niveau>

    {#if constat}
      <!-- Le chiffre de concentration est juste, et il induirait en erreur seul :
           22 titulaires pour 24 marchés, la concentration est en MONTANT et non
           en fréquence. Quelques chantiers coûtent simplement beaucoup plus cher
           que des fournitures. Le dire ici, et pas dans une note de méthode. -->
      <p class="lecture">
        <b>Ce que ce chiffre ne dit pas.</b>
        La concentration porte sur les montants, pas sur la fréquence&nbsp;:
        {constat.titulaires} entreprises différentes se partagent
        {constat.attribues} marchés, et
        {#if constat.recurrents === 0}
          aucune n'en a obtenu plus d'un.
        {:else}
          {constat.recurrents} seulement en {constat.recurrents > 1 ? 'ont' : 'a'} obtenu
          plus d'un.
        {/if}
        Quelques chantiers de voirie ou de réseaux coûtent simplement beaucoup
        plus cher qu'une fourniture. Une attribution répétée ne serait d'ailleurs
        pas en soi une irrégularité&nbsp;: dans une commune de mille habitants, le
        nombre d'entreprises capables de répondre est faible.
      </p>
    {/if}

    <div class="tiles">
      <div class="tile amt">
        <span class="tlabel">Marchés attribués</span>
        <span class="tval">{eurosC(totalAttrib)}</span>
        <span class="tsub">{attribues.length} marché(s){year !== 'all' ? ` · ${year}` : ''}</span>
      </div>
      <!-- « 78 marchés » est annoncé sur l'accueil, mais 24 seulement ont un
           titulaire et un montant connus. Sans cette ligne, l'écart entre les
           deux chiffres passe pour une incohérence. -->
      <div class="tile">
        <span class="tlabel">Recensés au total</span>
        <span class="tval">{base.length}</span>
        <span class="tsub">dont {attribues.length} attribué{attribues.length > 1 ? 's' : ''} · {avis.length} avis / consultations</span>
      </div>
      <div class="tile">
        <span class="tlabel">Acheteurs</span>
        <span class="tval">{acheteurs.length}</span>
        <span class="tsub">commune &amp; intercommunalité</span>
      </div>
    </div>

    <!-- Marchés attribués -->
    {#if attribues.length}
      <h2>Marchés attribués</h2>
      <p class="hint">Titulaire et montant connus — {eurosC(totalAttrib)}{year !== 'all' ? ` en ${year}` : ` sur ${periode}`}.</p>
      <ul class="mlist">
        {#each attribues as m (m.id)}
          <li>
            <div class="mtop">
              <span class="mobjet">{m.objet || 'Marché'}</span>
              <span class="mamt">{eurosC(m.montant)}</span>
            </div>
            <div class="mbar"><span class="mfill" style="width:{100 * (m.montant || 0) / attribMax}%"></span></div>
            <div class="mmeta">
              <span class="mtit">{#if m.titulaire_id}<a href="/entite/{m.titulaire_id}">{m.titulaire_nom}</a>{:else}{m.titulaire_nom}{/if}</span>
              {#if m.nature}<span class="chip">{m.nature}</span>{/if}
              {#if m.procedure}<span class="chip light">{m.procedure}</span>{/if}
              <span class="macheteur">{m.acheteur_nom}</span>
              {#if m.date_notif}<span class="mdate">{m.date_notif}</span>{/if}
              {#if m.source_url}<a class="msrc" class:cr={srcTag(m.source) === 'CR'} href={m.source_url} target="_blank" rel="noopener">{srcTag(m.source)} ↗</a>{:else}<span class="msrc">{srcTag(m.source)}</span>{/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- Vue annualisée -->
    {#if attribByYear.length > 1 && year === 'all'}
      <h3>Marchés attribués par an</h3>
      <div class="trend">
        {#each attribByYear as d}
          <div class="tcol" title="{d.year} : {d.n} marché(s), {eurosC(d.montant)}">
            <span class="tbar-val">{eurosC(d.montant)}</span>
            <span class="tbar" style="height:{Math.max(6, 100 * d.montant / yrMontantMax)}%"></span>
            <span class="tyear">{d.year}</span>
            <span class="tn">{d.n}</span>
          </div>
        {/each}
      </div>
    {/if}

    <!-- Avis / consultations -->
    {#if avis.length}
      <details>
        <summary>Avis de consultation &amp; appels d'offres recensés ({avis.length})</summary>
        <p class="hint">Avis et consultations lancées, sans attribution encore connue : le titulaire ne figure pas dans la source.
          Quand la délibération vote une enveloppe prévisionnelle, elle est indiquée — c'est une estimation, pas un prix payé,
          et elle n'entre pas dans le total des marchés attribués.</p>
        <table>
          <thead><tr><th>Date</th><th>Objet</th><th class="r">Enveloppe</th><th>Acheteur</th><th>Source</th></tr></thead>
          <tbody>
            {#each avis as m (m.id)}
              <tr>
                <td>{m.date_notif || '—'}</td>
                <td>{m.objet || '—'}</td>
                <td class="r">{m.montant ? eurosC(m.montant) : '—'}</td>
                <td>{m.acheteur_nom || '—'}</td>
                <td>{#if m.source_url}<a href={m.source_url} target="_blank" rel="noopener">{srcTag(m.source)} ↗</a>{:else}{srcTag(m.source)}{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </details>
    {/if}

    <p class="apart">
      Le conseil vote aussi des <a href="/projets-approuves">plans de financement</a> — participations
      à des travaux d'éclairage public ou d'électrification — où aucune entreprise n'est retenue.
      Ce ne sont pas des marchés attribués : ils sont recensés à part.
    </p>

    <p class="foot">
      Sources : délibérations du conseil municipal (choix d'entreprises, maîtrise d'œuvre — <b>seule source pour les marchés sous le seuil de publication</b>),
      DECP (données essentielles de la commande publique, ≥ 40 k€), BOAMP et site de la {EPCI}.
      Une commune de cette taille passant surtout des marchés sous le seuil DECP, les CR du CM sont la source la plus complète — provisoirement l'unique pour plusieurs marchés.
    </p>
  {/if}
</section>

<style>
  /* Une lecture n'est pas un fait : elle porte l'ambre des mises en garde,
     comme le niveau « interprétation » du reste du site. */
  .lecture {
    margin: .5rem 0 1.5rem; padding: .7rem .9rem;
    border-left: 3px solid var(--ambre); background: var(--ambre-pale);
    border-radius: 0 var(--rayon) var(--rayon) 0;
    font-size: .9rem; line-height: 1.55; color: var(--gris);
  }
  .lecture b { color: var(--encre); }

  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  .apart { margin-top: 1.75rem; background: var(--ardoise-pale); border: 1px solid var(--ardoise-pale);
           border-left: 3px solid var(--ardoise); border-radius: 8px; padding: .7rem .9rem;
           font-size: .87rem; color: var(--gris); line-height: 1.55; max-width: 80ch; }
  .apart a { color: var(--ardoise-fonce); font-weight: 600; }
  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0; max-width: 64ch; }
  .year { color: var(--gris); font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; }
  select { padding: .4rem .6rem; border: 1px solid var(--trait); border-radius: 6px; font-size: .95rem; }

  .amt { color: var(--ambre); }

  .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin-bottom: 1.75rem; }
  .tile { background: #fff; border: 1px solid var(--trait); border-top: 3px solid var(--trait); border-radius: 8px; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem; }
  .tile.amt { border-top-color: var(--ambre); }
  .tlabel { font-size: .72rem; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
  .tval { font-size: 1.45rem; font-weight: 700; color: var(--encre); }
  .tsub { font-size: .78rem; color: var(--gris-clair); }

  h2 { margin: 1.75rem 0 .25rem; font-size: 1.15rem; }
  h3 { margin: 1.75rem 0 .5rem; font-size: 1rem; }
  .hint { color: var(--gris); font-size: .85rem; margin: 0 0 .9rem; }

  .mlist { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: .9rem; }
  .mlist li { border: 1px solid var(--trait); border-radius: 10px; padding: .75rem .9rem; }
  .mtop { display: flex; justify-content: space-between; align-items: baseline; gap: .8rem; }
  .mobjet { font-weight: 600; color: var(--encre); font-size: .95rem; }
  .mamt { font-weight: 700; color: var(--ambre); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .mbar { background: var(--trait-pale); border-radius: 4px; height: 8px; overflow: hidden; margin: .45rem 0 .55rem; }
  .mfill { display: block; height: 100%; background: var(--ambre); border-radius: 4px; }
  .mmeta { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .6rem; font-size: .8rem; color: var(--gris); }
  .mtit { font-weight: 600; color: var(--gris); }
  .mtit a { color: var(--ardoise-fonce); }
  .chip { background: var(--trait-pale); color: var(--gris); border-radius: 99px; padding: .05rem .5rem; font-size: .72rem; font-weight: 600; }
  .chip.light { background: #fff; border: 1px solid var(--trait); font-weight: 500; }
  .macheteur { color: var(--gris); }
  .mdate { color: var(--gris-clair); font-variant-numeric: tabular-nums; }
  .msrc { margin-left: auto; color: var(--gris); font-weight: 600; font-size: .74rem; border: 1px solid var(--trait); border-radius: 99px; padding: .05rem .5rem; }
  .msrc.cr { color: var(--recette); border-color: #bbf7d0; background: #e7f0ea; }

  .trend { display: flex; align-items: flex-end; gap: .6rem; height: 150px; padding: .5rem 0; border-bottom: 1px solid var(--trait); }
  .tcol { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: .2rem; }
  .tbar { width: 60%; max-width: 40px; background: var(--ambre); border-radius: 4px 4px 0 0; min-height: 6px; }
  .tbar-val { font-size: .68rem; color: var(--gris-clair); font-variant-numeric: tabular-nums; }
  .tyear { font-size: .74rem; color: var(--gris); }
  .tn { font-size: .68rem; color: var(--ambre); font-weight: 700; }

  details { margin-top: 1.5rem; border-top: 1px solid var(--trait); padding-top: .5rem; }
  summary { cursor: pointer; color: var(--gris); font-size: .9rem; font-weight: 600; padding: .35rem 0; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--ardoise-pale); vertical-align: top; }
  th { color: var(--gris); font-weight: 600; }
  td a { color: var(--ardoise-fonce); }

  .foot { color: var(--gris-clair); font-size: .78rem; margin-top: 1.5rem; max-width: 74ch; line-height: 1.5; }

  @media (max-width: 720px) { .tiles { grid-template-columns: 1fr; } }
</style>
