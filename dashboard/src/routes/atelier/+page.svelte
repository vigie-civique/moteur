<script>
  // « Aujourd'hui » — la porte d'entrée de l'atelier depuis le 23/09/2026.
  //
  // Avant : une liste de 5 484 fiches `unverified`, triée par type et par nom.
  // Rien n'y disait ce qu'on attendait de vous, ni combien il restait, ni si
  // quelqu'un d'autre s'en occupait. Elle n'a pas disparu — c'est la seule
  // porte vers les 22 783 fiches — mais elle est devenue une VUE EXPERTE
  // (/atelier/fiches), et ce n'est plus par là qu'on arrive.
  //
  // Le registre des files vit dans `collectors/files.py`, pas ici : cette page
  // n'invente aucune question et ne compte rien elle-même.
  import { COMMUNE } from '$lib/instance.js'
  import { onMount } from 'svelte'
  import { authFetch, currentUser } from '$lib/stores/auth.js'
  import { auMoins, LIBELLE_ROLE } from '$lib/roles.js'
  import { heureLocale } from '$lib/heure.js'

  let files   = []
  let minutes = 10
  let jour    = { miens: [], herites: [] }
  let loading = true
  let error   = ''
  let toutVoir = false

  onMount(async () => {
    try {
      const res = await authFetch('/atelier/files')
      if (!res.ok) throw new Error(`${res.status}`)
      const d = await res.json()
      files = d.files
      minutes = d.reservation_minutes
      jour = d.premier_jour ?? jour
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })

  $: aFaire  = files.filter(f => !f.experte)
  $: expertes = files.filter(f => f.experte)
  $: reste = aFaire.reduce((n, f) => n + (f.reste ?? 0), 0)

  // Les milliers se séparent ici, sans passer par `Intl` : selon la version de
  // Chrome et les données de locale présentes sur la machine — un VPS en sert
  // parfois un jeu minimal — `toLocaleString('fr-FR')` rend « 1 128 » ou
  // « 1128 ». Constaté à l'écran le 23/09/2026 sur cette page même, où
  // l'en-tête séparait et pas les cartes. L'espace est insécable : un nombre
  // ne se coupe pas en fin de ligne.
  const nb = n => String(n ?? 0).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

  // ⭐ Un zéro ne s'affiche JAMAIS nu : il dit d'où il vient. Une file vide
  // parce que le détecteur a cherché et n'a rien trouvé, et une file vide
  // parce qu'il n'a jamais tourné ici, ne racontent pas la même chose — et
  // c'est la seconde qui trompe, parce qu'elle a l'air d'un travail fini.
  function raisonDuZero(f) {
    const p = f.derniere_passe
    if (!p) return "Aucune passe de collecte connue pour cette file : ce zéro "
                 + "n'a jamais été mesuré ici."
    const quand = p.le ? heureLocale(p.le) : 'à une date inconnue'
    if (p.issue === 'error' || p.issue === 'timeout')
      return `Le dernier passage de « ${p.collecteur} » (${quand}) a échoué : `
           + `ce zéro dit l'échec, pas l'absence.`
    return `« ${p.collecteur} » est passé ${quand} et n'a rien trouvé de neuf. `
         + `Rien n'attend un geste pour l'instant.`
  }
</script>

<svelte:head><title>Aujourd'hui — Atelier {COMMUNE}</title></svelte:head>

<div class="page">

  <header class="entete">
    <div>
      <h1>Aujourd'hui</h1>
      <p class="sous-titre">
        Ce qui attend un regard sur {COMMUNE}.
        {#if $currentUser}
          Vous êtes <strong>{LIBELLE_ROLE[$currentUser.role] ?? $currentUser.role}</strong>.
        {/if}
      </p>
    </div>
    {#if !loading && !error}
      <p class="compte-global">
        <strong>{nb(reste)}</strong> à regarder
      </p>
    {/if}
  </header>

  {#if loading}
    <p class="msg">Relevé des files…</p>
  {:else if error}
    <p class="msg erreur">Les files n'ont pas pu être relevées ({error}).</p>
  {:else}

    <div class="files">
      {#each aFaire as f (f.cle)}
        {@const ouvert = auMoins($currentUser, f.role_min)}
        <section class="file" class:vide={f.reste === 0} class:ferme={!ouvert}>
          <h2>{f.titre}</h2>
          <p class="question">{f.question}</p>

          {#if f.indisponible}
            <p class="raison">
              Cette file n'a pas pu être relevée sur cette base. Les autres ne
              sont pas concernées.
            </p>
          {:else if f.reste === 0}
            <p class="raison">{raisonDuZero(f)}</p>
          {:else}
            <p class="reste"><strong>{nb(f.reste)}</strong> en attente</p>
          {/if}

          {#if f.fait > 0}
            <p class="avancement">{nb(f.fait)} déjà tranché{f.fait > 1 ? 's' : ''}.</p>
          {/if}

          <!-- « Repérer les chantiers en cours » est la demande d'origine : la
               réservation existait depuis le premier lot, mais rien ne la
               montrait en dehors de la file elle-même. -->
          {#each f.en_cours as c}
            <p class="en-cours">
              {c.par} en a {c.combien} en cours
              {#if c.depuis}depuis {heureLocale(c.depuis)}{/if}
              <span class="expire">— la réservation retombe au bout de {minutes} min</span>
            </p>
          {/each}

          <p class="geste">{f.geste}.</p>
          <p class="effet">{f.effet}</p>

          {#if ouvert && f.reste !== 0}
            <!-- Quand la file a un écran de décision, « Commencer » ouvre UNE
                 question avec ses preuves, pas un tableau. La vue d'ensemble
                 reste atteignable juste à côté : on ne supprime une liste
                 qu'en la remplaçant. -->
            {#if f.premier}
              <a class="bouton"
                 href="/atelier/decision/{f.premier.objet}/{f.premier.id}">Commencer</a>
              <a class="discret-lien" href={f.route}>ou voir la liste entière</a>
            {:else}
              <a class="bouton" href={f.route}>Commencer</a>
            {/if}
          {:else if ouvert}
            <a class="bouton discret" href={f.route}>Regarder quand même</a>
          {:else}
            <!-- Lot D : ce qu'un rôle ne peut pas faire doit se VOIR, pas
                 s'apprendre par un 403 qui parle de clé d'administration. -->
            <p class="interdit">
              Trancher ici demande le rôle
              « {LIBELLE_ROLE[f.role_min] ?? f.role_min} ».
              <a href={f.route}>Vous pouvez regarder la file</a>.
            </p>
          {/if}
        </section>
      {/each}
    </div>

    <!-- Lot D — ce qu'on peut faire en arrivant. Un contributeur qui se
         connectait n'avait, jusqu'au 23/09/2026, aucun geste qui compte : le
         seul qui lui était ouvert écrivait dans une colonne que la publication
         ne lisait pas. Trois gestes, et ce que chacun APPORTE. -->
    {#if jour.miens.length}
      <section class="premier-jour">
        <h2>Ce que vous pouvez faire</h2>
        <ul>
          {#each jour.miens as g}
            <li>
              <a href={g.route}>{g.titre}</a>
              <p>{g.pourquoi}</p>
            </li>
          {/each}
        </ul>
        {#if jour.herites.length}
          <p class="herite">
            Votre rôle vous ouvre aussi {jour.herites.length} gestes plus
            simples.
            <button class="lien-nu" on:click={() => toutVoir = !toutVoir}>
              {toutVoir ? 'les replier' : 'les voir'}
            </button>
          </p>
          {#if toutVoir}
            <ul class="herites">
              {#each jour.herites as g}
                <li><a href={g.route}>{g.titre}</a> <p>{g.pourquoi}</p></li>
              {/each}
            </ul>
          {/if}
        {/if}
      </section>
    {/if}

    {#each expertes as f (f.cle)}
      <section class="experte">
        <h2>{f.titre} <span class="etiquette">vue experte</span></h2>
        <p>
          {nb(f.reste)} fiches n'ont jamais été relues, sur {nb((f.reste ?? 0) + (f.fait ?? 0))}.
          <strong>C'est normal, et ce n'est pas une tâche</strong> : une fiche
          jamais relue continue d'être publiée si les règles l'admettent — sans
          quoi le site se viderait. C'est la seule porte vers toutes les fiches.
        </p>
        <a class="bouton discret" href={f.route}>Ouvrir la liste complète</a>
      </section>
    {/each}

  {/if}
</div>

<style>
  /* Tailles et contrastes choisis pour une salle communale et un portable
     qu'on ne choisit pas : rien sous 13 px, rien en dessous de #94a3b8 sur le
     fond sombre. Le reste de l'atelier est encore en gris 11 px — lot F. */
  .page {
    padding: 1.2rem 1.4rem 2rem;
    max-width: 68rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }

  .entete {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  h1 { font-size: 1.5rem; font-weight: 700; color: #f1f5f9; margin: 0; }
  .sous-titre { font-size: .95rem; color: #94a3b8; margin: .3rem 0 0; }
  .sous-titre strong { color: #cbd5e1; font-weight: 600; }
  .compte-global { font-size: .95rem; color: #94a3b8; margin: 0; }
  .compte-global strong { font-size: 1.5rem; color: #f1f5f9; }

  .msg { font-size: .95rem; color: #94a3b8; }
  .msg.erreur { color: #fca5a5; }

  .files {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr));
    gap: .9rem;
  }

  .file {
    display: flex;
    flex-direction: column;
    gap: .45rem;
    padding: 1rem 1.1rem 1.1rem;
    border: 1px solid #334155;
    border-radius: .5rem;
    background: #111a2b;
  }
  .file.vide { background: #0f1626; border-color: #263449; }
  .file.ferme { opacity: .92; }

  .file h2 {
    font-size: .8rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: #94a3b8;
    margin: 0;
  }
  .question {
    font-size: 1.12rem;
    line-height: 1.35;
    color: #f1f5f9;
    margin: 0;
  }

  .reste { font-size: .95rem; color: #cbd5e1; margin: 0; }
  .reste strong { font-size: 1.6rem; color: #f8fafc; font-weight: 700; }

  /* Un zéro avec sa raison : lisible, pas une note de bas de page. */
  .raison { font-size: .9rem; line-height: 1.45; color: #94a3b8; margin: 0; }

  .avancement { font-size: .85rem; color: #94a3b8; margin: 0; }

  .en-cours {
    font-size: .85rem;
    color: #fcd34d;
    background: #2a2412;
    border-radius: .3rem;
    padding: .35rem .5rem;
    margin: 0;
  }
  .expire { color: #a1893f; }

  .geste { font-size: .95rem; color: #cbd5e1; margin: .25rem 0 0; }
  .effet { font-size: .85rem; line-height: 1.45; color: #94a3b8; margin: 0; }

  .bouton {
    align-self: flex-start;
    margin-top: .45rem;
    padding: .45rem .9rem;
    border-radius: .3rem;
    background: #3b82f6;
    color: #fff;
    font-size: .92rem;
    font-weight: 600;
    text-decoration: none;
  }
  .bouton:hover { background: #2563eb; }
  .bouton.discret {
    background: transparent;
    color: #93c5fd;
    border: 1px solid #334155;
  }
  .bouton.discret:hover { background: #1e293b; }
  .discret-lien { font-size: .82rem; color: #93c5fd; margin-top: .3rem; }

  .interdit { font-size: .85rem; line-height: 1.45; color: #94a3b8; margin: .25rem 0 0; }
  .interdit a { color: #93c5fd; }

  .premier-jour {
    padding: 1rem 1.1rem; border: 1px solid #334155;
    border-radius: .5rem; background: #0f1626;
  }
  .premier-jour h2 {
    font-size: .8rem; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: #94a3b8; margin: 0 0 .7rem;
  }
  .premier-jour ul { list-style: none; padding: 0; margin: 0;
    display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: .8rem; }
  .premier-jour li { display: flex; flex-direction: column; gap: .2rem; }
  .premier-jour a { font-size: .98rem; font-weight: 600; color: #93c5fd; text-decoration: none; }
  .premier-jour a:hover { text-decoration: underline; }
  .premier-jour p { font-size: .85rem; line-height: 1.45; color: #94a3b8; margin: 0; }
  .herite { margin-top: .9rem !important; }
  .herites { margin-top: .6rem !important; opacity: .85; }
  .lien-nu {
    background: transparent; border: none; color: #93c5fd; cursor: pointer;
    font-size: .85rem; text-decoration: underline; padding: 0;
  }

  .experte {
    padding: 1rem 1.1rem;
    border: 1px dashed #334155;
    border-radius: .5rem;
    display: flex;
    flex-direction: column;
    gap: .5rem;
  }
  .experte h2 {
    font-size: .95rem; font-weight: 700; color: #cbd5e1; margin: 0;
    display: flex; align-items: center; gap: .5rem;
  }
  .etiquette {
    font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
    color: #94a3b8; border: 1px solid #334155; border-radius: .2rem;
    padding: .1rem .35rem; font-weight: 600;
  }
  .experte p { font-size: .9rem; line-height: 1.5; color: #94a3b8; margin: 0; }
  .experte strong { color: #cbd5e1; }

  /* Lot F en avance sur ce seul écran : à 820 px les cartes tiennent encore. */
  @media (max-width: 640px) {
    .page { padding: 1rem .9rem 2rem; }
    .files { grid-template-columns: 1fr; }
  }
</style>
