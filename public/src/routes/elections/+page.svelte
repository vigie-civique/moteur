<script>
  import { COMMUNE, COMMUNE_A, EPCI, SITE_NOM } from '$lib/instance.js'
  import Icon from '$lib/components/Icon.svelte'

  // La base savait QUI avait été élu, jamais AVEC COMBIEN DE VOIX : un seul
  // événement `election` y figurait. Or 81 % de participation et un écart de
  // 10 points ne racontent pas la même chose qu'un scrutin à 45 %.
  // Rendu au build par +page.server.js : les résultats sont déjà dans le HTML.
  export let data
  $: resultats = data.resultats
  $: listes = data.listes
  $: communesAbsentes = data.communesAbsentes || []

  $: scrutins = [...new Set(resultats.map(r => r.scrutin))].sort().reverse()
  const listesDe = (r) => listes
    .filter(l => l.insee === r.insee && l.scrutin === r.scrutin && l.tour === r.tour)
    .sort((a, b) => (b.voix || 0) - (a.voix || 0))
  const parScrutin = (s) => resultats
    .filter(r => r.scrutin === s)
    .sort((a, b) => (b.participation_pct || 0) - (a.participation_pct || 0))

  const nomScrutin = (s) => s.replace('municipales-', 'Municipales ')
  const pct = (v) => v == null ? '—' : `${Number(v).toFixed(1)} %`
</script>

<svelte:head>
  <title>Les élections — {SITE_NOM}</title>
  <meta name="description" content="Résultats des élections municipales {COMMUNE_A} et dans les communes de la {EPCI} : participation, voix par liste, sièges attribués." />
</svelte:head>

<section class="page">
  <header>
    <h1 class="avec-icone"><Icon name="elections" size={26} />Les élections</h1>
    <p class="chapeau">
      Participation, voix et sièges — d'où vient le mandat de ceux qui décident.
      {COMMUNE} et les autres communes de l'intercommunalité.
    </p>
    <!-- L'absence est réelle, pas un trou de collecte : mieux vaut la nommer
         que la laisser deviner. Les communes concernées sont calculées au build
         (cf. +page.server.js) — les nommer en dur rendait la phrase fausse au
         scrutin suivant. -->
    {#if communesAbsentes.length}
      <p class="source">
        {communesAbsentes.length === 1 ? 'Une commune n’y figure pas' :
         `${communesAbsentes.length} communes n’y figurent pas`}&nbsp;:
        {communesAbsentes.join(', ')}. Un conseil municipal élu en dehors des
        deux tours n’apparaît dans aucun des fichiers nationaux publiés.
      </p>
    {/if}
  </header>

  {#if !resultats.length}<p class="etat">Aucun résultat disponible.</p>
  {:else}
    {#each scrutins as s}
      <h2>{nomScrutin(s)}</h2>
      <p class="source">Source : ministère de l'Intérieur, résultats officiels par commune.</p>

      <div class="communes">
        {#each parScrutin(s) as r}
          <article class:phare={r.commune === '{COMMUNE}'}>
            <header class="tete">
              <h3>{r.commune}</h3>
              <span class="tour">tour {r.tour}</span>
            </header>

            <div class="participation">
              <div class="barre" role="img"
                   aria-label="Participation {pct(r.participation_pct)}">
                <span style="width:{Math.min(100, r.participation_pct || 0)}%"></span>
              </div>
              <p class="chiffres">
                <strong>{pct(r.participation_pct)}</strong> de participation ·
                {r.votants} votants sur {r.inscrits} inscrits
                {#if r.blancs || r.nuls}
                  · {(r.blancs || 0) + (r.nuls || 0)} bulletin{(r.blancs || 0) + (r.nuls || 0) > 1 ? 's' : ''} blanc·s ou nul·s
                {/if}
              </p>
            </div>

            <ul class="listes">
              {#each listesDe(r) as l}
                <li>
                  <div class="ligne">
                    <span class="nom">{l.libelle || l.libelle_abrege || `Liste ${l.rang}`}</span>
                    <span class="voix">{l.voix} voix</span>
                  </div>
                  <div class="barre petite">
                    <span style="width:{Math.min(100, l.pct_exprimes || 0)}%"></span>
                  </div>
                  <p class="detail">
                    {pct(l.pct_exprimes)} des exprimés
                    {#if l.sieges_cm}· <strong>{l.sieges_cm}</strong> siège{l.sieges_cm > 1 ? 's' : ''} au conseil municipal{/if}
                    {#if l.sieges_cc}· {l.sieges_cc} au conseil communautaire{/if}
                  </p>
                </li>
              {/each}
            </ul>
          </article>
        {/each}
      </div>
    {/each}

    <div class="note">
      <h3>Ce que ces chiffres disent — et ce qu'ils ne disent pas</h3>
      <p>
        Les sièges sont attribués à la proportionnelle avec prime majoritaire :
        la liste arrivée en tête obtient la moitié des sièges, le reste étant
        réparti entre toutes les listes. Un écart de voix serré peut donc donner
        un écart de sièges très large.
      </p>
      <p>
        Ces résultats sont ceux publiés par le ministère de l'Intérieur. Ils ne
        renseignent ni sur les alliances passées entre les deux tours, ni sur les
        démissions survenues en cours de mandat — pour cela, voir
        <a href="/elus">la composition actuelle du conseil</a>.
      </p>
      <p class="liens">
        <a href="/qui-decide">Qui décide ?</a> ·
        <a href="/comprendre/mandats">Comprendre les mandats</a> ·
        <a href="/methode">Méthode et sources</a>
      </p>
    </div>
  {/if}
</section>

<style>
  .page { max-width: 940px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; color: var(--encre); }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.55; margin: 0 0 1.25rem; }
  h2 { font-size: 1.2rem; margin: 2rem 0 .2rem; color: var(--encre); }
  .source { font-size: .8rem; color: var(--gris-clair); margin: 0 0 1.25rem; }
  .etat { color: var(--gris); }

  .communes { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); }
  article { background: #fff; border: 1px solid var(--trait); border-radius: 12px; padding: 1rem 1.1rem; }
  article.phare { border-color: var(--ardoise); box-shadow: 0 3px 14px rgba(37,99,235,.1); }
  .tete { display: flex; align-items: baseline; gap: .5rem; margin-bottom: .7rem; }
  .tete h3 { margin: 0; font-size: 1.05rem; color: var(--encre); }
  .tour { font-size: .72rem; color: var(--gris-clair); }

  .barre { height: 7px; background: var(--ardoise-pale); border-radius: 999px; overflow: hidden; }
  .barre span { display: block; height: 100%; background: var(--ardoise); border-radius: 999px; }
  .barre.petite { height: 5px; margin: .25rem 0; }
  .barre.petite span { background: var(--gris); }
  .chiffres { font-size: .82rem; color: var(--gris); margin: .4rem 0 0; line-height: 1.45; }
  .chiffres strong { color: var(--encre); }

  .listes { list-style: none; margin: .9rem 0 0; padding: 0; display: grid; gap: .7rem; }
  .ligne { display: flex; justify-content: space-between; gap: .5rem; align-items: baseline; }
  .nom { font-size: .86rem; font-weight: 600; color: var(--encre); }
  .voix { font-size: .8rem; color: var(--gris); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .detail { font-size: .76rem; color: var(--gris); margin: 0; line-height: 1.4; }
  .detail strong { color: var(--encre); }

  .note { margin-top: 2.5rem; padding: 1.1rem 1.25rem; background: var(--papier);
          border: 1px solid var(--trait); border-left: 3px solid var(--ardoise); border-radius: 10px; }
  .note h3 { margin: 0 0 .5rem; font-size: 1rem; color: var(--encre); }
  .note p { margin: 0 0 .6rem; font-size: .88rem; line-height: 1.55; color: var(--gris); }
  .liens { font-size: .85rem; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
