<script>
  import { SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'
</script>

<svelte:head>
  <title>Comprendre le budget communal — {SITE_NOM}</title>
  <meta name="description" content="Fiche pédagogique : comment fonctionne le budget d'une commune — fonctionnement, investissement, recettes, dotations, dette, budgets annexes." />
</svelte:head>

<article>
  <p class="crumb"><a href="/comprendre">← Comprendre</a></p>
  <h1 class="avec-icone"><Icon name="argent" size={26} />Le budget communal, mode d'emploi</h1>

  <h2>Deux sections, deux logiques</h2>
  <p>Un budget communal est toujours coupé en deux :</p>
  <ul>
    <li><strong>Le fonctionnement</strong> — la vie courante : salaires des agents, entretien,
        électricité, subventions aux associations. Ces dépenses reviennent chaque année.</li>
    <li><strong>L'investissement</strong> — ce qui dure : travaux, bâtiments, équipements,
        remboursement du capital des emprunts.</li>
  </ul>
  <p>Quand le fonctionnement dégage un excédent (l'<strong>épargne brute</strong>), il finance
     l'investissement. C'est l'indicateur de santé numéro un : une commune qui n'épargne plus
     ne peut plus investir sans s'endetter.</p>

  <h2>D'où vient l'argent</h2>
  <ul>
    <li><strong>Impôts locaux</strong> — taxe foncière surtout (la taxe d'habitation sur les
        résidences principales a disparu, mais elle demeure sur les résidences secondaires —
        un enjeu réel sur le territoire).</li>
    <li><strong>Dotations de l'État</strong> — la DGF (dotation globale de fonctionnement) et ses
        composantes rurales (DSR). Notifiées chaque année, elles ne se négocient pas.</li>
    <li><strong>Subventions</strong> — État (DETR, DSIL, Fonds Vert), Région, Département,
        Europe : de l'argent fléché sur des projets précis.</li>
    <li><strong>Recettes propres</strong> — loyers des bâtiments communaux, cantine, concessions…</li>
  </ul>

  <h2>La dette</h2>
  <p>Emprunter n'est pas un problème en soi : c'est fait pour l'investissement (c'est même la règle —
     une commune n'a pas le droit d'emprunter pour son fonctionnement). Ce qui compte :
     la <strong>capacité de désendettement</strong> — en combien d'années d'épargne brute la commune
     rembourserait sa dette. En dessous de 8 ans : correct. Au-delà de 10-12 ans : zone d'alerte.</p>

  <h2>Les budgets annexes</h2>
  <p>Certaines activités sont sorties du budget principal (eau, chaufferie, locaux commerciaux…) et
     suivies dans des <strong>budgets annexes</strong>. À surveiller : c'est parfois là que se logent
     les déficits discrets, comblés ensuite par des « subventions d'équilibre » du budget principal.</p>

  <h2>Qui décide, quand</h2>
  <p>Le conseil municipal <strong>vote le budget avant le 15 avril</strong> (budget primitif), puis
     constate l'année suivante ce qui a été réellement dépensé (compte administratif). Ces documents
     sont publics — les délibérations budgétaires aussi.</p>

  <p class="voir">
    Voir les chiffres réels : <a href="/argent">Où va l'argent</a> ·
    <a href="/budgets">Budgets détaillés</a> — sources DGFiP et OFGL (2017-2024).
  </p>
</article>

<style>
  article { max-width: 760px; margin: 0 auto; padding: 1.5rem; line-height: 1.65; }
  h1 { color: var(--encre); } h2 { color: var(--encre); margin-top: 1.5rem; }
  .crumb a { color: var(--gris); font-size: .9rem; }
  .voir { margin-top: 1.6rem; padding: .9rem 1.1rem; background: var(--papier);
          border: 1px solid var(--trait); border-radius: 10px; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
