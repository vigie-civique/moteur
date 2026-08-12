<script>
  import Icon from '$lib/components/Icon.svelte'
</script>

<svelte:head>
  <title>Comprendre l'intercommunalité — Vigie Civique Lasalle</title>
  <meta name="description" content="Fiche pédagogique : la communauté de communes Causses Aigoual Cévennes Terres Solidaires — compétences, délégués, financement, et pourquoi cet échelon compte." />
</svelte:head>

<article>
  <p class="crumb"><a href="/comprendre">← Comprendre</a></p>
  <h1 class="avec-icone"><Icon name="intercommunalite" size={26} />L'intercommunalité, l'échelon discret qui décide beaucoup</h1>

  <h2>C'est quoi</h2>
  <p>Aucune commune de 100 ou 1 000 habitants ne peut gérer seule les déchets, une piscine ou le
     développement économique. La loi impose donc à chaque commune d'appartenir à un
     <strong>EPCI</strong> (établissement public de coopération intercommunale). Pour Lasalle,
     c'est la <strong>communauté de communes Causses Aigoual Cévennes Terres Solidaires</strong> (CC CAC), qui regroupe
     quinze communes du massif entre Aigoual et Salindrenque.</p>

  <h2>Ce qu'elle décide à la place de la commune</h2>
  <p>Les <strong>compétences transférées</strong> ne sont plus votées au conseil municipal :
     collecte des déchets, tourisme, zones d'activité, une partie de l'urbanisme et de l'eau selon
     les cas… La commune ne peut plus intervenir seule sur ces sujets — d'où l'importance de suivre
     aussi les délibérations communautaires, pas seulement celles du village.</p>

  <h2>Qui y siège</h2>
  <p>Des <strong>délégués communautaires</strong> : les maires et certains conseillers municipaux,
     désignés lors des élections municipales. Une petite commune n'a souvent qu'un ou deux sièges —
     son poids y est mécaniquement limité, et les arbitrages se jouent entre communes.</p>

  <h2>L'argent qui y transite</h2>
  <p>La CC CAC lève sa propre fiscalité et reçoit ses propres dotations. Elle attribue aussi des
     <strong>marchés publics</strong> et reçoit des <strong>subventions</strong> (Région, État,
     Europe/LEADER) pour des équipements utilisés par les habitants — la réhabilitation de
     bâtiments, les déchèteries, les projets touristiques. Suivre l'argent public local sans regarder
     l'interco, c'est ne voir que la moitié du tableau.</p>

  <h2>Où c'est documenté ici</h2>
  <p>Les procès-verbaux et délibérations du conseil communautaire sont collectés et archivés
     (le site de la CC CAC ne garde pas tout en ligne), ainsi que ses marchés et les subventions
     régionales qu'elle reçoit.</p>

  <p class="voir">
    Voir : <a href="/com-com">La communauté de communes</a> ·
    <a href="/deliberations">Délibérations</a> · <a href="/argent">Où va l'argent</a>.
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
