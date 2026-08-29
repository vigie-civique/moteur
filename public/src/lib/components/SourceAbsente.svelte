<script>
  // Dire qu'une question n'a pas été posée, plutôt que d'afficher un zéro.
  //
  // Le pendant de <Niveau> : celui-ci qualifie ce qu'on sait, celui-là dit ce
  // qu'on n'a pas cherché. Les deux cas sont visuellement distincts d'un
  // résultat, parce qu'un lecteur qui voit « 0 » sans explication conclut
  // toujours qu'il ne se passe rien — jamais que personne n'a regardé.
  import { enumerer } from '$lib/couverture.js'
  import { DOSSIER_COMPLET_URL } from '$lib/instance.js'

  export let etat = 'absente'   // 'absente' | 'vide'
  export let sources = []
  export let dernier = ''
  export let quoi = 'Cette rubrique'
  // Ce que la collecte automatique ne sait pas faire seule — aller chercher des
  // PV sur un site municipal, les découper, les rattacher — se fait à la main.
  // Le dire ICI, au seul endroit où la question se pose, et seulement si
  // l'instance déclare où : un site communal suivi n'a rien à proposer.
  export let travailManuel = false

  $: liste = enumerer(sources)
  // Les libellés de sources sont des groupes nominaux au genre et au nombre
  // variables : toute phrase qui les accorde finit par écrire « les actes des
  // assemblées n'a pas été renseignée ». Le gabarit les présente donc en
  // énumération, où aucun accord ne dépend d'eux.
  const jour = (d) => (d || '').slice(0, 10).split('-').reverse().join('/')
</script>

{#if etat === 'absente'}
  <p class="absente">
    <b>{quoi}&nbsp;: donnée non collectée.</b>
    {#if liste}Sources non interrogées pour ce dossier&nbsp;: {liste}. {/if}Ce n'est
    pas un zéro&nbsp;: c'est une question qui n'a pas été posée. Le détail figure
    sur la page <a href="/couverture">Couverture et lacunes</a>.
    {#if travailManuel && DOSSIER_COMPLET_URL}
      <br /><span class="manuel">Ces documents existent, mais aucun registre
      national ne les publie&nbsp;: il faut aller les chercher sur le site de la
      commune, les lire et les rattacher un par un. C'est un travail humain, et
      c'est l'objet du <a href={DOSSIER_COMPLET_URL} target="_blank"
      rel="noopener">dossier relu à la main</a>.</span>
    {/if}
  </p>
{:else if etat === 'vide'}
  <p class="vide">
    <b>Aucun résultat.</b>
    Sources interrogées{#if dernier} le {jour(dernier)}{/if}, sans rien rapporter
    pour ce territoire&nbsp;: {liste || 'aucune source déclarée'}.
  </p>
{/if}

<style>
  p { margin: .8rem 0; padding: .7rem .9rem; border-radius: 0 var(--rayon) var(--rayon) 0;
      font-size: .9rem; line-height: 1.55; color: var(--gris); max-width: 72ch; }
  p b { color: var(--encre); }
  .absente { border-left: 3px solid var(--depense); background: var(--papier); }
  .vide    { border-left: 3px solid var(--trait);   background: var(--papier); }
  a { color: inherit; }
  .manuel { display: inline-block; margin-top: .4rem; color: var(--gris); }
</style>
