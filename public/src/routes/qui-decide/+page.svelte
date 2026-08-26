<script>
  import { COMMUNE_DE, EPCI, EPCI_COURT, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // Hub « Qui décide ? » — la gouvernance et les réseaux de pouvoir.
  // Modèle LittleSis / SF Government Graph : le pouvoir se lit en relations.
  // Chaque carte annonce depuis le 11/08/2026 le volume qu'elle couvre.
  export let data

  const nombre = (n) => (n == null ? '—' : n.toLocaleString('fr-FR'))

  $: cartes = [
    { icone: 'elections', titre: 'Les élections', href: '/elections',
      sub: "Participation, voix et sièges : d'où vient le mandat de ceux qui décident.",
      valeur: nombre(data.communes), unite: 'communes · municipales 2026' },
    { icone: 'conseil', titre: 'Les conseils municipaux', href: '/elus',
      sub: `Maires, adjoints, conseillers et commissions ${COMMUNE_DE} et des communes de l'intercommunalité.`,
      valeur: nombre(data.elus), unite: 'élus en fonction' },
    { icone: 'intercommunalite', titre: `L'intercommunalité (${EPCI_COURT})`, href: '/com-com',
      sub: `Délégués ${COMMUNE_DE}, compétences, délibérations communautaires.`,
      valeur: nombre(data.deliberationsInterco), unite: 'actes votés par la CC' },
    { icone: 'document', titre: 'Délibérations & décisions', href: '/deliberations',
      sub: 'La chronologie des votes du conseil municipal.',
      valeur: nombre(data.deliberations), unite: 'actes du conseil municipal' },
    // « Graphe d'influence » faisait franchir au lecteur une étape que les
    // données ne permettent pas : une relation documentée n'établit pas une
    // influence. Le titre dit maintenant ce que la page montre réellement.
    { icone: 'graphe', titre: 'Les liens entre acteurs', href: '/graphe',
      sub: 'Qui est lié à qui — relations vérifiées uniquement.',
      valeur: nombre(data.relations), unite: 'liens vérifiés' },
    { icone: 'recherche', titre: 'Élus et structures subventionnées', href: '/elus-et-structures',
      sub: "Quand un élu dirige une structure qui reçoit de l'argent public : les déports constatés.",
      // « cas » + compteur se lit comme un score. « Situations documentées »
      // dit la même chose sans compter des points.
      valeur: nombre(data.conflits), unite: 'situations documentées' },
  ]
</script>

<svelte:head>
  <title>Qui décide ? — {SITE_NOM}</title>
  <meta name="description" content="La gouvernance {COMMUNE_DE} : élus, intercommunalité, délibérations et réseaux de pouvoir." />
</svelte:head>

<section class="hub">
  <header class="intro">
    <Icon name="decide" size={28} />
    <div>
      <h1>Qui décide&nbsp;?</h1>
      <p>La gouvernance locale et les réseaux de pouvoir. Qui détient les mandats, qui vote quoi,
         et comment les acteurs sont liés entre eux.</p>
    </div>
  </header>

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
  .intro { display: flex; gap: .8rem; align-items: flex-start; margin-bottom: 1.4rem; }
  .intro :global(.icon) { color: var(--ardoise); margin-top: .35rem; }
  .intro h1 { font-size: 1.9rem; margin: 0 0 .3rem; }
  .intro p { color: var(--gris); max-width: 62ch; margin: 0; }

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
