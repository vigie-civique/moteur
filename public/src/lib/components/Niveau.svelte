<script>
  // Marque le statut épistémique d'une information : ce qu'un document dit,
  // ce que le site calcule, ce qu'on peut en déduire.
  //
  // Ces trois choses n'ont pas la même valeur de preuve et ne doivent donc
  // jamais avoir la même apparence. « Mme X siège au conseil communautaire »
  // (un document l'atteste), « Mme X exerce 4 mandats recensés » (nous avons
  // compté) et « Mme X occupe une position centrale » (nous interprétons)
  // sont trois affirmations de nature différente. Présentées à l'identique,
  // le lecteur accorde à la troisième le crédit de la première.
  //
  // Usage :
  //   <Niveau type="calcul">Quatre titulaires concentrent 61 % des montants.</Niveau>
  //   <Niveau type="fait" source="Délibération du 27/04/2026" href={url}>…</Niveau>

  export let type = 'fait'          // 'fait' | 'calcul' | 'interpretation'
  export let source = ''            // fait : d'où vient l'information
  export let href = ''              // fait : lien vers le document
  export let base = ''              // calcul : sur quelles données il porte

  // L'étiquette et le détail se lisent d'affilée : « Calcul » suivi de
  // « calculé par le site » donnait « Calcul calculé par le site ». Le détail
  // complète l'étiquette, il ne la redit pas.
  //
  // `compact` : au-dessus d'une grille de tuiles, le bloc encadré écraserait
  // les chiffres qu'il qualifie. La variante n'en garde que l'étiquette et la
  // provenance, sur une ligne — même vocabulaire, même code couleur, poids
  // visuel d'une légende.
  export let compact = false

  const LIBELLES = {
    fait: {
      etiquette: 'Fait',
      explication: "Cette information figure telle quelle dans un document public.",
    },
    calcul: {
      etiquette: 'Calcul',
      explication: "Ce chiffre n'est écrit dans aucun document : il est calculé par le site à partir des données publiées. Il dépend donc de ce qui a été collecté.",
    },
    interpretation: {
      etiquette: 'Lecture',
      explication: "Ceci est une lecture proposée, pas un fait établi. D'autres lectures des mêmes données sont possibles.",
    },
  }

  $: n = LIBELLES[type] || LIBELLES.fait
</script>

{#if compact}
  <p class="ligne {type}">
    <span class="etiquette">{n.etiquette}</span>
    {#if type === 'fait' && source}
      <span class="detail">{source}</span>
      {#if href}<a class="doc" {href} target="_blank" rel="noopener">voir la source ↗</a>{/if}
    {:else if type === 'calcul'}
      <span class="detail">{base ? `du site, sur ${base}` : 'du site'}</span>
    {:else}
      <span class="detail">lecture proposée</span>
    {/if}
  </p>
{:else}
<div class="niveau {type}">
  <p class="entete">
    <span class="etiquette">{n.etiquette}</span>
    {#if type === 'fait' && source}
      <span class="detail">{source}</span>
      {#if href}<a class="doc" {href} target="_blank" rel="noopener">voir le document ↗</a>{/if}
    {:else if type === 'calcul'}
      <span class="detail">{base ? `du site, sur ${base}` : 'du site'}</span>
    {/if}
  </p>

  <div class="corps"><slot /></div>

  <p class="explication">{n.explication}</p>
</div>
{/if}

<style>
  /* Trois traitements franchement distincts : c'est tout l'objet du composant.
     Le fait est sobre et adossé au vert des recettes (une source existe), le
     calcul est neutre, la lecture porte l'ambre des mises en garde. */
  .niveau {
    margin: 1rem 0;
    padding: .7rem .9rem .55rem;
    border-left: 3px solid;
    border-radius: 0 var(--rayon) var(--rayon) 0;
  }
  .fait           { border-color: var(--recette); background: #f2f7f4; }
  .calcul         { border-color: var(--gris);    background: var(--papier); }
  .interpretation { border-color: var(--ambre);   background: var(--ambre-pale); }

  .entete { margin: 0 0 .35rem; display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem; }
  .etiquette {
    font-size: .66rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .06em; padding: .1rem .45rem; border-radius: 99px;
    background: var(--blanc); border: 1px solid currentColor;
  }
  /* Variante compacte : une ligne de légende, sans cadre ni fond. */
  .ligne {
    margin: 0 0 .5rem; display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem;
  }
  .ligne .etiquette { background: transparent; }
  .ligne.fait .etiquette           { color: var(--recette); border-color: var(--recette); }
  .ligne.calcul .etiquette         { color: var(--gris); border-color: var(--trait); }
  .ligne.interpretation .etiquette { color: var(--ambre); border-color: var(--ambre); }

  .fait .etiquette           { color: var(--recette); }
  .calcul .etiquette         { color: var(--gris); }
  .interpretation .etiquette { color: var(--ambre); }

  .detail { font-size: .78rem; color: var(--gris); }
  .doc { font-size: .78rem; color: var(--ardoise); }

  .corps { font-size: .95rem; line-height: 1.55; color: var(--encre); }
  .corps :global(b), .corps :global(strong) { font-variant-numeric: tabular-nums; }

  /* L'explication est une note de bas de bloc : présente pour qui la cherche,
     jamais assez lourde pour concurrencer l'information elle-même. */
  .explication {
    margin: .4rem 0 0; font-size: .74rem; line-height: 1.4; color: var(--gris-clair);
  }
</style>
