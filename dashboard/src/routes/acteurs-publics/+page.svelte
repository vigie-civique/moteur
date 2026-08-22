<script>
  import { COMMUNE, COMMUNE_DE, EPCI, EPCI_NB_AUTRES, SITE_NOM } from '$lib/instance.js'
  import { api } from '$lib/api.js'

  // UN APPEL PAR TYPE, et non un seul appel filtré ensuite côté client.
  //
  // `/api/entities` trie par nom et coupe à `limit` — TOUS TYPES CONFONDUS.
  // Sur les 9 500 fiches de Lasalle, `entities({limit:500})` rendait 385
  // entreprises (jetées ici), 105 associations, 10 lieux, et AUCUN service :
  // la page s'arrêtait à la lettre « AS », et son onglet « Service public (0) »
  // se lisait comme un fait — il n'y en a pas — là où il fallait lire « la
  // mairie vient après la lettre AS ». Les 76 services de la base étaient
  // invisibles. Relevé et corrigé le 22/08/2026.
  const TYPES = ['service', 'place', 'association']
  const PLAFOND = 5000        // maximum accepté par l'API

  // Périmètre — mêmes clés et mêmes couleurs que la file de l'atelier.
  const PERIMETRES = [
    { key: 'C1',   label: 'La commune', tip: `${COMMUNE} — le cœur du projet` },
    { key: 'C2',   label: 'Interco',    tip: `${EPCI} et ses ${EPCI_NB_AUTRES} autres communes membres` },
    { key: 'C3',   label: 'Supra',      tip: "Préfecture, département, région, agences d'État" },
    { key: 'lien', label: 'Rattaché',   tip: "Hors du territoire mais lié à un acteur suivi" },
    { key: '',     label: 'Tous',       tip: 'Tous périmètres confondus' },
  ]

  // Défaut C1, comme dans l'atelier : la base porte trois fois plus
  // d'associations d'ailleurs que de la commune, et une page titrée
  // « acteurs publics {COMMUNE_DE} » qui s'ouvre sur les associations des
  // quatorze autres communes dit quelque chose de faux avant d'être lue.
  let perimetre = 'C1'
  let typeFilter = 'all'
  let search  = ''

  let parType  = { service: [], place: [], association: [] }
  let tronques = []
  let loading  = true
  let error    = ''

  // Deux clics rapides sur deux périmètres lancent deux appels, et rien ne
  // garantit qu'ils reviennent dans l'ordre : sans ce jeton, la réponse la
  // plus lente s'affiche sous le libellé de l'autre — une liste juste sous un
  // titre faux, ce que cette page vient précisément de cesser de faire.
  let demande = 0

  async function charger(perim) {
    const mienne = ++demande
    loading = true; error = ''
    try {
      const lots = await Promise.all(
        TYPES.map(t => api.entities({ type: t, perimetre: perim, limit: PLAFOND }))
      )
      const recu = Object.fromEntries(
        TYPES.map((t, i) => [t, Array.isArray(lots[i]) ? lots[i] : []])
      )
      // Un lot rendu au plafond exact est un lot probablement coupé : le dire,
      // plutôt que d'afficher un compte faux avec l'aplomb d'un compte juste.
      const coupes = TYPES.filter(t => recu[t].length >= PLAFOND)
      // Les lieux affichés sont ceux qu'OSM a catégorisés. Depuis le nettoyage
      // du 22/08/2026 cette condition n'écarte plus rien : elle reste comme
      // garde-fou d'une fiche « lieu » créée sans origine.
      recu.place = recu.place.filter(e => e.osm_category)
      if (mienne !== demande) return
      tronques = coupes
      parType = recu
    } catch (e) { if (mienne === demande) error = e.message }
    finally { if (mienne === demande) loading = false }
  }

  $: charger(perimetre)

  $: counts = {
    service: parType.service.length,
    place: parType.place.length,
    association: parType.association.length,
  }
  $: total = counts.service + counts.place + counts.association

  $: filtered = (typeFilter === 'all'
      ? [...parType.service, ...parType.place, ...parType.association]
      : parType[typeFilter]
    ).filter(e => {
      const q = search.trim().toLowerCase()
      return !q || e.name?.toLowerCase().includes(q)
    }).sort((a, b) => (a.name ?? '').localeCompare(b.name ?? '', 'fr'))

  $: soustitre = {
    C1:     `Services, lieux publics et associations ${COMMUNE_DE}`,
    C2:     `Services, lieux publics et associations des autres communes — ${EPCI}`,
    C3:     'Autorités supra-communales : préfecture, département, région, agences',
    lien:   'Hors du territoire, mais rattachés à un acteur suivi',
    '':     'Tous périmètres confondus',
  }[perimetre]

  const TYPE_LABELS = { service: 'Service public', place: 'Lieu', association: 'Association' }
  const TYPE_COLORS = { service: '#92400e', place: '#4c1d95', association: '#065f46' }
  const PERIM_COLORS = { C1: '#14556b', C2: '#9a6b12', C3: '#5b5b66', lien: '#7c3f58', '': '#334155' }

  // La valeur OSM brute était affichée telle quelle sous chaque lieu : dix
  // fiches portaient « tourism » pour seule description.
  const LIBELLES_OSM = {
    amenity: 'Équipement', shop: 'Commerce', tourism: 'Tourisme',
    leisure: 'Loisirs', historic: 'Patrimoine', office: 'Bureau',
    craft: 'Artisanat', place: 'Lieu-dit',
  }
</script>

<svelte:head><title>Acteurs publics — {SITE_NOM}</title></svelte:head>

<div class="ap-page">
  <div class="page-header">
    <h1>Acteurs publics</h1>
    <span class="subtitle">{soustitre}</span>
  </div>

  <div class="controls">
    <input bind:value={search} placeholder="Rechercher…" class="search-input" />
    <div class="type-btns">
      <button class:active={typeFilter==='all'} on:click={() => typeFilter='all'}>
        Tous ({total})
      </button>
      {#each TYPES as t}
        <button class:active={typeFilter===t} on:click={() => typeFilter=t}
                style="--c:{TYPE_COLORS[t]}">
          {TYPE_LABELS[t]} ({counts[t]})
        </button>
      {/each}
    </div>
    <div class="type-btns perim-btns">
      {#each PERIMETRES as p}
        <button class:active={perimetre===p.key} on:click={() => perimetre = p.key}
                style="--c:{PERIM_COLORS[p.key]}" title={p.tip}>
          {p.label}
        </button>
      {/each}
    </div>
  </div>

  {#if tronques.length}
    <p class="avertissement">
      Liste coupée au plafond de {PLAFOND} fiches pour :
      {tronques.map(t => TYPE_LABELS[t]).join(', ')}. Les comptes ci-dessus sont
      donc des minima — restreindre le périmètre ou la recherche.
    </p>
  {/if}

  {#if error}<p class="err">{error}</p>{/if}

  {#if loading}
    <p class="muted-center">Chargement…</p>
  {:else if filtered.length === 0}
    <p class="muted-center">Aucun résultat.</p>
  {:else}
    <div class="entity-grid">
      {#each filtered as e}
        <a href="/entite/{e.id}" class="entity-card">
          <div class="card-header">
            <span class="type-dot" style="background:{TYPE_COLORS[e.type] ?? '#334155'}"></span>
            <span class="type-label">{TYPE_LABELS[e.type] ?? e.type}</span>
          </div>
          <div class="card-name">{e.name}</div>
          {#if e.address}
            <div class="card-addr muted">{e.address}</div>
          {/if}
          {#if e.service_category || e.osm_category}
            <div class="card-cat muted" title={e.osm_value ?? ''}>
              {e.service_category ?? LIBELLES_OSM[e.osm_category] ?? e.osm_category}
            </div>
          {/if}
        </a>
      {/each}
    </div>
  {/if}
</div>

<style>
  .ap-page { padding: 1.2rem; max-width: 1100px; overflow-y: auto; }
  .page-header { margin-bottom: .8rem; }
  h1 { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .subtitle { font-size: .78rem; color: #64748b; }

  .controls { display: flex; align-items: center; gap: .75rem; margin-bottom: .85rem; flex-wrap: wrap; }
  .search-input { background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
    border-radius: 6px; padding: .3rem .65rem; font-size: .8rem; width: 220px; }
  .search-input:focus { outline: none; border-color: #3b82f6; }
  .type-btns { display: flex; gap: .3rem; flex-wrap: wrap; }
  .type-btns button { background: #1e293b; border: 1px solid #334155; color: #94a3b8;
    border-radius: 5px; padding: .25rem .55rem; font-size: .75rem; cursor: pointer; }
  .type-btns button.active { border-color: var(--c, #3b82f6); color: #e2e8f0; }

  .entity-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap: .5rem; }
  .entity-card { background: #1e293b; border: 1px solid #334155; border-radius: 7px;
    padding: .6rem .75rem; text-decoration: none; display: block; transition: border-color .12s; }
  .entity-card:hover { border-color: #60a5fa; }
  .card-header { display: flex; align-items: center; gap: .35rem; margin-bottom: .3rem; }
  .type-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .type-label { font-size: .65rem; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }
  .card-name { font-size: .82rem; font-weight: 600; color: #e2e8f0; line-height: 1.3; }
  .card-addr, .card-cat { font-size: .71rem; margin-top: .2rem;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .muted { color: #64748b; }

  .perim-btns { margin-left: auto; }
  .avertissement { color: #fbbf24; font-size: .78rem; background: #1e293b;
    border: 1px solid #92400e; border-radius: 6px; padding: .4rem .6rem; margin-bottom: .7rem; }

  .err { color: #f87171; font-size: .83rem; }
  .muted-center { color: #64748b; text-align: center; margin-top: 2rem; }
</style>
