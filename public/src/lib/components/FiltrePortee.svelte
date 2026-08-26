<script>
  import { COMMUNE, EPCI_COURT } from '$lib/instance.js'

  /**
   * Choisir entre ce que la commune fait et ce que l'intercommunalité fait
   * pour elle.
   *
   * Ce n'est pas un filtre de confort : ce sont deux assemblées, deux budgets,
   * deux bulletins de vote. Les additionner sans le dire — « 1 997
   * délibérations » sur un site communal, dont 833 votées ailleurs — laisse
   * croire à un conseil municipal deux fois plus actif qu'il ne l'est.
   *
   * Le troisième onglet ne s'affiche que s'il porte quelque chose : sur une
   * page qui ne montre que des actes votés, « sur le territoire » serait un
   * bouton vide. Et l'ensemble disparaît quand l'une des deux portées est
   * absente — un choix entre une seule option n'est pas un choix.
   */
  export let valeur = 'commune'
  export let compte = {}        // { commune: n, intercommunalite: n, territoire: n }
  export let avecTerritoire = true
  export let libelleTerritoire = 'Sur le territoire'
  export let aide = ''

  $: onglets = [
    ['commune', COMMUNE, compte.commune ?? 0],
    ['intercommunalite', EPCI_COURT, compte.intercommunalite ?? 0],
    ...(avecTerritoire && (compte.territoire ?? 0) > 0
      ? [['territoire', libelleTerritoire, compte.territoire]] : []),
    ['tout', 'Tout', Object.values(compte).reduce((a, b) => a + (b || 0), 0)],
  ]
  // Deux portées non vides au minimum, sinon le choix est décoratif.
  $: utile = onglets.filter(([cle, , n]) => cle !== 'tout' && n > 0).length > 1
  const nombre = (n) => (n == null ? '—' : n.toLocaleString('fr-FR'))
</script>

{#if utile}
  <div class="portee" role="group" aria-label="Filtrer par périmètre">
    {#each onglets as [cle, label, n]}
      <button class:on={valeur === cle} on:click={() => (valeur = cle)}
              aria-pressed={valeur === cle}>
        {label} <b>{nombre(n)}</b>
      </button>
    {/each}
  </div>
  {#if aide}<p class="aide">{aide}</p>{/if}
{/if}

<style>
  .portee { display: flex; flex-wrap: wrap; gap: .4rem; margin: 0 0 .4rem; }
  .portee button {
    padding: .4rem .8rem; border: 1px solid var(--trait); border-radius: 6px;
    background: #fff; color: var(--gris); font-size: .85rem; cursor: pointer;
  }
  .portee button b { font-weight: 700; color: var(--encre); }
  .portee button.on { border-color: var(--encre); background: var(--encre); color: #fff; }
  .portee button.on b { color: #fff; }
  .aide { color: var(--gris); font-size: .8rem; margin: 0 0 .9rem; max-width: 74ch; }
</style>
