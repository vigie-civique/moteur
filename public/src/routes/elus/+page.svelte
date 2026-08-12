<script>
  import { rangFonction, estAdjoint } from '$lib/elus.js'

  // Source : Répertoire National des Élus (DGCL), qui porte la commune de
  // chaque mandat. La page se construisait avant sur `relations.json`, où le
  // mandat ne dit pas de quelle commune il relève : elle empilait les conseils
  // des communes de l'intercommunalité sans le signaler — d'où deux maires côte à
  // côte. Elle datait en plus la « mandature » à la plus récente installation
  // trouvée (22/03/2026) puis écartait tout mandat antérieur : sur 110 mandats
  // actifs il n'en restait que 14, et pas ceux de Lasalle.
  const COMMUNE_PRINCIPALE = 'Lasalle'

  // Rendu au build par +page.server.js : tout le croisement RNE × relations
  // y est fait, la page ne fait plus que filtrer et afficher.
  export let data
  $: elus = data.elus
  $: commissions = new Map(data.commissionsEntries)

  let commune = COMMUNE_PRINCIPALE



  $: communes = [...new Set(elus.map(e => e.commune))]
    .sort((a, b) => (a === COMMUNE_PRINCIPALE ? -1 : b === COMMUNE_PRINCIPALE ? 1 : a.localeCompare(b)))
  $: visibles = commune === '*' ? elus : elus.filter(e => e.commune === commune)
  $: parCommune = communes
    .map(c => [c, visibles.filter(e => e.commune === c)])
    .filter(([, l]) => l.length)

  const installation = (l) => {
    const d = l.map(e => e.date_debut_mandat).filter(Boolean).sort()[0]
    return d ? new Date(d).toLocaleDateString('fr-FR',
      { day: 'numeric', month: 'long', year: 'numeric' }) : ''
  }
</script>

<svelte:head><title>Conseils municipaux — Vigie Civique Lasalle</title>
  <meta name="description" content="Composition des conseils municipaux de Lasalle et des communes de la CC Causses Aigoual Cévennes Terres Solidaires : maires, adjoints, conseillers et délégués communautaires." /></svelte:head>

<section>
  <h1>Conseils municipaux</h1>
  <p class="sub">
    Les élus en fonction, commune par commune, d'après le Répertoire National
    des Élus (DGCL). Seuls les conseillers actuellement en poste figurent ici
    (ni anciens élus, ni candidats).
  </p>

  {#if !elus.length}<p class="muted">Aucun mandat en cours dans le jeu de données public.</p>{/if}

  {#if communes.length}
    <div class="filtres">
      {#each communes as c}
        <button class:actif={commune === c} on:click={() => commune = c}>{c}</button>
      {/each}
      <button class:actif={commune === '*'} on:click={() => commune = '*'}>Toutes les communes</button>
    </div>
  {/if}

  {#each parCommune as [c, liste]}
    <h2>
      {c}
      <span class="count">{liste.length} élus{#if installation(liste)} · conseil installé le {installation(liste)}{/if}</span>
    </h2>
    <div class="grid">
      {#each liste as e (e.entity_id)}
        <article>
          <a href="/entite/{e.entity_id}"><h3>{e.prenom} {e.nom}</h3></a>
          <div class="roles">
            {#if e.fonction}
              <span class="role" class:maire={rangFonction(e.fonction) === 0}
                    class:adjoint={estAdjoint(e.fonction)}>{e.fonction}</span>
            {/if}
            <span class="role">Conseiller·ère municipal·e</span>
            {#if e.epci}
              <span class="role interco">
                {e.epci.fonction || 'Conseiller·ère communautaire'}
              </span>
            {/if}
          </div>
          {#if e.epci?.epci_nom}
            <p class="comm"><span class="clab">Intercommunalité</span> {e.epci.epci_nom}</p>
          {/if}
          {#if commissions.get(e.entity_id)}
            <p class="comm">
              <span class="clab">Commissions</span>
              {#each commissions.get(e.entity_id) as c, i}
                {#if i}<span class="sep">·</span>{/if}<span
                  class:pilote={c.role === 'responsable'}
                  title={c.role === 'responsable' ? 'Responsable de la commission' : ''}
                >{c.label}{#if c.role === 'responsable'} ★{/if}</span>{#if c.precision}<span class="prec"> ({c.precision})</span>{/if}
              {/each}
            </p>
          {/if}
        </article>
      {/each}
    </div>
  {/each}
</section>

<style>
  section { max-width: 1000px; margin: 0 auto; padding: 1.5rem; }
  h1 { color: var(--encre); margin: 0 0 .25rem; }
  .sub { color: var(--gris); margin: 0 0 1rem; max-width: 65ch; line-height: 1.5; }
  h2 { color: var(--encre); font-size: 1.15rem; margin: 1.75rem 0 .2rem;
       display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem; }
  .count { color: var(--gris-clair); font-size: .78rem; font-weight: 400;
           text-transform: uppercase; letter-spacing: .03em; }
  .filtres { display: flex; gap: .4rem; flex-wrap: wrap; margin: 0 0 .5rem; }
  .filtres button { font-size: .8rem; padding: .35rem .7rem; cursor: pointer;
    color: var(--gris); background: #fff; border: 1px solid var(--trait); border-radius: 999px; }
  .filtres button:hover { border-color: var(--trait); }
  .filtres button.actif { background: var(--ardoise); color: #fff; border-color: var(--ardoise); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .8rem;
          margin-top: .8rem; }
  article { background: #fff; border: 1px solid var(--trait); border-radius: 10px; padding: .9rem 1rem; }
  article h3 { margin: 0 0 .5rem; color: var(--encre); font-size: 1.05rem; }
  .roles { display: flex; flex-wrap: wrap; gap: .35rem; }
  /* Pas de `nowrap` : « 5ème vice-président du conseil communautaire » est un
     libellé RNE de 45 caractères, il débordait de la carte sur la colonne
     voisine. Il passe à la ligne dans sa pastille. */
  .role { font-size: .68rem; text-transform: uppercase; letter-spacing: .02em;
          background: var(--gris); color: #fff; padding: .14rem .55rem;
          border-radius: 12px; line-height: 1.35; max-width: 100%; }
  .role.maire { background: var(--ambre); } .role.adjoint { background: var(--ardoise); }
  .role.interco { background: var(--ardoise-fonce); }
  .comm { margin: .6rem 0 0; font-size: .8rem; color: var(--gris); line-height: 1.4; }
  .comm .pilote { font-weight: 600; color: var(--encre); }
  .comm .prec { color: var(--gris-clair); }
  .comm .sep { color: var(--trait); margin: 0 .25rem; }
  .clab { display: block; font-size: .65rem; text-transform: uppercase; letter-spacing: .03em; color: var(--gris-clair); margin-bottom: .1rem; }
</style>
