<script>
  import { COMMUNE, EPCI, EPCI_COURT } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // Accueil refondu le 11/08/2026. C'était une carte plein écran : 1 135 points
  // en quatre couleurs, un encart flottant, et rien qui dise ce qu'est ce site
  // ni ce qu'on peut y chercher. La carte devient /carte ; l'accueil annonce,
  // oriente, puis montre ce qui vient de bouger.
  export let data
  $: ({ chiffres, budget, recents, agenda, arreteLe, interco, prochains, sourceMarches,
       extraitsMarches, dernieres, dossiers, sujets, anneesSeances } = data)

  const GENRES = {
    acte:      { label: 'Acte public',     classe: 'g-acte' },
    'marché':  { label: 'Marché public',   classe: 'g-marche' },
    argent:    { label: 'Argent public',   classe: 'g-argent' },
    'légal':   { label: 'Annonce légale',  classe: 'g-legal' },
    vie:       { label: 'Vie locale',      classe: 'g-vie' },
  }

  const nombre = (n) => (n == null ? '-' : n.toLocaleString('fr-FR'))

  // Les titres BODACC finissent par la date de l'annonce, déjà affichée dans sa
  // propre colonne : « … — la commune (2026-08-09) » devient « … - la commune ».
  // Le tiret cadratin des sources devient un tiret simple, comme partout ici.
  const titre = (t) => (t || '').replace(/\s*\(\d{4}-\d{2}-\d{2}\)\s*$/, '').replace(/\s—\s/g, ' - ')

  // ── Les séances ─────────────────────────────────────────────────────────
  // « Conseil municipal du 10 septembre 2026 » perd sa date : la colonne de
  // gauche la porte déjà.
  const assemblee = (t) => (t || '').replace(/\s+du\s+\d.*$/i, '')
  const PIECES = {
    proces_verbal: 'procès-verbal',
    compte_rendu: 'compte rendu',
    deliberations: 'registre des délibérations',
    convocation: 'convocation',
    ordre_du_jour: 'ordre du jour',
    annexe: 'annexe',
    piece: 'pièce',
  }
  // ⚖️ Un zéro s'affiche avec sa raison, jamais nu. « 0 délibération » ferait
  // croire à une séance sans décision, alors qu'il dit que le découpage n'a
  // rien su lire dans les pièces — ce n'est pas la même information.
  const compte = (n) =>
    n > 0 ? `${n} délibération${n > 1 ? 's' : ''}`
          : 'aucune délibération lue dans les pièces'
  const millions = (n) =>
    n == null ? '-'
    : n >= 1e6 ? `${(n / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} M€`
    : `${Math.round(n / 1e3).toLocaleString('fr-FR')} k€`

  const jour = (d) => {
    if (!d) return ''
    const dt = new Date(d + 'T00:00:00')
    return dt.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  }
  const dateLongue = (d) =>
    d ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : ''
  const dateDuJour = (d) =>
    d ? new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' }) : ''
</script>

<svelte:head>
  <title>{COMMUNE} au clair : la commune par les données publiques</title>
  <meta name="description" content="Qui décide, où va l'argent, qui agit : {COMMUNE} et son intercommunalité, la {EPCI}, à partir des seules données publiques." />
</svelte:head>

<!-- Accueil refondu le 04/10/2026 (docs/refonte-du-contenu.md, architecture
     B). Il s'ouvrait sur des compteurs et trois portes vers de la donnée
     rangée ; les séances et les dossiers — ce qui donne accès à la décision et
     à ses enjeux — n'y étaient que deux pastilles d'en-tête, cachées derrière
     le menu sur mobile. Il part maintenant d'elles ; les données suivent.
     Resserré le 06/10/2026 : la recherche face au titre, trois dossiers, les
     données en tuiles, et le fil des décisions après les trois portes. -->
<section class="entree">
  <div>
    <h1>{COMMUNE}, au clair.</h1>
    <p>Les séances du conseil, les dossiers, les données publiques.</p>
  </div>
  <form class="cherche" action="/recherche" method="get" role="search">
    <input type="search" name="q" placeholder="Un sujet, un nom, un montant…"
           aria-label="Rechercher un sujet, un nom, un montant" autocomplete="off" />
    <button type="submit">Chercher</button>
  </form>
</section>

<!-- Au conseil : la dernière séance de CHAQUE assemblée, nommée. Les deux ne
     se mêlent pas — ni les mêmes élus, ni le même bulletin de vote. -->
{#if dernieres?.length || prochains?.length}
  <section class="conseil">
    <header>
      <h2>Au conseil</h2>
      <!-- Le lien dit l'année tant que les séances publiées n'en couvrent
           qu'une : « toutes » promettrait un historique qui n'y est pas. -->
      <a class="tout" href="/conseils">Toutes les séances{anneesSeances?.length === 1 ? ` ${anneesSeances[0]}` : ''} <Icon name="fleche" size={14} /></a>
    </header>
    {#if dernieres?.length}
      <div class="seances">
        {#each dernieres as s}
          <a class="seance" href="/conseils/{s.id}">
            <span class="nature" class:cc={s.code === 'cc'}>{s.assemblee}</span>
            <strong>{dateLongue(s.date)}</strong>
            {#if s.en_clair}
              <span class="titre-clair">{s.en_clair.titre}</span>
              <span class="etat">Mise en clair, relue le {dateLongue(s.en_clair.relu_le)}</span>
            {:else}
              <span>{compte(s.nb_actes)}</span>
              <span class="etat">Pas encore mise en clair</span>
            {/if}
          </a>
        {/each}
      </div>
    {/if}
    {#if prochains?.length}
    <!-- Le prochain conseil, tel que sa convocation l'annonce : avant la séance,
         c'est la seule chose qu'un habitant peut en savoir. -->
    <div class="prochain">
      {#each prochains as s}
        <article>
          <p class="quand">
            <span class="etiquette">Prochain conseil</span>
            <strong>{assemblee(s.titre)}</strong>, {dateDuJour(s.date)}{#if s.convocation?.heure}, {s.convocation.heure}{/if}{#if s.convocation?.lieu}, {s.convocation.lieu}{/if}
          </p>
          {#if s.convocation?.ordre_du_jour?.length}
            <details>
              <summary>L'ordre du jour : {s.convocation.ordre_du_jour.length} point{s.convocation.ordre_du_jour.length > 1 ? 's' : ''}</summary>
              <ol>{#each s.convocation.ordre_du_jour as point}<li>{point}</li>{/each}</ol>
              <p class="source">Lu dans la convocation{#if s.convocation.convoque_le}{' '}du {dateLongue(s.convocation.convoque_le)}{/if}{#if s.convocation.url}{' '}(<a href={s.convocation.url} target="_blank" rel="noopener">la lire</a>){/if}.
                Séance publique : chacun peut y assister.</p>
            </details>
          {:else if s.convocation?.url}
            <p class="source"><a href={s.convocation.url} target="_blank" rel="noopener">La convocation</a></p>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
  </section>
{/if}

{#if !dossiers?.length && sujets?.length}
  <section class="dossiers">
    <header>
      <h2>Ce que les données disent de…</h2>
      <a class="tout" href="/dossiers">Dossiers thématiques <Icon name="fleche" size={14} /></a>
    </header>
    <p class="chapeau-dossiers">Aucun dossier n'est encore écrit ici. Sur ces sujets, les sources publiques ont déjà des faits&nbsp;:</p>
    <ul>
      {#each sujets as s}<li><a href={s.lien}>{s.titre}</a></li>{/each}
    </ul>
  </section>
{/if}

<!-- Trois dossiers, tirés au sort à chaque publication (+page.server.js). -->
{#if dossiers?.length}
  <section class="dossiers">
    <header>
      <h2>Dossiers thématiques</h2>
      <a class="tout" href="/dossiers">Tous les dossiers <Icon name="fleche" size={14} /></a>
    </header>
    <ul>
      {#each dossiers as d}
        <li><a href="/dossiers/{d.slug}">{d.titre}</a>{#if d.chapeau}<p>{d.chapeau}</p>{/if}</li>
      {/each}
    </ul>
  </section>
{/if}

<!-- Les données : des valeurs, pas des phrases. Chaque tuile porte le chiffre
     de la COMMUNE ; celui de l'intercommunalité suit, nommé, jamais additionné
     (ni le même conseil, ni le même bulletin de vote). Un zéro garde sa raison,
     en une ligne : il dit ce que le SITE a relevé, jamais ce que la commune a
     fait. Le détail de chaque compte est sur la page où mène la tuile. -->
<section class="donnees">
  <header>
    <h2>Les données</h2>
    <a class="tout" href="/carte">Explorer la carte <Icon name="fleche" size={14} /></a>
  </header>
  <div class="tuiles">
    <a class="tuile" href="/deliberations">
      <b>{nombre(chiffres.deliberations)}</b>
      <span class="quoi">délibérations municipales</span>
      {#if interco?.deliberations}<span class="aussi">{EPCI_COURT}&nbsp;: {nombre(interco.deliberations)}</span>{/if}
    </a>
    <a class="tuile" class:vide={chiffres.marches === 0} href="/marches">
      <b>{nombre(chiffres.marches)}</b>
      <span class="quoi">{chiffres.marches > 1 ? 'marchés attribués' : 'marché attribué'}</span>
      {#if chiffres.marches === 0}
        <span class="aussi raison">
          {#if sourceMarches === 'absente'}collecte pas encore lancée
          {:else if extraitsMarches?.cas === 'en_attente'}{nombre(extraitsMarches.enAttente)} lu{extraitsMarches.enAttente > 1 ? 's' : ''} dans les procès-verbaux, qui {extraitsMarches.enAttente > 1 ? 'attendent leur' : 'attend sa'} relecture
          {:else}rien n'est publié sous 40&nbsp;000&nbsp;€&nbsp;HT{/if}
        </span>
      {/if}
      {#if interco?.marches}<span class="aussi">{EPCI_COURT}&nbsp;: {nombre(interco.marches)}</span>{/if}
    </a>
    <a class="tuile" href="/acteurs-publics">
      <b>{nombre(chiffres.acteurs)}</b>
      <span class="quoi">acteurs en activité</span>
      {#if chiffres.associations}<span class="aussi">dont {nombre(chiffres.associations)} associations</span>{/if}
    </a>
    {#if budget}
      <a class="tuile" href="/budgets">
        <b>{millions(budget.recettes)}</b>
        <span class="quoi">recettes de fonctionnement</span>
        <span class="aussi">{budget.annee}, source OFGL</span>
      </a>
      <a class="tuile" href="/budgets">
        <b>{millions(budget.depenses)}</b>
        <span class="quoi">dépenses de fonctionnement</span>
        <span class="aussi">{budget.annee}, source OFGL</span>
      </a>
      {#if budget.habitants}
        <a class="tuile" href="/territoire">
          <b>{nombre(budget.habitants)}</b>
          <span class="quoi">habitants</span>
          <span class="aussi">{budget.annee}, source OFGL</span>
        </a>
      {/if}
    {/if}
  </div>
  <p class="provenance">
    Chiffres de la commune.
    <a href="/com-com">Ceux de la {EPCI_COURT}</a> · <a href="/methode">Méthode</a>
  </p>
</section>

<section class="portes">
  <a class="porte" href="/qui-decide">
    <span class="porte-titre"><Icon name="decide" size={18} />Qui décide&nbsp;?</span>
    <p>Le conseil, l'intercommunalité, les commissions et les liens entre acteurs.</p>
  </a>
  <a class="porte" href="/argent">
    <span class="porte-titre"><Icon name="argent" size={18} />Où va l'argent&nbsp;?</span>
    <p>Budget, impôts, subventions, marchés publics et transactions foncières.</p>
  </a>
  <a class="porte" href="/acteurs-publics">
    <span class="porte-titre"><Icon name="acteurs" size={18} />Qui agit&nbsp;?</span>
    <p>Entreprises, associations, services publics et lieux de la commune.</p>
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
            {#if item.nb_actes != null}
              <!-- Une séance renvoie vers sa page (cf. +page.server.js) ; ses
                   PIÈCES renvoient vers l'archive d'origine. -->
              <a href={item.lien || '/deliberations'}>{assemblee(item.titre)}</a>
              <span class="compte">: {compte(item.nb_actes)}</span>
              {#if item.pieces?.length}
                <span class="pieces">
                  {#each item.pieces as p, i}{#if i}<span class="sep"> · </span>{/if}<a
                    href={p.url} target="_blank" rel="noopener">{PIECES[p.nature] || 'pièce'}</a>{/each}
                </span>
              {/if}
            {:else if item.url}
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
  .ailleurs {
    margin: .7rem 0 0; font-size: .85rem; color: var(--gris);
    border-top: 1px dashed var(--trait); padding-top: .6rem;
  }

  /* L'agenda est volontairement plus discret que le fil des décisions : même
     structure, moins de poids. */
  .flux.agenda { margin-top: 1.25rem; }

  /* Le prochain conseil : un bandeau, pas une carte de plus. Il se lit en une
     ligne ; l'ordre du jour se déplie pour qui veut savoir de quoi on parlera. */
  .prochain { display: flex; flex-direction: column; gap: .6rem; margin-bottom: 1.6rem; }
  .prochain article {
    border: 1px solid var(--trait); border-left: 4px solid var(--ardoise);
    border-radius: var(--rayon); background: var(--blanc); padding: .8rem 1rem;
  }
  .prochain .quand { margin: 0; font-size: .98rem; line-height: 1.5; }
  .prochain .etiquette {
    display: inline-block; margin-right: .5rem; font-size: .68rem; font-weight: 700;
    letter-spacing: .06em; text-transform: uppercase; color: var(--ardoise-fonce);
    background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .5rem;
  }
  .prochain details { margin-top: .5rem; }
  .prochain summary { cursor: pointer; color: var(--ardoise); font-size: .9rem; }
  .prochain ol { margin: .5rem 0 .4rem; padding-left: 1.4rem; font-size: .9rem; line-height: 1.5; }
  .prochain li { margin-bottom: .2rem; }
  .prochain .source { margin: .3rem 0 0; font-size: .8rem; color: var(--gris); }
  .prochain .source a { color: var(--ardoise); }
  .flux.agenda h2 { font-size: 1rem; color: var(--gris); }

  section { max-width: 1080px; margin: 0 auto; padding: 0 1.4rem; }

  /* ---------- entrée, conseil, dossiers (04/10/2026) ---------- */
  /* Le titre à gauche, la recherche en face, calée à droite ; elle passe
     dessous quand la largeur manque. */
  .entree {
    display: flex; align-items: center; justify-content: space-between;
    gap: 1rem 2rem; flex-wrap: wrap; padding-top: 2.4rem; padding-bottom: 1.6rem;
  }
  .entree h1 { font-size: clamp(2rem, 4.5vw, 2.9rem); line-height: 1.08; margin: 0 0 .4rem; }
  .entree p { margin: 0; color: var(--gris); font-size: 1.02rem; }
  .cherche { display: flex; gap: .5rem; flex: 0 1 26rem; margin-left: auto; }
  .cherche input {
    flex: 1; min-width: 0; padding: .6rem .85rem; font-size: 1rem; color: var(--encre);
    border: 1px solid var(--trait); border-radius: var(--rayon); background: var(--blanc);
  }
  .cherche input:focus { outline: 2px solid var(--ardoise); outline-offset: 1px; }
  .cherche button {
    padding: .6rem 1rem; font-size: .95rem; border: none; border-radius: var(--rayon);
    background: var(--ardoise); color: var(--blanc); cursor: pointer;
  }
  .conseil, .dossiers { padding-bottom: 2.2rem; }
  .conseil header, .dossiers header, .donnees header { display: flex; align-items: baseline; gap: .8rem; flex-wrap: wrap; margin-bottom: .7rem; }
  .conseil h2, .dossiers h2, .donnees h2 { font-size: 1.35rem; margin: 0; }
  .seances { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: .8rem; margin-bottom: 1rem; }
  .seance {
    display: flex; flex-direction: column; gap: .25rem; padding: .85rem 1rem; color: inherit;
    background: var(--blanc); border: 1px solid var(--trait); border-left: 4px solid var(--ardoise);
    border-radius: var(--rayon);
  }
  .seance:hover { text-decoration: none; box-shadow: var(--ombre); }
  .seance .nature {
    align-self: flex-start; font-size: .66rem; font-weight: 700; text-transform: uppercase;
    color: var(--ardoise-fonce); background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .45rem;
  }
  .seance .nature.cc { background: var(--trait-pale); color: var(--encre); }
  .seance .titre-clair { font-family: var(--display); font-size: 1.05rem; color: var(--encre); }
  .seance .etat { font-size: .8rem; color: var(--gris); }
  .chapeau-dossiers { margin: 0 0 .8rem; color: var(--gris); font-size: .92rem; max-width: 62ch; }
  .dossiers ul { list-style: none; padding: 0; margin: 0; display: grid;
                 grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr)); gap: .7rem; }
  .dossiers li { padding: .75rem .9rem; background: var(--blanc); border: 1px solid var(--trait);
                 border-radius: var(--rayon); }
  .dossiers li a { font-family: var(--display); font-size: 1.05rem; font-weight: 600; }
  .dossiers li p { margin: .3rem 0 0; font-size: .84rem; color: var(--gris); line-height: 1.45; }

  /* ---------- les données, en tuiles ---------- */
  .donnees { padding-bottom: 1.4rem; }
  .tuiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: .7rem; }
  .tuile {
    display: flex; flex-direction: column; gap: .2rem; padding: .8rem .9rem; color: inherit;
    background: var(--blanc); border: 1px solid var(--trait); border-radius: var(--rayon);
  }
  .tuile:hover { text-decoration: none; border-color: var(--ardoise); }
  .tuile b {
    font-family: var(--display); font-size: 1.7rem; line-height: 1;
    font-variant-numeric: tabular-nums; color: var(--encre);
  }
  .tuile.vide b { color: var(--gris); }
  .tuile .quoi {
    font-family: var(--data); font-size: .66rem; letter-spacing: .09em;
    text-transform: uppercase; color: var(--gris);
  }
  .tuile .aussi { font-size: .76rem; color: var(--gris); font-variant-numeric: tabular-nums; }
  .tuile .raison { color: var(--ambre); }
  .provenance { margin: .6rem 0 0; font-size: .78rem; color: var(--gris); }
  .provenance a { color: var(--ardoise); }

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
  /* Le compte d'actes et les pièces sont la MENTION d'une séance, pas son nom :
     ils suivent le titre sans lui disputer la ligne. */
  .flux .compte { color: var(--gris); }
  .flux .pieces { display: block; font-size: .78rem; margin-top: .15rem; }
  .flux .pieces .sep { color: var(--gris-clair); }
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
    .cherche { flex-basis: 100%; }
    .portes, .secondaires { grid-template-columns: 1fr; }
    .flux li { grid-template-columns: 4.6rem 1fr; row-gap: .2rem; }
    .genre { grid-column: 2; justify-self: start; }
  }
</style>
