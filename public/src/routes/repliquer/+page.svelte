<script>
  import { COMMUNE, DEPOT_URL, LA_COMMUNE, SITE_NOM } from '$lib/instance.js'
  import Niveau from '$lib/components/Niveau.svelte'

  export let data
  $: r = data.replicabilite
</script>

<svelte:head>
  <title>Répliquer ce dispositif sur votre commune — {SITE_NOM}</title>
  <meta name="description" content="Le code de ce site est réutilisable pour observer une autre commune : collecteurs de données publiques, règles de publication, site statique. Licence MIT." />
</svelte:head>

<section>
  <h1>Répliquer sur votre commune</h1>
  <p class="chapeau">
    Ce site n'a rien d'unique. En dessous de 3 500 habitants, l'obligation légale
    d'ouvrir ses données ne s'applique pas — et c'est là que vivent la moitié des
    communes françaises. Le dispositif qui produit cette page est réutilisable&nbsp;;
    voici ce qu'il fait, ce qu'il coûte, et ce qu'il ne fera pas à votre place.
  </p>

  {#if DEPOT_URL}
    <div class="depot">
      <a class="lien-depot" href={DEPOT_URL} rel="noopener">Voir le code</a>
      <dl class="meta">
        <div><dt>Licence</dt><dd>MIT (code) · ODbL (données)</dd></div>
        <div><dt>Amorçage</dt><dd>un code INSEE suffit</dd></div>
      </dl>
      <p class="verif">
        <code>git clone {DEPOT_URL}</code>, puis
        <code>python3 scripts/init_instance.py &lt;code INSEE&gt;</code>. Le dépôt
        porte son propre historique&nbsp;: vous pouvez voir ce qui a changé, quand,
        et pourquoi — y compris les erreurs et leurs corrections. C'est le point
        d'une publication de code&nbsp;; une archive ne le donne pas.
      </p>
    </div>
  {:else}
    <p class="muted">
      Le code de cette instance n'est pas publié à une adresse stable. Écrivez
      via <a href="/contact">la page contact</a>&nbsp;: il est sous licence MIT et
      rien ne s'oppose à ce qu'il vous soit transmis.
    </p>
  {/if}

  <h2>Ce que le dépôt contient</h2>
  <ul class="contenu">
    <li><b>Les collecteurs</b> — SIRENE, RNA, BODACC, DVF, OFGL/DGFiP, DECP et BOAMP, Sitadel, Géorisques, RNE, résultats électoraux, INSEE, Hub'Eau.</li>
    <li><b>La chaîne de publication</b> — le script qui extrait de la base un instantané filtré, et les règles qui décident ce qui sort.</li>
    <li><b>Le site</b> — celui que vous lisez, sans serveur ni base de données en ligne.</li>
    <li><b>L'outil d'édition</b> — facultatif, et qui travaille sur la base complète&nbsp;: il n'a pas vocation à être mis en ligne.</li>
    <li><b>Les contrôles</b> — refus de publier une page vide, refus de laisser fuiter un chemin local, refus de publier ce que le périmètre n'autorise pas, et une suite de tests sur les trois fonctions qui décident de ce qui sort.</li>
  </ul>

  <h2>Ce qu'il ne contient pas</h2>
  <p>
    Aucune donnée. Ni base, ni instantané publié, ni notes de travail, ni fichier
    nommant qui que ce soit. Un dispositif qui documente des personnes doit
    s'appliquer à lui-même les règles qu'il applique à ce qu'il publie&nbsp;: la
    liste des fichiers distribués est celle de ce qui est versionné, et un
    contrôle automatique refuse de fabriquer une archive si un nom de personne,
    un secret ou un chemin personnel s'y est glissé.
  </p>

  <h2>Ce que ça vous demandera vraiment</h2>
  {#if r}
    <Niveau type="calcul" base="le code du dispositif, recompté à chaque publication">
      {LA_COMMUNE}, son code INSEE et son intercommunalité se déclarent en un
      seul endroit, et les collecteurs nationaux fonctionnent alors sans
      modification. Un contrôle automatique recompte à chaque publication ce qui
      reste attaché à une commune précise&nbsp;:
      <b>{r.moteur_occurrences}</b> occurrence{r.moteur_occurrences > 1 ? 's' : ''}
      dans le moteur, <b>{r.site_occurrences}</b> dans ce site.
    </Niveau>
  {/if}
  <p>
    Et surtout&nbsp;: les collecteurs qui lisent le site de la mairie et celui de
    l'intercommunalité sont écrits pour la structure de <em>ces</em> sites. Le
    dépôt en fournit pour deux familles courantes, mais il n'existe aucun format
    commun aux sites de mairie — c'est la raison de fond pour laquelle ce genre
    d'outil n'existe pas déjà partout, et c'est le travail que personne ne peut
    faire à votre place. Comptez quelques jours, pas une heure.
  </p>

  <h2>La partie difficile n'est pas technique</h2>
  <p>
    Le plus délicat n'est pas de collecter, c'est de décider ce qu'il est
    légitime de faire dire aux données. Un lien entre un élu et une association
    n'est pas une faute&nbsp;; une entreprise qui obtient plusieurs marchés dans
    une commune de mille habitants n'est pas un scandale&nbsp;; un chiffre exact
    peut suggérer une conclusion que rien n'établit.
  </p>
  <p>
    Le code porte cette discipline — la distinction entre un fait, un calcul et
    une lecture, la provenance affichée sur chaque acte, les lacunes publiées —
    mais il ne la tiendra pas à votre place. Lisez
    <a href="/methode">la méthode</a> et <a href="/couverture">les lacunes</a>
    avant de vous lancer&nbsp;: c'est là qu'est le vrai contenu du projet.
  </p>

  <h2>Si vous le reprenez</h2>
  <p>
    Rien ne vous oblige à nous prévenir&nbsp;: la licence l'autorise sans
    contrepartie. Mais une correction proposée sur le dépôt profite à toutes les
    instances, y compris {COMMUNE}, et une commune de plus qui publie ses données
    est ce que ce projet cherche.
  </p>
</section>

<style>
  section { max-width: 780px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .6rem; }
  .chapeau { color: var(--gris); line-height: 1.65; margin: 0 0 1.75rem; }
  p { line-height: 1.65; }
  a { color: var(--ardoise); }
  .muted { color: var(--gris-clair); }

  .depot { border: 1px solid var(--trait); border-radius: 10px; padding: 1.2rem 1.3rem;
           background: var(--papier); }
  .lien-depot {
    display: inline-block; padding: .6rem 1.1rem; border-radius: 8px;
    background: var(--ardoise); color: #fff; font-weight: 600; text-decoration: none;
  }
  .lien-depot:hover { background: var(--ardoise-fonce); }

  .meta { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 1rem 0 .75rem; }
  .meta dt { font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; color: var(--gris); }
  .meta dd { margin: .1rem 0 0; font-size: .92rem; }

  code { font-family: var(--data); font-size: .78rem; word-break: break-all; color: var(--encre); }
  .verif { font-size: .84rem; color: var(--gris); margin: .6rem 0 0; }

  .contenu { padding-left: 1.1rem; }
  .contenu li { margin-bottom: .45rem; line-height: 1.6; }
</style>
