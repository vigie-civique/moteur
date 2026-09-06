<script>
  // Bandeau d'état — ce que ce site EST, dit sur toutes ses pages.
  //
  // Trois sites servis par le même moteur n'ont pas le même statut, et rien ne
  // le disait : quelqu'un arrivant sur un portage de démonstration depuis un
  // moteur de recherche n'avait aucun moyen de savoir que personne, sur place,
  // ne tenait ce site. Il lisait ses manques comme la qualité du dispositif.
  //
  // Le bandeau NE SE REFERME PAS. Un bandeau qu'on peut fermer n'est pas une
  // mention, c'est une réclame : il disparaît au premier clic et le lecteur
  // suivant ne le voit plus. Il est discret et permanent, jamais modal — pas
  // de `role="alert"`, qui interromprait un lecteur d'écran à chaque page pour
  // une information qui ne change pas.
  //
  // Les libellés viennent de `instance.js`, donc de `collectors/statut.py` :
  // le même texte est publié dans le snapshot. Deux textes qui se ressemblent
  // finissent par diverger.
  import { STATUT_TYPE, STATUT_LIBELLE, STATUT_TEXTE, STATUT_TENUE_PAR } from '$lib/instance.js'

  // La date de dernière COLLECTE — jamais celle de publication. Une
  // republication ne recollecte rien, et ferait passer un site figé pour un
  // site vivant. Absente, on n'invente pas : la ligne disparaît.
  export let derniereCollecte = ''

  const fmt = (d) => {
    if (!d) return ''
    try {
      return new Date(d.slice(0, 10) + 'T00:00:00')
        .toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
    } catch { return d }
  }

  // Plein contre creux, en plus de la couleur : le pastillage seul ne se lit
  // ni en noir et blanc, ni par un daltonien.
  $: marque = STATUT_TYPE === 'demonstration' ? '○' : '●'
  $: texte = STATUT_TENUE_PAR
    ? STATUT_TEXTE.replace('tenu sur place', `tenu sur place par ${STATUT_TENUE_PAR}`)
    : STATUT_TEXTE
</script>

<aside class="etat {STATUT_TYPE}" aria-label="Statut de ce site">
  <p class="entete">
    <span class="etiquette"><span aria-hidden="true">{marque}</span> {STATUT_LIBELLE}</span>
    {#if derniereCollecte}
      <span class="date">dernière collecte : {fmt(derniereCollecte)}</span>
    {/if}
  </p>
  <p class="texte">
    {texte}
    <a href="/couverture">Ce qu'il couvre, et ce qui lui manque →</a>
  </p>
</aside>

<style>
  /* Les jetons sont ceux du site : aucune couleur nouvelle. L'ambre est déjà
     celui des mises en garde (Niveau « interpretation »), l'ardoise celui des
     renvois — un lecteur qui connaît le site sait déjà les lire. */
  .etat {
    margin: 0 0 1.2rem;
    padding: .6rem .85rem .55rem;
    border-left: 3px solid;
    border-radius: 0 var(--rayon) var(--rayon) 0;
    font-size: .86rem;
  }
  .demonstration { border-color: var(--ambre);   background: var(--ambre-pale); }
  .constitution  { border-color: var(--ardoise); background: var(--ardoise-pale); }
  .tenue         { border-color: var(--recette); background: #f2f7f4; }

  .entete { margin: 0 0 .3rem; display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem; }
  .etiquette {
    font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;
    padding: .1rem .45rem; border-radius: 99px;
    background: var(--blanc); border: 1px solid currentColor;
  }
  .demonstration .etiquette { color: var(--ambre); }
  .constitution .etiquette  { color: var(--ardoise-fonce); }
  .tenue .etiquette         { color: var(--recette); }

  .date { font-size: .74rem; color: var(--gris); font-variant-numeric: tabular-nums; }
  .texte { margin: 0; line-height: 1.5; color: var(--encre); }
  .texte a { color: var(--ardoise); white-space: nowrap; }

  /* Sur un petit écran, le texte long passerait avant le titre de la page :
     on garde l'étiquette et le renvoi, la phrase se replie. */
  @media (max-width: 540px) {
    .etat { font-size: .8rem; }
    .date { display: block; }
  }

  /* Une page imprimée circule sans son contexte : le bandeau reste. */
  @media print {
    .etat { border: 1px solid #999; background: none; }
  }
</style>
