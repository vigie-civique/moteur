<script>
  // Jeu d'icônes du site. Remplace les émojis utilisés jusqu'ici dans la
  // navigation et les titres : un émoji change de dessin selon le système,
  // se colle au texte et ne prend pas la couleur de son contexte.
  // Tout est tracé en <path> pour que le composant reste un simple {#each}.
  export let name = ''
  export let size = 20
  export let label = ''   // renseigné = icône lisible par un lecteur d'écran

  const PATHS = {
    recent: ['M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0', 'M12 8v4.2l2.8 1.8'],
    decide: ['M12 3 21 8H3z', 'M5.5 11v7M9.5 11v7M14.5 11v7M18.5 11v7', 'M3 20.5h18'],
    argent: ['M4.5 6h15a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z',
             'M14.6 12a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0'],
    acteurs: ['M12 21s6.8-6.2 6.8-11A6.8 6.8 0 0 0 5.2 10c0 4.8 6.8 11 6.8 11z',
              'M14.4 10a2.4 2.4 0 1 1-4.8 0 2.4 2.4 0 0 1 4.8 0'],
    territoire: ['M4 20V11M9.3 20V5M14.7 20v-6M20 20V8', 'M2.5 20.5h19'],
    environnement: ['M12 3.5c3 3.9 6 6.4 6 9.8a6 6 0 0 1-12 0c0-3.4 3-5.9 6-9.8z'],
    vie: ['M5.5 5h13a2 2 0 0 1 2 2v11.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z',
          'M8 3.2v3.6M16 3.2v3.6M3.5 10.5h17'],
    comprendre: ['M4 4.5h6.4a2.6 2.6 0 0 1 2.6 2.6V20a2.2 2.2 0 0 0-2.2-1.7H4z',
                 'M20 4.5h-6.4A2.6 2.6 0 0 0 11 7.1V20a2.2 2.2 0 0 1 2.2-1.7H20z'],
    recherche: ['M17.5 11a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0', 'm16 16 4.5 4.5'],
    menu: ['M4 7h16M4 12h16M4 17h16'],
    fermer: ['M6 6l12 12M18 6L6 18'],
    fleche: ['M4.5 12h14M13 6.5l6 5.5-6 5.5'],
    impots: ['M12 3.5v17', 'M8 7.5h6.5a2.75 2.75 0 0 1 0 5.5H9a2.75 2.75 0 0 0 0 5.5h7'],
    marches: ['M4 19V6.5A2.5 2.5 0 0 1 6.5 4H16l4 4v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z',
              'M8 13h8M8 16.5h5'],
    subventions: ['M20 8.5 12 4 4 8.5v7L12 20l8-4.5z', 'M4 8.5 12 13l8-4.5M12 13v7'],
    urbanisme: ['M3 20.5h18M5 20.5V9l7-5 7 5v11.5', 'M10 20.5v-6h4v6'],
    graphe: ['M9.6 8.4 14.4 6M9.4 12.2h5.2M9.7 15.7l4.6 2.2',
             'M9 7a2.2 2.2 0 1 1-4.4 0A2.2 2.2 0 0 1 9 7', 'M9 12.2a2.2 2.2 0 1 1-4.4 0 2.2 2.2 0 0 1 4.4 0',
             'M9 17a2.2 2.2 0 1 1-4.4 0A2.2 2.2 0 0 1 9 17', 'M19.4 5.4a2.2 2.2 0 1 1-4.4 0 2.2 2.2 0 0 1 4.4 0',
             'M19.4 18.6a2.2 2.2 0 1 1-4.4 0 2.2 2.2 0 0 1 4.4 0'],
    elections: ['M4 9.5h16L18.4 20.5H5.6z', 'M9 9.5V6.7A2.7 2.7 0 0 1 11.7 4h.6A2.7 2.7 0 0 1 15 6.7v2.8'],
    conseil: ['M6.5 8.5a2.3 2.3 0 1 1-4.6 0 2.3 2.3 0 0 1 4.6 0', 'M14.3 7a2.3 2.3 0 1 1-4.6 0 2.3 2.3 0 0 1 4.6 0',
              'M22.1 8.5a2.3 2.3 0 1 1-4.6 0 2.3 2.3 0 0 1 4.6 0',
              'M1.5 19v-1.6a2.7 2.7 0 0 1 2.7-2.7M8.3 19v-2.4A2.9 2.9 0 0 1 11.2 14h1.6a2.9 2.9 0 0 1 2.9 2.6V19M22.5 19v-1.6a2.7 2.7 0 0 0-2.7-2.7'],
    document: ['M6 3.5h7.5L19 9v11.5H6z', 'M13.5 3.5V9H19', 'M9 13h7M9 16.5h5'],
    intercommunalite: ['M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17z', 'M3.5 12h17',
                       'M12 3.5c2.2 2.4 3.4 5.4 3.4 8.5S14.2 18.1 12 20.5c-2.2-2.4-3.4-5.4-3.4-8.5S9.8 5.9 12 3.5z'],
    eau: ['M12 3.5c3 3.9 6 6.4 6 9.8a6 6 0 0 1-12 0c0-3.4 3-5.9 6-9.8z'],
  }

  $: d = PATHS[name] || []
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="1.5"
     stroke-linecap="round" stroke-linejoin="round"
     role={label ? 'img' : 'presentation'} aria-hidden={label ? undefined : 'true'}
     aria-label={label || undefined}>
  {#each d as p}<path d={p}></path>{/each}
</svg>

<style>
  .icon { flex: none; display: block; }
</style>
