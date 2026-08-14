<script>
  import { COMMUNE, COMMUNE_A, COMMUNE_DE, EPCI, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // « De combien sont mes impôts locaux, et comment on se situe ? » est la
  // première question d'un habitant. La base avait le budget et les comparatifs
  // OFGL depuis des mois, mais pas les taux votés : aucune page ne répondait.
  // Rendu au build par +page.server.js.
  export let data
  $: taux = data.taux
  $: annee = data.annee
  let annee = null

  // Distinction non négociable : la commune ne vote qu'une PART du taux.
  // Le reste vient de l'intercommunalité et des syndicats. Attribuer le taux
  // global au conseil municipal serait une erreur factuelle.
  const LIGNES = [
    { vote: 'TFB_VOTE',  global: 'TFB_GLOBAL',  label: 'Foncier bâti',
      aide: 'Payée par tout propriétaire d’un logement ou d’un local.' },
    { vote: 'TFNB_VOTE', global: 'TFNB_GLOBAL', label: 'Foncier non bâti',
      aide: 'Terrains, prés, bois. Taux élevés mais bases faibles en zone rurale.' },
    { vote: 'TH_VOTE',   global: 'TH_GLOBAL',   label: 'Habitation (2ᵉ résidence)',
      aide: 'La taxe d’habitation ne subsiste que sur les résidences secondaires.' },
    { vote: null,        global: 'TEOM',        label: 'Ordures ménagères',
      aide: 'Fixée au niveau intercommunal : la commune ne la vote pas.' },
  ]

  const val = (commune, indicateur, an = annee) =>
    taux.find(t => t.commune === commune && t.indicateur === indicateur && t.annee === an)?.taux ?? null

  $: communes = [...new Set(taux.map(t => t.commune))]
    .sort((a, b) => (val(b, 'TFB_VOTE') ?? 0) - (val(a, 'TFB_VOTE') ?? 0))
  $: annees = [...new Set(taux.map(t => t.annee))].sort()

  const pct = (v) => v == null ? '—' : `${v.toFixed(2)} %`
  // Évolution du taux communal de foncier bâti sur la période disponible.
  const evolution = (commune) => {
    if (!annees.length) return null
    const a = val(commune, 'TFB_VOTE', annees[0])
    const b = val(commune, 'TFB_VOTE', annees[annees.length - 1])
    if (a == null || b == null || a === 0) return null
    return ((b - a) / a) * 100
  }
</script>

<svelte:head>
  <title>Impôts locaux — {SITE_NOM}</title>
  <meta name="description" content="Taux d'imposition votés {COMMUNE_A} et dans les 15 communes de la {EPCI} : foncier bâti, foncier non bâti, taxe d'habitation, ordures ménagères." />
</svelte:head>

<section class="page">
  <header>
    <h1 class="avec-icone"><Icon name="impots" size={26} />Les impôts locaux</h1>
    <p class="chapeau">
      Ce que le conseil municipal vote, et ce que vous payez réellement.
      Les deux ne sont pas la même chose : à la part communale s'ajoutent celles
      de l'intercommunalité et des syndicats.
    </p>
  </header>

  {#if !taux.length}<p class="etat">Aucun taux disponible.</p>
  {:else if !taux.length}<p class="etat">Aucune donnée disponible.</p>
  {:else}
    <p class="source">
      Exercice {annee} · source : direction générale des finances publiques
      (fichiers de fiscalité directe locale) · données {annees[0]}–{annees[annees.length - 1]}
    </p>

    {#each LIGNES as ligne}
      <h2>{ligne.label}</h2>
      <p class="aide">{ligne.aide}</p>
      <div class="tableau">
        <table>
          <thead>
            <tr>
              <th>Commune</th>
              {#if ligne.vote}<th class="num">Part votée<br><small>par la commune</small></th>{/if}
              <th class="num">Taux total<br><small>tout compris</small></th>
              {#if ligne.vote}<th class="num">Évolution<br><small>{annees[0]}→{annees[annees.length - 1]}</small></th>{/if}
            </tr>
          </thead>
          <tbody>
            {#each communes as c}
              {@const v = ligne.vote ? val(c, ligne.vote) : null}
              {@const g = val(c, ligne.global)}
              {@const ev = ligne.vote === 'TFB_VOTE' ? evolution(c) : null}
              <tr class:phare={c === '{COMMUNE}'}>
                <td>{c}</td>
                {#if ligne.vote}<td class="num">{pct(v)}</td>{/if}
                <td class="num">{pct(g)}</td>
                {#if ligne.vote}
                  <td class="num">
                    {#if ev == null}—
                    {:else}<span class:hausse={ev > 0.5} class:stable={Math.abs(ev) <= 0.5}
                      >{ev > 0 ? '+' : ''}{ev.toFixed(1)} %</span>{/if}
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/each}

    <div class="note">
      <h3>Comment lire ces chiffres</h3>
      <p>
        Un taux ne se traduit pas directement en euros : il s'applique à la
        <strong>valeur locative cadastrale</strong> de chaque bien, révisée par
        l'État. Un taux plus élevé qu'ailleurs ne signifie donc pas
        mécaniquement un impôt plus élevé — mais il traduit un choix du conseil.
      </p>
      <p>
        La colonne « part votée » est la <strong>seule</strong> dont le conseil
        municipal est responsable. Le « taux total » inclut l'intercommunalité et
        les syndicats, sur lesquels la commune n'a qu'une voix parmi d'autres.
      </p>
      <p class="liens">
        <a href="/comprendre/budget">Comprendre le budget communal</a> ·
        <a href="/budgets">Le budget {COMMUNE_DE}</a> ·
        <a href="/methode">Méthode et sources</a>
      </p>
    </div>
  {/if}
</section>

<style>
  .page { max-width: 940px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; color: var(--encre); }
  .chapeau { color: var(--gris); max-width: 64ch; line-height: 1.55; margin: 0 0 1rem; }
  .source { font-size: .8rem; color: var(--gris-clair); margin: 0 0 2rem; }
  h2 { font-size: 1.15rem; margin: 2rem 0 .25rem; color: var(--encre); }
  .aide { font-size: .85rem; color: var(--gris); margin: 0 0 .75rem; }
  .etat { color: var(--gris); }

  .tableau { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .9rem; background: #fff;
          border: 1px solid var(--trait); border-radius: 10px; }
  th, td { padding: .55rem .7rem; text-align: left; border-bottom: 1px solid var(--ardoise-pale); }
  th { font-size: .78rem; color: var(--gris); font-weight: 600; background: var(--papier); }
  th small { font-weight: 400; color: var(--gris-clair); font-size: .7rem; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  tbody tr:last-child td { border-bottom: none; }
  tr.phare { background: var(--ardoise-pale); }
  tr.phare td:first-child { font-weight: 600; color: var(--ardoise-fonce); }
  .hausse { color: var(--ambre); }
  .stable { color: var(--gris); }

  .note { margin-top: 2.5rem; padding: 1.1rem 1.25rem; background: var(--papier);
          border: 1px solid var(--trait); border-left: 3px solid var(--ardoise); border-radius: 10px; }
  .note h3 { margin: 0 0 .5rem; font-size: 1rem; color: var(--encre); }
  .note p { margin: 0 0 .6rem; font-size: .88rem; line-height: 1.55; color: var(--gris); }
  .liens { font-size: .85rem; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
