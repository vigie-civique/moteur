<script>
  import Icon from '$lib/components/Icon.svelte'
  // « Comprendre » — la couche pédagogique (clé d'après CivLab).
  // Expliquer, pas seulement montrer : mission, mode d'emploi, institutions, fiabilité.
  const portes = [
    { icone: 'decide', t: 'Qui décide ?',     d: 'Les élus, le conseil, l\'intercommunalité et les réseaux de pouvoir.', href: '/qui-decide' },
    { icone: 'argent', t: "Où va l'argent ?", d: 'Le budget, les subventions, les marchés publics, le foncier.',          href: '/argent' },
    { icone: 'acteurs', t: 'Qui agit ?',       d: 'L\'annuaire des acteurs du territoire, et leur carte.',                  href: '/acteurs-publics' },
  ]
  const institutions = [
    { t: 'La commune de Lasalle',
      d: "Le conseil municipal, élu pour six ans, vote le budget et les grandes décisions. Le maire et ses adjoints les mettent en œuvre. Les délibérations sont des documents publics : c'est la trace écrite de ce qui est décidé en séance." },
    { t: "L'intercommunalité (CC Causses Aigoual Cévennes Terres Solidaires)",
      d: "Lasalle appartient à une communauté de communes qui exerce des compétences partagées (déchets, tourisme, développement…). Des délégués communaux y siègent. Une partie de l'argent public transite par cet échelon." },
    { t: "D'où vient l'argent public",
      d: "Recettes locales (impôts, taxes), dotations de l'État, subventions de la Région ou du Département. Il finance le fonctionnement, l'investissement et les subventions aux associations. Le détail chiffré est dans « Où va l'argent »." },
  ]
  const fiches = [
    { icone: 'argent', t: 'Le budget communal',        d: 'Fonctionnement, investissement, dette, budgets annexes — mode d\'emploi.', href: '/comprendre/budget' },
    { icone: 'decide', t: "L'intercommunalité",        d: 'La CC Causses Aigoual Cévennes Terres Solidaires : compétences, délégués, argent transféré.', href: '/comprendre/intercommunalite' },
    { icone: 'elections', t: 'Mandats & délibérations',   d: 'Conseil municipal, délégations, et comment lire une délibération.',         href: '/comprendre/mandats' },
  ]
  const liens = [
    { icone: 'recherche', t: 'Méthode & sources détaillées', d: 'Le tableau complet des sources et des licences.', href: '/methode' },
    { icone: 'document', t: 'Mentions légales',             d: 'Éditeur, hébergeur, cadre RGPD.',                  href: '/mentions-legales' },
    { icone: 'document', t: 'Droit de réponse',             d: 'Signaler une erreur, demander une rectification.', href: '/contact' },
  ]
</script>

<svelte:head>
  <title>Comprendre — Vigie Civique Lasalle</title>
  <meta name="description" content="Mode d'emploi du site, fonctionnement des institutions locales, fiabilité et sources des données de la veille citoyenne de Lasalle." />
</svelte:head>

<article class="page">
  <header class="intro">
    <h1 class="avec-icone"><Icon name="comprendre" size={26} />Comprendre</h1>
    <p class="lead">Ce site existe pour une raison simple : <strong>permettre à chaque habitant de Lasalle
       de comprendre qui décide quoi, et comment l'argent public est utilisé.</strong>
       Expliquer, pas seulement montrer.</p>
  </header>

  <section>
    <h2>Comment lire ce site</h2>
    <p>L'information est organisée par <strong>questions de citoyen</strong>, pas par tableaux de données.
       Trois portes d'entrée :</p>
    <div class="grid">
      {#each portes as p}
        <a class="card" href={p.href}>
          <Icon name={p.icone} size={22} />
          <h3>{p.t}</h3>
          <p>{p.d}</p>
        </a>
      {/each}
    </div>
  </section>

  <section>
    <h2>Comprendre les institutions</h2>
    <div class="stack">
      {#each institutions as i}
        <div class="explainer">
          <h3>{i.t}</h3>
          <p>{i.d}</p>
        </div>
      {/each}
    </div>
  </section>

  <section>
    <h2>Les fiches pédagogiques</h2>
    <div class="grid">
      {#each fiches as f}
        <a class="card" href={f.href}>
          <Icon name={f.icone} size={22} />
          <h3>{f.t}</h3>
          <p>{f.d}</p>
        </a>
      {/each}
    </div>
  </section>

  <section>
    <h2>Quelle confiance accorder aux données&nbsp;?</h2>
    <p>Toutes les informations proviennent de <strong>données publiques ouvertes</strong> (SIRENE, RNA, DVF,
       BODACC, OFGL, marchés publics, délibérations…). Chaque élément publié porte la
       <strong>source qui l'a produite</strong>, citée là où l'information apparaît.</p>
    <!-- Le badge « confirmé — recoupé par deux sources indépendantes » a été retiré
         le 12/08/2026 : aucune donnée ne l'a jamais porté. Cf. /methode. -->
    <p class="note">Les pistes de travail non établies ne sont <strong>jamais</strong> publiées,
       et aucune donnée personnelle privée n'est exposée.
       Le détail de la méthode, et ce que nous ne savons pas encore faire, sont sur la page
       <a href="/methode">Méthode &amp; sources</a>.</p>
  </section>

  <section>
    <h2>Aller plus loin</h2>
    <div class="grid">
      {#each liens as l}
        <a class="card" href={l.href}>
          <Icon name={l.icone} size={22} />
          <h3>{l.t}</h3>
          <p>{l.d}</p>
        </a>
      {/each}
    </div>
  </section>
</article>

<style>
  .page { max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem 3rem; line-height: 1.6; }
  .intro h1 { font-size: 1.9rem; margin: 0 0 .5rem; color: var(--encre); }
  .lead { color: var(--gris); font-size: 1.05rem; max-width: 65ch; }
  section { margin-top: 2rem; }
  h2 { color: var(--encre); font-size: 1.25rem; border-bottom: 1px solid var(--trait); padding-bottom: .35rem; }
  h3 { color: var(--encre); font-size: 1rem; margin: 0 0 .35rem; }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-top: 1rem; }
  .card {
    display: block; background: #fff; border: 1px solid var(--trait); border-radius: 12px;
    padding: 1.1rem; color: inherit; transition: border-color .15s, box-shadow .15s, transform .15s;
  }
  .card:hover { border-color: var(--ardoise); box-shadow: 0 6px 18px rgba(14,165,233,.12); transform: translateY(-2px); text-decoration: none; }
  .card :global(.icon) { color: var(--ardoise); }
  .card p { font-size: .88rem; color: var(--gris); margin: 0; }

  .stack { display: flex; flex-direction: column; gap: .75rem; margin-top: 1rem; }
  .explainer { background: var(--trait-pale); border-left: 3px solid var(--ardoise); border-radius: 0 8px 8px 0; padding: .85rem 1rem; }
  .explainer p { margin: 0; color: var(--gris); font-size: .92rem; }

  .note { background: var(--ambre-pale); border: 1px solid #eadfc6; border-radius: 8px; padding: .75rem 1rem; font-size: .9rem; color: #713f12; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
