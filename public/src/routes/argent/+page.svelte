<script>
  import { COMMUNE_DE, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // Hub « Où va l'argent ? » — les finances rendues lisibles.
  // Modèle NosFinancesLocales / Éclaireur Public : pédagogique, pas un export
  // comptable. Chaque carte porte depuis le 11/08/2026 le chiffre qu'elle
  // promet : six cartes muettes suivies de 500 px de blanc ne donnaient ni
  // envie de cliquer, ni la moindre idée de ce qu'on allait y trouver.
  export let data

  const nombre = (n) => (n == null ? '—' : n.toLocaleString('fr-FR'))
  const montant = (n) =>
    n == null ? '—'
    : Math.abs(n) >= 1e6 ? `${(n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} M€`
    : `${Math.round(n / 1e3).toLocaleString('fr-FR')} k€`

  $: cartes = [
    { icone: 'impots', titre: 'Les impôts locaux', href: '/impots',
      sub: "Taux votés par la commune et taux réellement payés, comparés aux communes de l'intercommunalité.",
      valeur: nombre(data.communes), unite: 'communes comparées' },
    { icone: 'argent', titre: 'Le budget de la commune', href: '/budgets',
      sub: 'Recettes, dépenses, épargne, dette — en clair, pas en jargon comptable.',
      valeur: montant(data.recettes), unite: `de recettes en ${data.annee}` },
    { icone: 'subventions', titre: 'Subventions & flux financiers', href: '/finances',
      sub: "Qui reçoit l'argent public : subventions, dotations, cessions de patrimoine.",
      valeur: nombre(data.beneficiaires), unite: 'bénéficiaires recensés' },
    { icone: 'marches', titre: 'Marchés publics', href: '/marches',
      sub: 'Qui obtient les marchés de la commune : travaux, études, fournitures.',
      valeur: nombre(data.marches), unite: 'marchés publiés' },
    { icone: 'urbanisme', titre: 'Foncier & urbanisme', href: '/urbanisme',
      sub: 'Transactions foncières (DVF) et la parcelle AD0180.',
      valeur: nombre(data.dvf), unite: data.dvfPeriode ? `transactions · ${data.dvfPeriode}` : 'transactions' },
    { icone: 'comprendre', titre: 'Comprendre le budget', href: '/comprendre/budget',
      sub: "Fonctionnement, investissement, épargne, dette : le mode d'emploi.",
      valeur: null, unite: 'Fiche pédagogique' },
  ]
</script>

<svelte:head>
  <title>Où va l'argent ? — {SITE_NOM}</title>
  <meta name="description" content="Les finances {COMMUNE_DE} rendues lisibles : budget, subventions, marchés publics et foncier." />
</svelte:head>

<section class="hub">
  <header class="intro">
    <Icon name="argent" size={28} />
    <div>
      <h1>Où va l'argent&nbsp;?</h1>
      <p>L'argent public rendu lisible : d'où viennent les recettes, où partent les dépenses,
         qui touche les subventions et qui obtient les marchés.</p>
    </div>
  </header>

  {#if data.recettes && data.depenses}
    <p class="resume">
      En <b>{data.annee}</b>, la commune a perçu <b class="in">{montant(data.recettes)}</b>
      et dépensé <b class="out">{montant(data.depenses)}</b> en fonctionnement.
    </p>
  {/if}

  <div class="grid">
    {#each cartes as c}
      <a class="card" href={c.href}>
        <span class="titre"><Icon name={c.icone} size={17} />{c.titre}</span>
        <p>{c.sub}</p>
        <span class="fig">
          {#if c.valeur}<b>{c.valeur}</b>{/if}{c.unite}
        </span>
      </a>
    {/each}
  </div>
</section>

<style>
  .hub { max-width: 1080px; margin: 0 auto; padding: 2.2rem 1.4rem 3.5rem; }
  .intro { display: flex; gap: .8rem; align-items: flex-start; margin-bottom: 1.2rem; }
  .intro :global(.icon) { color: var(--ardoise); margin-top: .35rem; }
  .intro h1 { font-size: 1.9rem; margin: 0 0 .3rem; }
  .intro p { color: var(--gris); max-width: 62ch; margin: 0; }

  .resume {
    margin: 0 0 1.4rem; padding: .7rem .9rem; background: var(--blanc);
    border: 1px solid var(--trait); border-left: 3px solid var(--ardoise);
    border-radius: var(--rayon); font-size: .95rem;
  }
  .resume b { font-variant-numeric: tabular-nums; }
  .resume .in { color: var(--recette); }
  .resume .out { color: var(--depense); }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: .9rem; }
  .card {
    display: flex; flex-direction: column; gap: .35rem;
    background: var(--blanc); border: 1px solid var(--trait); border-radius: var(--rayon);
    padding: 1rem 1.1rem; color: inherit; transition: border-color .15s, box-shadow .15s;
  }
  .card:hover { border-color: var(--ardoise); box-shadow: var(--ombre); text-decoration: none; }
  .titre {
    display: flex; align-items: center; gap: .5rem;
    font-family: var(--display); font-size: 1.05rem; font-weight: 600; color: var(--encre);
  }
  .titre :global(.icon) { color: var(--ardoise); }
  .card p { font-size: .87rem; color: var(--gris); margin: 0; }
  .fig {
    margin-top: auto; padding-top: .6rem; border-top: 1px solid var(--trait-pale);
    font-family: var(--data); font-size: .74rem; color: var(--gris);
    font-variant-numeric: tabular-nums;
  }
  .fig b {
    font-family: var(--display); font-size: 1.2rem; color: var(--encre);
    margin-right: .35rem; font-weight: 600;
  }
</style>
