<script>
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { TYPE_LABELS, loadJSON, euros } from '$lib/data.js'

  // La recherche ne portait que sur les acteurs. Or on ne cherche pas seulement
  // « qui » : on cherche « école », « assainissement », « voirie », un montant,
  // une année. Ne trouver que des noms d'entreprises donnait l'impression que le
  // site ignorait un sujet dont il détient pourtant les actes.
  //
  // Deux index, pour ne pas alourdir la page : celui des acteurs est embarqué au
  // build (~140 Ko) et répond dès la première frappe ; l'index transversal
  // (6 474 entrées, ~940 Ko) est chargé en arrière-plan et prend le relais. Tout
  // embarquer aurait fait une page à 1 Mo — la régression même qu'on a corrigée
  // ailleurs.
  export let data
  $: acteurs = data.index

  let complet = null          // index transversal, une fois chargé
  let chargement = true

  let q = ''
  let categorie = ''
  let commune = ''

  onMount(async () => {
    // Requête pré-remplie depuis l'URL : ?q= rend les résultats partageables.
    // Lu ici et non au rendu : la page est prérendue, il n'y a pas de query
    // string au build (SvelteKit interdit d'y toucher à ce moment-là).
    q = $page.url.searchParams.get('q') || ''
    try {
      complet = (await loadJSON('recherche_index.json')).index || []
    } catch { complet = null }   // on reste sur les acteurs seuls
    finally { chargement = false }
  })

  const LIMITE = 60   // au-delà, affiner la requête vaut mieux que dérouler

  const CATEGORIES = {
    acteur: 'Acteur',
    acte: 'Acte',
    marche: 'Marché',
    versement: 'Versement',
  }

  // Recherche insensible aux accents et à la casse : « caderle » doit trouver
  // « Sainte-Croix-de-Caderle », et « ecole » doit trouver « école ».
  const fold = (s) => (s || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')   // diacritiques combinants
    .toLowerCase()

  // Tant que l'index transversal n'est pas là, on cherche dans les acteurs, mis
  // au même format : le lecteur n'a pas à savoir qu'il y a deux fichiers.
  $: source = complet ?? acteurs.map((e) => ({
    k: 'acteur', t: e.n, u: `/entite/${e.id}`, c: e.c, n: 1000 + (e.nb || 0),
  }))

  // Le champ `c` ne veut pas dire la même chose selon la catégorie : commune
  // pour un acteur, source pour un acte, acheteur pour un marché, payeur pour
  // un versement. Alimenter un filtre « communes » avec tout cela y mettait
  // `bodacc`, `lasalle.fr` et « État - Fonds Vert » à côté de Lasalle et
  // Colognac. Le filtre n'est donc proposé que sur les acteurs, où il a un sens.
  $: communes = [...new Set(
    source.filter((e) => e.k === 'acteur').map((e) => e.c).filter(Boolean)
  )].sort()
  $: filtreCommuneUtile = categorie === 'acteur'
  $: if (!filtreCommuneUtile && commune) commune = ''
  $: needle = fold(q.trim())
  $: resultats = needle.length < 2 && !categorie && !commune
    ? []
    : source
        .filter((e) => !categorie || e.k === categorie)
        .filter((e) => !commune || e.c === commune)
        .filter((e) => !needle || fold(e.t).includes(needle)
                    || (e.m != null && String(e.m).includes(needle))
                    || (e.d || '').includes(needle))
  $: affiches = resultats.slice(0, LIMITE)
  $: parCategorie = resultats.reduce((acc, r) => {
    acc[r.k] = (acc[r.k] || 0) + 1
    return acc
  }, {})
</script>

<svelte:head>
  <title>Rechercher — Vigie Civique Lasalle</title>
  <meta name="description" content="Chercher dans tout le site : acteurs, délibérations, marchés publics et versements de la commune de Lasalle et de son intercommunalité." />
</svelte:head>

<section class="rech">
  <h1>Rechercher</h1>
  <p class="sub">
    Acteurs, délibérations, marchés publics et versements — tout en même temps.
    Cherchez un nom, mais aussi un sujet («&nbsp;voirie&nbsp;», «&nbsp;école&nbsp;»),
    un montant ou une année.
  </p>

  <div class="filtres">
    <input
      type="search"
      bind:value={q}
      placeholder="Nom d'une association, d'une entreprise, d'un lieu…"
      aria-label="Rechercher un acteur"
      autocomplete="off" />
    <select bind:value={categorie} aria-label="Filtrer par catégorie">
      <option value="">Tout</option>
      <option value="acteur">Acteurs</option>
      <option value="acte">Actes et délibérations</option>
      <option value="marche">Marchés publics</option>
      <option value="versement">Versements</option>
    </select>
    {#if filtreCommuneUtile}
      <select bind:value={commune} aria-label="Filtrer par commune">
        <option value="">Toutes les communes</option>
        {#each communes as c}<option value={c}>{c}</option>{/each}
      </select>
    {/if}
  </div>

  {#if !resultats.length}
    <p class="etat">
      {needle.length >= 2 || categorie || commune
        ? 'Rien ne correspond.'
        : `Tapez au moins deux lettres, ou choisissez une catégorie. ${source.length.toLocaleString('fr-FR')} entrées consultables.`}
    </p>
  {:else}
    <p class="compte">
      {resultats.length.toLocaleString('fr-FR')} résultat{resultats.length > 1 ? 's' : ''}
      {#if Object.keys(parCategorie).length > 1}
        <em>— {Object.entries(parCategorie)
              .map(([k, n]) => `${n} ${(CATEGORIES[k] || k).toLowerCase()}${n > 1 ? 's' : ''}`)
              .join(' · ')}</em>
      {/if}
      {#if resultats.length > LIMITE}<em>— {LIMITE} premiers affichés, affinez la recherche</em>{/if}
    </p>
    <ul class="liste">
      {#each affiches as e, i (e.u + i)}
        <li>
          <a href={e.u}>
            <span class="badge {e.k}">{CATEGORIES[e.k] || e.k}</span>
            <span class="nom">{e.t}</span>
            {#if e.d}<span class="commune">{e.d}</span>{/if}
            {#if e.c}<span class="commune">{e.c}</span>{/if}
            {#if e.m != null}<span class="actes">{euros(e.m)}</span>{/if}
          </a>
        </li>
      {/each}
    </ul>
  {/if}

  {#if chargement}
    <p class="etat chargeant">Chargement de l'index complet — la recherche porte pour l'instant sur les acteurs seuls.</p>
  {/if}
</section>

<style>
  .rech { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
  h1 { font-size: 1.7rem; margin: 0 0 .4rem; color: var(--encre); }
  .sub { color: var(--gris); max-width: 62ch; line-height: 1.5; margin: 0 0 1.5rem; }

  .filtres { display: flex; gap: .6rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
  input[type="search"] {
    flex: 1 1 22rem; padding: .65rem .9rem; font-size: 1rem;
    border: 1px solid var(--trait); border-radius: 10px; background: #fff; color: var(--encre);
  }
  input[type="search"]:focus, select:focus { outline: 2px solid var(--ardoise); outline-offset: 1px; border-color: var(--ardoise); }
  select {
    padding: .65rem .7rem; font-size: .9rem; border: 1px solid var(--trait);
    border-radius: 10px; background: #fff; color: var(--gris);
  }

  .etat { color: var(--gris); }
  .etat.err { color: var(--depense); }
  .compte { font-size: .85rem; color: var(--gris); margin: 0 0 .6rem; }
  .compte em { font-style: normal; color: var(--gris-clair); }

  .liste { list-style: none; margin: 0; padding: 0; display: grid; gap: .4rem; }
  .liste a {
    display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
    padding: .6rem .8rem; background: #fff; border: 1px solid var(--trait);
    border-radius: 10px; color: inherit; text-decoration: none;
  }
  .liste a:hover { border-color: var(--ardoise); box-shadow: 0 3px 10px rgba(37,99,235,.1); text-decoration: none; }
  .nom { font-weight: 600; color: var(--encre); }
  .alias { font-size: .8rem; color: var(--gris-clair); }
  .commune { font-size: .78rem; color: var(--gris); margin-left: auto; }
  .actes { font-size: .72rem; color: var(--ardoise); background: var(--ardoise-pale); padding: .1rem .45rem; border-radius: 999px; }

  .badge {
    font-size: .68rem; text-transform: uppercase; letter-spacing: .03em;
    padding: .15rem .45rem; border-radius: 5px; background: var(--trait-pale); color: var(--gris); white-space: nowrap;
  }
  .badge.business { background: var(--ambre-pale); color: var(--ambre); }
  .badge.association { background: #d1fae5; color: #065f46; }
  .badge.service { background: var(--ardoise-pale); color: var(--ardoise-fonce); }
  .badge.place { background: var(--ardoise-pale); color: #5b21b6; }
  .badge.person { background: #f6e7e5; color: var(--depense); }

  @media (max-width: 620px) {
    .commune { margin-left: 0; }
  }
</style>
