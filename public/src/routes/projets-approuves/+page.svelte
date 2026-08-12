<script>
  import { euros } from '$lib/data.js'

  // Rendu au build par +page.server.js.
  export let data
  $: approbations = data.approbations
  let year = 'all'

  const yearOf = (a) => (a.date || '').slice(0, 4)
  const sum = (L) => L.reduce((s, a) => s + (a.montant_ht || 0), 0)

  $: yearsAvail = [...new Set(approbations.map(yearOf).filter(Boolean))].sort((a, b) => b - a)
  $: base = approbations.filter(a => year === 'all' || yearOf(a) === year)
  $: totalHT = sum(base)
  $: maxHT = Math.max(...base.map(a => a.montant_ht || 0), 1)
  $: periode = yearsAvail.length
    ? `${yearsAvail[yearsAvail.length - 1]}–${yearsAvail[0]}` : '—'

  function eurosC(n) {
    if (n == null) return '—'
    const a = Math.abs(n)
    if (a >= 1e6) return (n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€'
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString('fr-FR') + ' k€'
    return euros(n)
  }
</script>

<svelte:head>
  <title>Projets approuvés — Vigie Civique Lasalle</title>
  <meta name="description" content="Plans de financement votés par le conseil municipal : participations de la commune aux opérations d'éclairage public et d'électrification." />
</svelte:head>

<section>
  <header class="head">
    <div>
      <h1>Projets approuvés</h1>
      <p class="sub">Les plans de financement votés par le conseil municipal — la commune approuve un projet
        et sa participation, sans qu'aucune entreprise ne soit encore retenue.</p>
    </div>
    {#if yearsAvail.length > 1}
      <label class="year">Année
        <select bind:value={year}>
          <option value="all">Toutes</option>
          {#each yearsAvail as y}<option value={y}>{y}</option>{/each}
        </select>
      </label>
    {/if}
  </header>

  <p class="note">
    <b>Ce n'est pas un marché.</b> Ces délibérations votent le principe d'une opération et son
    financement — le plus souvent une participation à des travaux d'éclairage public ou
    d'électrification portés par un syndicat. L'entreprise qui exécutera les travaux est choisie
    ailleurs, parfois par le syndicat lui-même. C'est pourquoi ces montants sont présentés à part
    des <a href="/marches">marchés attribués</a> : les additionner reviendrait à compter deux fois
    le même euro.
  </p>



  {#if approbations.length}
    <div class="tiles">
      <div class="tile">
        <span class="tlabel">Projets approuvés</span>
        <span class="tval">{base.length}</span>
        <span class="tsub">{year === 'all' ? periode : year}</span>
      </div>
      <div class="tile">
        <span class="tlabel">Montant voté (HT)</span>
        <span class="tval">{eurosC(totalHT)}</span>
        <span class="tsub">cumul des plans de financement</span>
      </div>
    </div>

    <ul class="liste">
      {#each base as a (a.id)}
        <li>
          <div class="ligne">
            <span class="date">{a.date}</span>
            <span class="objet">
              {a.objet}
              {#if a.maitre_ouvrage}<span class="mo">{a.maitre_ouvrage}</span>{/if}
            </span>
            <span class="montant">
              {eurosC(a.montant_ht)} <span class="base">HT</span>
              {#if a.montant_ttc}<span class="ttc">{eurosC(a.montant_ttc)} TTC</span>{/if}
            </span>
          </div>
          <div class="barre"><span style="width:{100 * (a.montant_ht || 0) / maxHT}%"></span></div>
          {#if a.citation}
            <details>
              <summary>Ce que dit la délibération</summary>
              <blockquote>{a.citation}</blockquote>
              {#if a.source_url}<a class="src" href={a.source_url} target="_blank" rel="noopener">Compte rendu ↗</a>{/if}
            </details>
          {/if}
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">Aucun projet approuvé recensé pour l'instant.</p>
  {/if}

  <p class="foot">
    Source : délibérations et comptes rendus du conseil municipal, relevés un par un.
    Chaque ligne est accompagnée de la phrase votée. Le recensement n'est pas exhaustif :
    il ne couvre que les actes mis en ligne par la commune et lisibles à la relecture.
  </p>
</section>

<style>
  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; color: var(--encre); }
  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
  h1 { margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0; max-width: 62ch; }
  .year { color: var(--gris); font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; }
  select { padding: .4rem .6rem; border: 1px solid var(--trait); border-radius: 6px; font-size: .95rem; }

  .note { background: var(--papier); border: 1px solid var(--trait); border-left: 3px solid var(--encre);
          border-radius: 8px; padding: .8rem 1rem; margin: 1.25rem 0; color: var(--gris);
          font-size: .9rem; line-height: 1.6; max-width: 80ch; }
  .note a { color: var(--ardoise-fonce); }

  .tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; margin-bottom: 1.75rem; max-width: 560px; }
  .tile { background: #fff; border: 1px solid var(--trait); border-top: 3px solid var(--ardoise); border-radius: 8px;
          padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem; }
  .tlabel { font-size: .72rem; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
  .tval { font-size: 1.45rem; font-weight: 700; }
  .tsub { font-size: .78rem; color: var(--gris-clair); }

  .liste { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1.1rem; }
  .ligne { display: grid; grid-template-columns: 90px minmax(0, 1fr) auto; gap: .8rem; align-items: baseline; }
  .date { font-size: .8rem; color: var(--ardoise); font-weight: 700; font-variant-numeric: tabular-nums; }
  .objet { font-size: .95rem; }
  .mo { display: inline-block; margin-left: .4rem; font-size: .68rem; font-weight: 700; color: var(--ardoise-fonce);
        background: var(--ardoise-pale); border-radius: 999px; padding: .1rem .45rem; vertical-align: middle; }
  .montant { text-align: right; font-weight: 700; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .base { font-size: .7rem; color: var(--gris); font-weight: 600; }
  .ttc { display: block; font-size: .72rem; color: var(--gris-clair); font-weight: 500; }

  .barre { height: 6px; background: var(--trait-pale); border-radius: 4px; overflow: hidden; margin: .35rem 0 0; }
  .barre span { display: block; height: 100%; background: var(--ardoise); border-radius: 4px; }

  details { margin-top: .4rem; }
  summary { cursor: pointer; color: var(--gris); font-size: .82rem; padding: .2rem 0; }
  blockquote { margin: .4rem 0 .3rem; padding-left: .8rem; border-left: 2px solid var(--trait);
               color: var(--gris); font-size: .85rem; line-height: 1.55; }
  .src { font-size: .8rem; color: var(--ardoise-fonce); }

  .foot { color: var(--gris-clair); font-size: .78rem; margin-top: 2rem; max-width: 72ch; }

  @media (max-width: 640px) {
    .tiles { grid-template-columns: 1fr; }
    .ligne { grid-template-columns: 1fr; }
    .montant { text-align: left; }
  }
</style>
