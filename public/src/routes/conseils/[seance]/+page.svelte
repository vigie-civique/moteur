<script>
  import { SITE_NOM } from '$lib/instance.js'
  export let data
  $: s = data.seance
  $: actes = data.actes
  $: clair = s.en_clair
  const fmt = (d) => {
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
  const PIECES = {
    proces_verbal: 'Procès-verbal', compte_rendu: 'Compte rendu',
    deliberations: 'Registre des délibérations', convocation: 'Convocation',
    ordre_du_jour: 'Ordre du jour', annexe: 'Annexe', piece: 'Pièce',
  }
  const vote = (v) => {
    if (!v) return ''
    if (v.unanimite) return "à l'unanimité"
    const p = []
    if (v.pour != null) p.push(`${v.pour} pour`)
    if (v.contre) p.push(`${v.contre} contre`)
    if (v.abstention) p.push(`${v.abstention} abstention${v.abstention > 1 ? 's' : ''}`)
    return p.join(', ')
  }
  const pluriel = (n, mot) => `${n} ${mot}${n > 1 ? 's' : ''}`
</script>

<svelte:head>
  <title>{s.assemblee} du {fmt(s.date)} — Les conseils en clair — {SITE_NOM}</title>
  <meta name="description" content="{s.assemblee} du {fmt(s.date)} : {pluriel(s.nb_actes, 'délibération')} publiée{s.nb_actes > 1 ? 's' : ''}{clair ? ', et la séance mise en clair' : ''}." />
</svelte:head>

<article>
  <p class="fil"><a href="/conseils">Les conseils en clair</a> › {s.date}</p>
  <p class="nature" class:cc={s.code === 'cc'}>{s.assemblee}</p>
  <h1>{s.assemblee} du {fmt(s.date)}</h1>

  <!-- L'état de la séance, toujours dit : sous « Les conseils en clair », la
       plupart des séances ne sont pas encore mises en clair, et le titre de la
       rubrique ne doit pas le promettre à leur place. -->
  {#if clair}
    <div class="clair">
      <p class="etat"><b>Mise en clair</b>, relue à l'atelier le {clair.relu_le}.</p>
      <p class="titre-clair">{clair.titre}</p>
      <p><a class="bouton" href="/data/{clair.fichier}">Lire les trois feuilles en clair</a>
        <span class="aide">ce qui était annoncé, ce qui a été décidé, ce que les documents ont de faux ou d'incomplet — imprimables en A4</span></p>
    </div>
  {:else}
    <p class="etat pas-encore">
      <b>Pas encore mise en clair.</b> Voici les délibérations telles que la
      collecte les a lues dans les pièces de la séance, sans relecture.
    </p>
  {/if}

  <!-- Deux lectures de la même séance peuvent ne pas compter pareil. Les deux
       nombres sont donnés, avec leur origine (décision 10) : un élu qui vient
       vérifier doit savoir lequel il conteste. -->
  {#if clair && clair.nb_actes !== s.nb_actes}
    <div class="ecart">
      <p><b>Deux décomptes pour cette séance.</b></p>
      <ul>
        <li><b>{clair.nb_actes}</b> — les actes que le relevé a retrouvés dans le
          procès-verbal, un par marque d'acte, et que la relecture a vérifiés&nbsp;;</li>
        <li><b>{s.nb_actes}</b> — les délibérations que la collecte a découpées dans
          les pièces de la séance et publiées, listées ci-dessous.</li>
      </ul>
      <p class="aide">L'écart n'est pas encore expliqué acte par acte. Un découpage
        peut séparer en deux ce que le procès-verbal compte pour un, ou retenir
        un fragment comme une délibération. Le relevé relu, lui, a été vérifié contre
        les marques d'acte du procès-verbal.</p>
    </div>
  {/if}

  {#if s.pieces?.length}
    <h2>Les pièces</h2>
    <ul class="pieces">
      {#each s.pieces as p}
        <li><a href={p.url} target="_blank" rel="noopener">{PIECES[p.nature] || p.libelle || 'Pièce'}</a>{#if p.libelle && PIECES[p.nature]} <span class="aide">— {p.libelle}</span>{/if}</li>
      {/each}
    </ul>
  {/if}

  <h2>{s.nb_actes > 1 ? `Les ${s.nb_actes} délibérations publiées`
       : s.nb_actes ? 'La délibération publiée' : 'Aucune délibération lue dans les pièces'}</h2>
  {#if actes.length}
    <ol class="actes">
      {#each actes as a}
        <li><a href={a.lien}>{a.titre || '(sans titre)'}</a>{#if vote(a.vote)} <span class="vote">— {vote(a.vote)}</span>{/if}</li>
      {/each}
    </ol>
    <p class="aide">Chaque délibération mène à sa ligne dans le registre de son année, avec son texte quand il a été lu.</p>
  {:else}
    <p class="aide">La séance est publiée, mais le découpage n'a lu aucune délibération dans ses pièces&nbsp;: ce n'est pas une séance sans décision.</p>
  {/if}

  <p class="retour"><a href="/conseils">Toutes les séances</a> · <a href="/deliberations/{s.date.slice(0, 4)}">Le registre de {s.date.slice(0, 4)}</a> · <a href="/contact">Signaler une erreur</a></p>
</article>

<style>
  article { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a, article a { color: var(--ardoise); }
  h1 { font-size: 1.7rem; margin: .3rem 0 1rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .5rem; }
  .nature { display: inline-block; margin: 0; font-size: .68rem; font-weight: 700; text-transform: uppercase;
            color: var(--ardoise-fonce); background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .45rem; }
  .nature.cc { background: var(--trait-pale); color: var(--encre); }
  .etat { margin: 0 0 .5rem; line-height: 1.55; }
  .pas-encore { color: var(--gris); border-left: 3px solid var(--trait); padding-left: .8rem; max-width: 62ch; }
  .clair { border: 1px solid var(--trait); border-left: 4px solid var(--ardoise); border-radius: var(--rayon);
           background: var(--blanc); padding: .8rem 1rem; }
  .clair p { margin: .2rem 0; }
  .titre-clair { font-family: var(--display); font-size: 1.15rem; }
  .bouton { display: inline-block; margin-top: .3rem; font-weight: 600; }
  .ecart { margin-top: 1rem; border-left: 3px solid var(--ambre); background: var(--ambre-pale);
           padding: .6rem 1rem; border-radius: var(--rayon); }
  .ecart p, .ecart ul { margin: .3rem 0; line-height: 1.5; }
  .aide { color: var(--gris); font-size: .85rem; line-height: 1.5; }
  .pieces, .actes { padding-left: 1.3rem; line-height: 1.6; }
  .actes li { margin-bottom: .3rem; }
  .vote { color: var(--gris); font-size: .85rem; }
  .retour { margin-top: 2rem; font-size: .9rem; }
</style>
