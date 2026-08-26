<script>
  import { COMMUNE, EPCI, EPCI_COURT } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // Accueil refondu le 11/08/2026. C'était une carte plein écran : 1 135 points
  // en quatre couleurs, un encart flottant, et rien qui dise ce qu'est ce site
  // ni ce qu'on peut y chercher. La carte devient /carte ; l'accueil annonce,
  // oriente, puis montre ce qui vient de bouger.
  export let data
  $: ({ chiffres, budget, recents, agenda, arreteLe, interco } = data)

  const GENRES = {
    acte:      { label: 'Acte public',     classe: 'g-acte' },
    'marché':  { label: 'Marché public',   classe: 'g-marche' },
    argent:    { label: 'Argent public',   classe: 'g-argent' },
    'légal':   { label: 'Annonce légale',  classe: 'g-legal' },
    vie:       { label: 'Vie locale',      classe: 'g-vie' },
  }

  const nombre = (n) => (n == null ? '—' : n.toLocaleString('fr-FR'))

  // Les titres BODACC finissent par la date de l'annonce, déjà affichée dans sa
  // propre colonne : « … — la commune (2026-08-09) » devient « … — la commune ».
  const titre = (t) => (t || '').replace(/\s*\(\d{4}-\d{2}-\d{2}\)\s*$/, '')
  const millions = (n) =>
    n == null ? '—'
    : n >= 1e6 ? `${(n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} M€`
    : `${Math.round(n / 1e3).toLocaleString('fr-FR')} k€`

  const jour = (d) => {
    if (!d) return ''
    const dt = new Date(d + 'T00:00:00')
    return dt.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  }
  const dateLongue = (d) =>
    d ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : ''
</script>

<svelte:head>
  <title>{COMMUNE} au clair — la commune par les données publiques</title>
  <meta name="description" content="Qui décide, où va l'argent, qui agit : {COMMUNE} et son intercommunalité, la {EPCI}, à partir des seules données publiques." />
</svelte:head>

<section class="hero">
  <div class="pitch">
    <h1>{COMMUNE}, au clair.</h1>
    <p>
      <!-- « L'intercommunalité qui décide à sa place » était percutant mais
           juridiquement faux : les compétences sont transférées par la loi ou
           par délibération, elles ne sont pas confisquées. Pour un site de
           vigilance, la précision doit gagner contre l'effet de manche. -->
      Qui décide, où va l'argent, qui agit&nbsp;: la commune et l'intercommunalité
      qui exerce certaines compétences pour elle, reconstitués à partir des
      seules données publiques.
    </p>
    <!-- Cette page ne montre QUE la commune. L'intercommunalité décide aussi
         pour elle, et sur des compétences lourdes — mais ce n'est ni le même
         conseil ni le même bulletin de vote, et les additionner sous le mot
         « délibérations » laissait croire à un conseil municipal deux fois plus
         actif. Le renvoi est là pour qu'aucune moitié ne se perde. -->
    {#if interco?.deliberations}
      <p class="cadrage">
        Ces chiffres sont ceux <b>de la commune</b>. La {EPCI} en décide
        {interco.deliberations.toLocaleString('fr-FR')} de plus pour elle&nbsp;:
        <a href="/com-com">voir ce que décide la {EPCI_COURT}</a>.
      </p>
    {/if}
    <div class="chiffres">
      <span class="chiffre"><b>{nombre(chiffres.acteurs)}</b><span>acteurs recensés</span></span>
      <span class="chiffre"><b>{nombre(chiffres.deliberations)}</b><span>délibérations</span></span>
      <span class="chiffre"><b>{nombre(chiffres.marches)}</b><span>marchés</span></span>
      {#if budget}
        <span class="chiffre"><b>{millions(budget.recettes)}</b><span>budget {budget.annee}</span></span>
      {/if}
    </div>
    <!-- Pas de badge « Calcul » ici : ces quatre chiffres n'ont pas la même
         nature. Les trois premiers sont nos comptes — ils valent ce que vaut la
         collecte. Le budget est un agrégat publié par OFGL, plus solide que ce
         que nous savons produire. Un badge unique mentirait sur l'un des deux,
         et le hero n'est pas l'endroit pour trois étiquettes. La phrase le dit
         en clair, chaque page de destination porte ensuite sa qualification. -->
    <p class="provenance">
      Les trois premiers chiffres sont ceux que notre collecte a trouvés&nbsp;;
      le budget est l'agrégat publié par l'Observatoire des finances locales.
      <a href="/methode">Comment nous distinguons un fait d'un calcul</a>
    </p>
  </div>

  <a class="teaser" href="/carte">
    <svg viewBox="0 0 320 190" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <path d="M-10 120 C 60 100, 90 140, 150 125 S 260 90, 330 110" fill="none" stroke="#c3d3d8" stroke-width="2.5" />
      <path d="M-10 60 C 70 70, 120 40, 190 55 S 280 80, 330 60" fill="none" stroke="#dfe4de" stroke-width="1.5" />
      <g fill="#14556b" opacity=".85">
        <circle cx="150" cy="112" r="4" /><circle cx="161" cy="105" r="3" />
        <circle cx="142" cy="120" r="3" /><circle cx="169" cy="118" r="2.5" />
        <circle cx="133" cy="108" r="2.5" /><circle cx="157" cy="126" r="2.5" />
      </g>
      <g fill="#2c6e4f" opacity=".75">
        <circle cx="96" cy="86" r="3" /><circle cx="212" cy="72" r="3" />
        <circle cx="248" cy="128" r="2.5" /><circle cx="74" cy="142" r="2.5" />
        <circle cx="188" cy="148" r="2.5" />
      </g>
      <g fill="#9a6b12" opacity=".7">
        <circle cx="118" cy="60" r="2.5" /><circle cx="272" cy="96" r="2.5" />
        <circle cx="52" cy="104" r="2.5" /><circle cx="228" cy="42" r="2" />
      </g>
    </svg>
    <span class="teaser-cta">
      <Icon name="acteurs" size={15} />
      <!-- « 1 807 acteurs » en haut de page et « 795 sur la carte » ici : le
           même mot, deux nombres, et le lecteur conclut au bug. L'écart est
           réel et légitime (tous les acteurs n'ont pas de localisation
           publique fiable), il suffit de le dire à l'endroit où il se voit. -->
      Explorer les {nombre(chiffres.surCarte)} acteurs localisables sur la carte
      <Icon name="fleche" size={15} />
    </span>
  </a>
</section>

<section class="portes">
  <a class="porte" href="/qui-decide">
    <span class="porte-titre"><Icon name="decide" size={18} />Qui décide&nbsp;?</span>
    <p>Le conseil, l'intercommunalité, les commissions et les liens entre acteurs.</p>
    <span class="porte-n">{nombre(chiffres.deliberations)} délibérations publiées</span>
  </a>
  <a class="porte" href="/argent">
    <span class="porte-titre"><Icon name="argent" size={18} />Où va l'argent&nbsp;?</span>
    <p>Budget, impôts, subventions, marchés publics et transactions foncières.</p>
    <span class="porte-n">
      {#if budget}{millions(budget.depenses)} dépensés en {budget.annee} · {/if}{nombre(chiffres.marches)} marchés
    </span>
  </a>
  <a class="porte" href="/acteurs-publics">
    <span class="porte-titre"><Icon name="acteurs" size={18} />Qui agit&nbsp;?</span>
    <p>Entreprises, associations, services publics et lieux de la commune — et, au choix, ceux de l'intercommunalité.</p>
    <!-- 327 + 966 ne fait pas 1 807 : les services publics, lieux et personnes
         complètent le total. Annoncer « parmi » évite au lecteur de tenter
         l'addition et de conclure qu'il manque des acteurs. -->
    <span class="porte-n">parmi lesquels {nombre(chiffres.associations)} associations et {nombre(chiffres.entreprises)} entreprises</span>
  </a>
</section>

{#if recents.length}
  <section class="flux">
    <header>
      <h2>Ce que la commune vient de décider</h2>
      {#if arreteLe}<span class="arrete">données arrêtées au {dateLongue(arreteLe)}</span>{/if}
      <a class="tout" href="/nouveautes">Tout le flux <Icon name="fleche" size={14} /></a>
    </header>
    <ul>
      {#each recents as item}
        <li>
          <time datetime={item.date}>{jour(item.date)}</time>
          <!-- `id` désigne l'événement, pas un acteur : pas de lien vers une
               fiche. La seule cible utile est la source d'origine. -->
          <span class="titre">
            {#if item.url}
              <a href={item.url} target="_blank" rel="noopener">{titre(item.titre)}</a>
            {:else}{titre(item.titre)}{/if}
          </span>
          <span class="genre {GENRES[item.genre]?.classe || ''}">{GENRES[item.genre]?.label || item.genre}</span>
        </li>
      {/each}
    </ul>
    {#if interco?.recents}
      <p class="ailleurs">
        Sur la même période, la {EPCI_COURT} a pris
        {interco.recents.toLocaleString('fr-FR')} décisions qui engagent aussi
        la commune. <a href="/deliberations">Les voir avec les autres actes</a>
      </p>
    {/if}
  </section>
{/if}

<!-- L'agenda garde sa place, mais après la décision publique et sous son propre
     nom. Mélangé au reste et trié par date, il occupait tout le fil. -->
{#if agenda?.length}
  <section class="flux agenda">
    <header>
      <h2>Et dans la vie de la commune</h2>
      <a class="tout" href="/vie-locale">L'agenda <Icon name="fleche" size={14} /></a>
    </header>
    <ul>
      {#each agenda as item}
        <li>
          <time datetime={item.date}>{jour(item.date)}</time>
          <span class="titre">
            {#if item.url}
              <a href={item.url} target="_blank" rel="noopener">{titre(item.titre)}</a>
            {:else}{titre(item.titre)}{/if}
          </span>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<section class="contexte">
  <h2>Pour situer les chiffres</h2>
  <div class="secondaires">
    <a href="/territoire"><Icon name="territoire" size={17} />
      <span><strong>Le territoire</strong><small>Population, logement, revenus et emploi depuis 1968.</small></span></a>
    <a href="/environnement"><Icon name="environnement" size={17} />
      <span><strong>Environnement</strong><small>Qualité des cours d'eau, risques naturels, installations classées.</small></span></a>
    <a href="/vie-locale"><Icon name="vie" size={17} />
      <span><strong>Vie locale</strong><small>Événements, manifestations et vie associative locale.</small></span></a>
    <a href="/comprendre"><Icon name="comprendre" size={17} />
      <span><strong>Comprendre</strong><small>Méthode, sources, fiabilité : comment ce site est fabriqué.</small></span></a>
  </div>
</section>

<style>
  /* Le cadrage de périmètre : une phrase, pas un bandeau. Elle doit se lire
     avant les chiffres sans leur voler la vedette. */
  .cadrage {
    margin: .6rem 0 0; font-size: .88rem; color: var(--gris);
    border-left: 3px solid var(--trait); padding-left: .7rem;
  }
  .cadrage b { color: var(--encre); }
  .ailleurs {
    margin: .7rem 0 0; font-size: .85rem; color: var(--gris);
    border-top: 1px dashed var(--trait); padding-top: .6rem;
  }

  /* L'agenda est volontairement plus discret que le fil des décisions : même
     structure, moins de poids. */
  .flux.agenda { margin-top: 1.25rem; }
  .flux.agenda h2 { font-size: 1rem; color: var(--gris); }

  section { max-width: 1080px; margin: 0 auto; padding: 0 1.4rem; }

  /* ---------- hero ---------- */
  .hero {
    display: grid; grid-template-columns: 1.15fr .85fr; gap: 2.5rem;
    align-items: center; padding-top: 2.6rem; padding-bottom: 2rem;
  }
  .pitch h1 { font-size: clamp(2rem, 4.5vw, 2.9rem); line-height: 1.08; margin: 0 0 .6rem; }
  .pitch p { margin: 0 0 1.4rem; color: var(--gris); font-size: 1.02rem; max-width: 46ch; }

  .provenance {
    margin: .9rem 0 0; font-size: .78rem; line-height: 1.5; color: var(--gris);
    max-width: 46ch;
  }
  .provenance a { color: var(--ardoise); }

  .chiffres { display: flex; gap: 1.8rem; flex-wrap: wrap; }
  .chiffre { display: flex; flex-direction: column; }
  .chiffre b {
    font-family: var(--display); font-size: 1.7rem; line-height: 1;
    font-variant-numeric: tabular-nums; color: var(--encre);
  }
  .chiffre span {
    font-family: var(--data); font-size: .66rem; letter-spacing: .09em;
    text-transform: uppercase; color: var(--gris-clair); margin-top: .25rem;
  }

  .teaser {
    position: relative; display: block; overflow: hidden;
    border: 1px solid var(--trait); border-radius: var(--rayon);
    background: #eef1ec; height: 200px; color: inherit;
  }
  .teaser:hover { text-decoration: none; border-color: var(--ardoise); }
  .teaser svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .teaser-cta {
    position: absolute; left: 0; right: 0; bottom: 0;
    display: flex; align-items: center; gap: .4rem;
    padding: .55rem .75rem; background: rgba(255,255,255,.93);
    border-top: 1px solid var(--trait); font-size: .84rem; color: var(--ardoise);
  }

  /* ---------- portes ---------- */
  .portes { display: grid; grid-template-columns: repeat(3, 1fr); gap: .9rem; padding-bottom: 2.4rem; }
  .porte {
    display: flex; flex-direction: column; gap: .35rem;
    background: var(--blanc); border: 1px solid var(--trait);
    border-left: 3px solid var(--ardoise); border-radius: var(--rayon);
    padding: 1rem 1.1rem; color: inherit;
    transition: border-color .15s, box-shadow .15s;
  }
  .porte:hover { text-decoration: none; box-shadow: var(--ombre); border-color: var(--ardoise); }
  .porte-titre {
    display: flex; align-items: center; gap: .5rem;
    font-family: var(--display); font-size: 1.08rem; font-weight: 600; color: var(--encre);
  }
  .porte-titre :global(.icon) { color: var(--ardoise); }
  .porte p { margin: 0; font-size: .87rem; color: var(--gris); }
  .porte-n {
    margin-top: .45rem; padding-top: .5rem; border-top: 1px solid var(--trait-pale);
    font-family: var(--data); font-size: .72rem; color: var(--gris);
    font-variant-numeric: tabular-nums;
  }

  /* ---------- flux ---------- */
  .flux { padding-bottom: 2.6rem; }
  .flux header { display: flex; align-items: baseline; gap: .8rem; flex-wrap: wrap; margin-bottom: .7rem; }
  .flux h2 { font-size: 1.35rem; margin: 0; }
  .arrete { font-family: var(--data); font-size: .7rem; color: var(--gris-clair); }
  .tout { margin-left: auto; display: inline-flex; align-items: center; gap: .3rem; font-size: .85rem; }
  .flux ul { list-style: none; padding: 0; margin: 0; background: var(--blanc);
             border: 1px solid var(--trait); border-radius: var(--rayon); }
  .flux li {
    display: grid; grid-template-columns: 4.6rem 1fr auto; gap: .9rem; align-items: baseline;
    padding: .6rem .9rem; border-bottom: 1px solid var(--trait-pale);
  }
  .flux li:last-child { border-bottom: none; }
  .flux time { font-family: var(--data); font-size: .74rem; color: var(--gris-clair);
               font-variant-numeric: tabular-nums; }
  .flux .titre { font-size: .9rem; }
  .genre {
    font-family: var(--data); font-size: .64rem; letter-spacing: .05em; text-transform: uppercase;
    padding: .12rem .42rem; border-radius: 3px; white-space: nowrap; color: var(--gris);
    background: var(--trait-pale);
  }
  .g-acte, .g-marche { background: var(--ardoise-pale); color: var(--ardoise); }
  .g-argent { background: #e7f0ea; color: var(--recette); }
  .g-legal { background: var(--ambre-pale); color: var(--ambre); }
  .g-vie { background: #efeaf2; color: #62487a; }

  /* ---------- contexte ---------- */
  .contexte { padding-bottom: 3.5rem; }
  .contexte h2 { font-size: 1.15rem; margin: 0 0 .8rem; }
  .secondaires { display: grid; grid-template-columns: repeat(4, 1fr); gap: .7rem; }
  .secondaires a {
    display: flex; gap: .55rem; align-items: flex-start;
    padding: .75rem .85rem; background: var(--blanc);
    border: 1px solid var(--trait); border-radius: var(--rayon); color: inherit;
  }
  .secondaires a:hover { text-decoration: none; border-color: var(--ardoise); }
  .secondaires a :global(.icon) { color: var(--gris); margin-top: .15rem; }
  .secondaires span { display: flex; flex-direction: column; gap: .15rem; }
  .secondaires strong { font-size: .88rem; font-weight: 600; }
  .secondaires small { font-size: .78rem; color: var(--gris); line-height: 1.35; }

  @media (max-width: 900px) {
    .hero { grid-template-columns: 1fr; gap: 1.5rem; padding-top: 1.8rem; }
    .portes, .secondaires { grid-template-columns: 1fr; }
    .flux li { grid-template-columns: 4.6rem 1fr; row-gap: .2rem; }
    .genre { grid-column: 2; justify-self: start; }
  }
</style>
