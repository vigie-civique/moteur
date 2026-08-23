<script>
  import { CODE_POSTAL, COMMUNE, COMMUNE_DE, EPCI, EPCI_COURT, INSEE, SITE_NOM } from '$lib/instance.js'
  // Chiffres lus au build (cf. +page.server.js) : cette page ne doit jamais
  // citer un compteur écrit à la main.
  export let data
  import Niveau from '$lib/components/Niveau.svelte'
</script>

<svelte:head><title>Méthode &amp; sources — {SITE_NOM}</title>
  <meta name="description" content="Comment ces données sont collectées, vérifiées et filtrées : sources officielles, règles de publication, corrections et limites connues." /></svelte:head>

<section>
  <h1>Méthode &amp; sources</h1>
  <p>Ce site agrège et croise des <strong>données publiques ouvertes</strong> pour documenter la gouvernance locale {COMMUNE_DE} ({CODE_POSTAL}). Aucune donnée personnelle privée n'est publiée.</p>

  <h2>Sources de données</h2>
  <table>
    <thead><tr><th>Source</th><th>Données</th><th>Licence</th></tr></thead>
    <tbody>
      <tr><td>SIRENE (INSEE)</td><td>Entreprises, associations</td><td>Licence Ouverte v2</td></tr>
      <tr><td>RNA</td><td>Associations</td><td>Licence Ouverte v2</td></tr>
      <tr><td>DVF (Cerema)</td><td>Transactions immobilières</td><td>Licence Ouverte v2</td></tr>
      <tr><td>BODACC</td><td>Annonces commerciales</td><td>Licence Ouverte v2</td></tr>
      <tr><td>OFGL / DGFiP</td><td>Budgets, agrégats financiers</td><td>Licence Ouverte v2</td></tr>
      <tr><td>DECP</td><td>Marchés publics</td><td>Licence Ouverte v2</td></tr>
      <tr><td>Délibérations CM / {EPCI_COURT}</td><td>Documents administratifs publics</td><td>CADA</td></tr>
      <tr><td>OpenStreetMap</td><td>Lieux, points d'intérêt</td><td>ODbL 1.0</td></tr>
    </tbody>
  </table>

  <h2>Ce que « vérifié » veut dire ici</h2>
  <p>
    Chaque donnée publiée porte la source qui l'a produite, et cette source est
    citée sur la page où la donnée apparaît. Nous ne publions que ce qui provient
    d'une source publique identifiée&nbsp;: un document administratif, un registre
    national, un site officiel.
  </p>
  <p>
    En sens inverse, les pistes de travail de l'atelier — une entreprise
    soupçonnée d'être liée à une autre, un rapprochement plausible mais non
    établi — portent un niveau inférieur et <strong>ne sont jamais publiées</strong>.
    {#if data.ecartes.entites}
      À ce titre, {data.ecartes.entites} acteurs,
      {data.ecartes.relations} liens et {data.ecartes.flux} flux financiers
      présents dans la base de travail sont écartés du site public.
    {/if}
  </p>
  <p class="franchise">
    Nous annoncions ici, jusqu'au 12 août 2026, deux niveaux distincts&nbsp;:
    « vérifié » pour une source primaire et « confirmé » pour une donnée recoupée
    par au moins deux sources indépendantes. C'était inexact&nbsp;: aucune donnée
    n'a jamais porté ce second niveau, faute d'une règle d'attribution
    praticable — quelle est la deuxième source indépendante du procès-verbal d'un
    conseil municipal&nbsp;? La distinction est retirée plutôt que maintenue à vide.
    Nous préférons décrire ce que la chaîne fait réellement.
  </p>
  <h2>Trois questions plutôt qu'un label</h2>
  <p>
    Un label unique demandait au lecteur de nous croire. Chaque acte publié
    porte désormais trois indications, affichées sur la ligne de l'acte
    lui-même et non reléguées ici&nbsp;: personne ne lit une page de méthode
    avant d'interpréter une ligne.
  </p>

  {#if data.provenance}
    <dl class="axes">
      <dt>D'où vient l'information&nbsp;?</dt>
      <dd>
        <strong>Source primaire</strong> — publiée par l'autorité qui a pris la
        décision&nbsp;: {data.provenance.provenance?.primaire ?? '—'} actes.
        <strong>Registre national</strong> — enregistrée par un tiers officiel,
        qui atteste de la <em>déclaration</em> qui lui a été faite et non du fait
        déclaré&nbsp;: {data.provenance.provenance?.registre ?? '—'} actes.
        <strong>Source secondaire</strong> — rapportée par un tiers&nbsp;:
        {data.provenance.provenance?.secondaire ?? 0}. Une source que nous
        n'avons pas classée tombe dans cette dernière catégorie&nbsp;: le doute
        joue contre nous.
      </dd>

      <dt>Pouvez-vous consulter la pièce&nbsp;?</dt>
      <dd>
        <strong>Acte consultable</strong> — le document lui-même est
        accessible&nbsp;: {data.provenance.document?.acte ?? '—'}.
        <strong>Page source</strong> — le lien mène à la page qui contient
        l'acte, le plus souvent le compte rendu entier et non la délibération
        isolée&nbsp;: {data.provenance.document?.page_source ?? '—'}. C'est notre
        principale faiblesse, et elle se voit ici plutôt que d'être tue.
        <strong>Sans document</strong>&nbsp;: {data.provenance.document?.aucun ?? 0}.
      </dd>

      <dt>Qu'avons-nous fait entre la source et l'affichage&nbsp;?</dt>
      <dd>
        <strong>Donnée structurée</strong> — reprise telle quelle d'un flux, sans
        étape d'interprétation&nbsp;: {data.provenance.traitement?.structure ?? '—'}.
        <strong>Extraite d'un document</strong> — lue dans un PDF ou un compte
        rendu par reconnaissance de caractères ou par modèle de langage&nbsp;:
        {data.provenance.traitement?.extraction ?? '—'}. C'est là que naissent
        les erreurs de lecture. <strong>Rectifiée</strong> après vérification
        humaine&nbsp;: {data.provenance.traitement?.rectifie ?? 0}.
      </dd>
    </dl>
  {/if}

  <p>
    Une quatrième dimension serait utile — la <strong>concordance</strong>,
    c'est-à-dire savoir si plusieurs sources indépendantes disent la même chose.
    Nous ne la produisons pas, parce que rien dans notre chaîne ne recoupe
    aujourd'hui deux sources indépendantes. L'afficher reviendrait à répondre
    invariablement « source unique », et à répéter l'erreur du niveau
    « confirmé » retiré plus haut&nbsp;: annoncer une garantie qui n'existe pas.
  </p>

  <h2>Fait, calcul, lecture</h2>
  <p>
    Trois choses très différentes cohabitent sur ce site, et elles n'ont pas la
    même valeur de preuve. Présentées à l'identique, la plus fragile emprunterait
    le crédit de la plus solide. Elles sont donc signalées différemment&nbsp;:
  </p>

  <Niveau type="fait" source="Délibération du conseil municipal du 27/04/2026">
    Le conseil a approuvé la mise en place d'une mutuelle communale.
  </Niveau>
  <p class="apres">
    Un <strong>fait</strong> figure tel quel dans un document public. Nous le
    reproduisons, nous n'en sommes pas l'auteur. Le document est cité, et
    consultable quand la source le met à disposition.
  </p>

  <Niveau type="calcul" base="les marchés recensés dans les délibérations et les données ouvertes">
    Sur 2016–2026, 24 marchés attribués sont recensés pour 2,57 M€.
  </Niveau>
  <p class="apres">
    Un <strong>calcul</strong> n'est écrit dans aucun document&nbsp;: c'est nous
    qui comptons. Il dépend entièrement de ce qui a été collecté — un marché que
    nous n'avons pas trouvé n'y figure pas, et le total est donc un minimum, pas
    une vérité comptable.
  </p>

  <Niveau type="interpretation">
    Une même entreprise obtient régulièrement les marchés de voirie de la commune.
  </Niveau>
  <p class="apres">
    Une <strong>lecture</strong> est une proposition d'interprétation. D'autres
    sont possibles à partir des mêmes données&nbsp;: dans une commune de mille
    habitants, le nombre d'entreprises capables de répondre à un marché est
    faible, et une régularité n'est pas une irrégularité. Nous en publions peu,
    et jamais sans dire ce que les documents ne permettent pas d'établir.
  </p>

  <h2>Corrections</h2>
  <p>
    Une partie des documents sources sont des PDF scannés, lus par reconnaissance
    optique de caractères. Cette lecture produit des erreurs : un numéro d'article
    pris pour un montant, des chiffres accolés, une date fausse. Lorsqu'une donnée
    est manifestement erronée au regard du document d'origine, elle est
    <strong>rectifiée</strong> après vérification humaine sur le document.
  </p>
  <ul>
    <li>La donnée telle qu'elle a été collectée est <strong>conservée</strong> : la
      rectification est enregistrée à côté, jamais à la place.</li>
    <li>Toute valeur rectifiée porte la mention <strong>✎ rectifié</strong> sur le
      site, avec le motif de la correction.</li>
    <li>Une donnée jugée non publiable après contrôle est retirée du site, pas
      modifiée.</li>
  </ul>
  <p>
    Une erreur constatée peut être signalée par la page
    <a href="/contact">Contact / Droit de réponse</a>.
  </p>

  <p class="renvoi">
    Le détail de ce que la collecte couvre — période par source, fraîcheur des
    collecteurs, documents manquants — est sur la page
    <a href="/couverture">Couverture et lacunes</a>.
  </p>

  <h2>Limites</h2>
  <p>Les coordonnées issues de géocodage automatique peuvent être approximatives. Les entités sans localisation publique fiable ne sont pas affichées sur la carte.</p>
  <h2>Périmètre</h2>
  <p>
    Le site suit la <strong>chaîne de décision</strong>, pas le voisinage
    géographique. Il couvre donc <strong>{COMMUNE}</strong> en profondeur, et la
    <strong>{EPCI}</strong> — l'échelon
    qui exerce à la place de la commune l'eau, l'assainissement, les déchets et
    le développement économique.
  </p>
  <p>
    Les quinze communes membres de cette intercommunalité sont collectées au même
    niveau que {COMMUNE}, mais elles ne sont <strong>pas publiées en fiches</strong> :
    elles servent à situer {COMMUNE} parmi ses pairs (fiscalité, population,
    urbanisme, résultats électoraux). Seules apparaissent en fiche les
    institutions — mairies, intercommunalité, syndicats — et les personnes qui
    siègent au conseil communautaire, parce qu'elles décident pour {COMMUNE}.
  </p>
  <p>
    Une entité située hors de ce périmètre y entre malgré tout si elle est
    <strong>rattachée à un acteur suivi</strong> : société détenue par un élu de
    {COMMUNE}, titulaire d'un marché de la commune. C'est le lien de décision qui
    fait entrer une donnée, jamais la proximité.
  </p>
  <p>
    Les actes et événements ne portent pas tous la mention de leur commune :
    c'est un défaut connu, en cours de correction.
  </p>

  <!-- Objectif de réplication — assumé publiquement depuis le 12/08/2026.
       Ce n'est pas une intention vague : elle a des conséquences techniques
       vérifiables (périmètre piloté en un seul fichier, export Popolo,
       dictionnaire de données régénéré à chaque publication), et c'est cette
       page qui en rend compte. -->
  <h2>Ce modèle est fait pour être repris</h2>
  <p>
    Rien ici ne vaut spécifiquement pour {COMMUNE}. Le même dispositif —
    collecteurs, base, règles de publication, site — est conçu pour être
    <strong>rejoué sur n'importe quelle commune française</strong>, et
    singulièrement sur les <strong>petites communes rurales</strong> : le
    régime général d'open data ne vise que les collectivités de plus de
    3 500 habitants employant plus de 50 agents, et {COMMUNE} n'en relève pas.
    D'autres obligations de publication demeurent — les actes des communes de
    moins de 3 500 habitants doivent être rendus publics, la commune choisissant
    entre affichage, papier et forme électronique, et l'électronique s'applique
    à défaut de choix. Ce qui manque ici, ce n'est donc pas le droit de savoir :
    c'est un endroit où tout se lit ensemble.
  </p>
  <p>
    Le périmètre d'une instance — la commune, son intercommunalité, ses communes
    membres — tient dans un fichier de configuration. Le reste demande du
    travail : les collecteurs nationaux fonctionnent tels quels partout, mais le
    site officiel de chaque mairie a sa propre structure et réclame son propre
    analyseur. Comptez quelques jours, pas une heure.
  </p>
  {#if data.replicabilite}
    <p>
      Ce que cette page affirme est mesuré, pas promis. Un contrôle automatique
      recompte à chaque publication les endroits où le nom d'une commune s'est
      glissé dans le code plutôt que dans la configuration&nbsp;:
      <strong>{data.replicabilite.moteur_occurrences}</strong> dans le moteur,
      <strong>{data.replicabilite.site_occurrences}</strong> dans ce site,
      <strong>{data.replicabilite.atelier_occurrences}</strong> dans l'outil
      d'édition. Il interdit des formes autant que des mots&nbsp;: un code INSEE
      écrit en dur, un identifiant de ligne pris pour une constante, l'adresse
      d'un site officiel. La mesure a longtemps manqué&nbsp;: le contrôle ne
      cherchait que le nom de la commune courante, et donnait un feu vert
      trompeur partout ailleurs.
    </p>
  {/if}
  <p>
    Le dispositif a deux moitiés. <strong>Ce site</strong> ne sert que des
    données filtrées, il est entièrement statique et n'interroge aucune base.
    <strong>L'outil d'édition</strong>, lui, travaille sur la base complète —
    celle qui contient les pistes non vérifiées et les personnes sans rôle
    public, tout ce que le filtre écarte. Il n'a pas vocation à être en ligne&nbsp;:
    chaque instance décide s'il tourne seulement sur la machine de collecte, sur
    un réseau restreint, ou sur l'internet avec des comptes nommés. Ce n'est pas
    une question technique, c'est une question d'accès à ce qu'on a choisi de ne
    pas publier.
  </p>
  <p>
    Le code est réutilisable, sous licence MIT&nbsp;:
    <a href="/repliquer">répliquer sur votre commune</a>.
  </p>

  <h2>Réutiliser les données</h2>
  <p>
    Toutes les données publiées ici sont servies en <strong>JSON</strong>, au
    même endroit que le site, sans inscription ni clé d'API. Le
    <a href="/data/README.md">dictionnaire de données</a> décrit chaque
    fichier ; il est régénéré à chaque publication, il ne peut donc pas décrire
    un état périmé.
  </p>
  <ul>
    <li>
      <a href="/data/entities.json">entities.json</a> — les acteurs ·
      <a href="/data/relations.json">relations.json</a> — les liens, datés et
      sourcés · <a href="/data/events.json">events.json</a> — les actes.
    </li>
    <li>
      <a href="/data/popolo.json">popolo.json</a> — les mandats au format
      <a href="https://www.popoloproject.com/" target="_blank" rel="noopener">Popolo</a>,
      le vocabulaire commun des projets de transparence démocratique. Un outil
      qui parle déjà Popolo lit ce fichier sans rien connaître de ce site.
    </li>
    <li>
      <a href="/data/intercommunalite.json">intercommunalite.json</a>,
      <a href="/data/marches.json">marches.json</a>,
      <a href="/data/flows.json">flows.json</a>,
      <a href="/data/dvf.json">dvf.json</a> et les autres — voir le
      dictionnaire.
    </li>
  </ul>
  <h2>Licence</h2>
  <p>
    Les données de ce site sont publiées sous
    <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener">Open
    Database License 1.0</a> (ODbL). Vous pouvez les copier, les modifier et les
    utiliser, y compris commercialement, à trois conditions&nbsp;: <strong>citer</strong>
    la source, <strong>partager à l'identique</strong> toute base dérivée que vous
    redistribuez, et ne pas les diffuser sous verrou technique sans en fournir
    aussi une version libre.
  </p>
  <p>
    Ce choix découle des sources&nbsp;: une partie des lieux et des
    coordonnées vient d'OpenStreetMap, dont la licence impose le partage à
    l'identique aux bases qui en dérivent. Les autres sources, en Licence
    Ouverte v2, sont compatibles avec ce choix.
  </p>
  <p class="attribution">
    {SITE_NOM}. Contient des informations d'OpenStreetMap
    (© les contributeurs OpenStreetMap, ODbL), des données publiques sous
    Licence Ouverte v2 (SIRENE, INSEE, RNA, DVF, BODACC, OFGL, DGFiP, DECP,
    BOAMP, Répertoire National des Élus, ministère de l'Intérieur, BANATIC) et
    des données IGN.
  </p>
  <p>
    Le <strong>site</strong> et ses visualisations relèvent de la simple
    attribution, pas du partage à l'identique. Le <strong>code</strong> qui
    produit ce site est sous licence MIT, distincte&nbsp;: c'est lui qu'une
    autre commune reprendrait.
  </p>
  <p>
    <strong>Une licence ouverte ne lève pas le RGPD.</strong> Ces données
    restent des données personnelles pour partie&nbsp;: les réutiliser suppose
    d'avoir sa propre base légale. En cas de doute, écrivez-nous par la page
    <a href="/contact">Contact</a>.
  </p>
</section>

<style>
  .renvoi { background: var(--ardoise-pale); border-radius: var(--rayon);
            padding: .7rem .9rem; font-size: .92rem; }
  .renvoi a { color: var(--ardoise); }

  .axes { margin: 1rem 0 1.5rem; }
  .axes dt { font-weight: 600; color: var(--encre); margin-top: 1rem; }
  .axes dd { margin: .3rem 0 0; padding-left: 1rem; border-left: 2px solid var(--trait);
             color: var(--gris); font-size: .92rem; line-height: 1.6; }
  .axes dd strong { color: var(--encre); }

  /* Commentaire qui suit un exemple de niveau : rattaché visuellement au bloc
     qui le précède, pas au paragraphe suivant. */
  .apres { margin: .35rem 0 1.5rem; font-size: .92rem; color: var(--gris); }

  /* Encart de franchise : signaler une erreur passée du site lui-même. Il doit
     se distinguer du texte courant sans crier — c'est une correction, pas un
     avertissement de danger. */
  .franchise {
    border-left: 3px solid var(--ambre);
    background: var(--ambre-pale);
    padding: .8rem 1rem;
    border-radius: 0 8px 8px 0;
    font-size: .92rem;
  }

  section { max-width: 800px; margin: 0 auto; padding: 1.5rem; line-height: 1.6; }
  h1 { color: var(--encre); } h2 { color: var(--encre); margin-top: 1.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: .9rem; margin: .5rem 0; }
  th, td { text-align: left; padding: .45rem .5rem; border-bottom: 1px solid var(--trait); }
  th { color: var(--gris); }
  /* Bloc d'attribution ODbL — obligation de licence, pas décoration. */
  .attribution {
    font-size: .88rem; color: var(--gris);
    border-left: 3px solid var(--trait); padding-left: .9rem;
  }
</style>
