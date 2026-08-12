<script>
  import Niveau from '$lib/components/Niveau.svelte'

  // Rendu au build par +page.server.js.
  export let data
  $: c = data.couverture

  const ETATS = {
    partiel: 'Partiel',
    incomplet: 'Incomplet',
    absent: 'Absent',
  }

  const fmt = (d) => {
    if (!d) return '—'
    try { return new Date(d.slice(0, 10) + 'T00:00:00').toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return d }
  }
  const nb = (n) => (n == null ? '—' : n.toLocaleString('fr-FR'))

  // Un collecteur qui n'a pas tourné depuis longtemps est une lacune en
  // formation : elle ne se voit pas encore dans les compteurs.
  const JOURS = 45
  $: dormants = Object.entries(c?.collecteurs || {})
    .filter(([, v]) => {
      if (!v.dernier) return true
      const j = (Date.now() - new Date(v.dernier.replace(' ', 'T')).getTime()) / 864e5
      return j > JOURS
    })
    .sort((a, b) => (a[1].dernier || '').localeCompare(b[1].dernier || ''))
</script>

<svelte:head>
  <title>Couverture et lacunes — Vigie Civique Lasalle</title>
  <meta name="description" content="Ce que la collecte couvre et ce qu'elle ne couvre pas : périodes par source, fraîcheur des collecteurs, documents manquants et limites connues." />
</svelte:head>

<section>
  <h1>Couverture et lacunes</h1>
  <p class="chapeau">
    Un observatoire qui n'affiche que ce qu'il sait ressemble à une boîte noire&nbsp;:
    rien ne permet alors de distinguer « il ne s'est rien passé cette année-là » de
    « nous n'avons pas collecté cette année-là ». Cette page donne l'inverse — les
    limites de ce qui est publié ici.
  </p>

  {#if !c?.sources?.length}
    <p class="muted">Données de couverture indisponibles.</p>
  {:else}
    <h2>Le point faible principal</h2>
    <!-- Donné en premier, et non enfoui : c'est le chiffre qui affaiblit le
         plus les affirmations du site, donc celui qu'il serait le plus
         malhonnête de laisser découvrir au lecteur. -->
    <Niveau type="calcul" base="les actes publiés et leurs liens de source">
      <b>{c.part_avec_piece} %</b> des actes publiés
      ({nb(c.actes_avec_piece)} sur {nb(c.actes_total)}) renvoient vers
      <b>le document de l'acte lui-même</b>. Pour tous les autres, le lien mène à
      la page qui le contient — le plus souvent le compte rendu entier d'une
      séance, dans lequel il faut chercher le passage.
    </Niveau>
    <p class="apres">
      « Sourcé » ne veut donc pas encore dire « vérifiable en un clic ». Chaque
      acte porte cette indication sur sa propre ligne, dans
      <a href="/deliberations">les délibérations</a>.
    </p>

    <h2>Période couverte, par source</h2>
    <div class="tableau">
      <table>
        <thead>
          <tr><th>Source</th><th class="r">Actes</th><th>Période</th><th class="r">Avec la pièce</th></tr>
        </thead>
        <tbody>
          {#each c.sources as s}
            <tr>
              <td>{s.source}</td>
              <td class="r">{nb(s.actes)}</td>
              <td class="periode">{fmt(s.debut)} → {fmt(s.fin)}</td>
              <td class="r">
                {#if s.avec_document}{nb(s.avec_document)}{:else}<span class="zero">aucune</span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note">
      Une période qui commence tard ne signifie pas que rien n'existait avant&nbsp;:
      elle indique le point à partir duquel la source publie, ou à partir duquel
      nous collectons.
    </p>

    <h2>Fraîcheur de la collecte</h2>
    {#if dormants.length}
      <p>
        {dormants.length} collecteur{dormants.length > 1 ? 's n\'ont' : ' n\'a'} pas
        tourné depuis plus de {JOURS} jours. Les données qu'il{dormants.length > 1 ? 's alimentent' : ' alimente'}
        peuvent être en retard sur la réalité, sans que rien ne le signale ailleurs sur le site.
      </p>
      <ul class="dormants">
        {#each dormants as [nom, v]}
          <li><b>{nom}</b> — dernier passage {v.dernier ? fmt(v.dernier) : 'jamais'}
            {#if v.statut && v.statut !== 'ok'}<span class="statut">({v.statut})</span>{/if}
          </li>
        {/each}
      </ul>
    {:else}
      <p>Tous les collecteurs ont tourné dans les {JOURS} derniers jours.</p>
    {/if}

    <h2>Ce que nous ne savons pas faire</h2>
    <ul class="lacunes">
      {#each c.lacunes_connues || [] as l}
        <li class={l.etat}>
          <p class="sujet">{l.sujet} <span class="etat">{ETATS[l.etat] || l.etat}</span></p>
          <p class="detail">{l.detail}</p>
        </li>
      {/each}
    </ul>

    <p class="liens">
      <a href="/methode">Méthode et sources</a> ·
      <a href="/contact">Signaler une erreur ou une source manquante</a>
    </p>
  {/if}
</section>

<style>
  section { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .6rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 1.5rem; }
  .apres { margin: .35rem 0 0; font-size: .9rem; color: var(--gris); }
  .apres a, .liens a { color: var(--ardoise); }
  .note { font-size: .82rem; color: var(--gris-clair); margin: .5rem 0 0; line-height: 1.5; }
  .muted { color: var(--gris-clair); }

  /* Le tableau doit défiler dans son propre cadre : sur téléphone, c'est le
     premier élément qui pousse la page à déborder horizontalement. */
  .tableau { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: .88rem; min-width: 30rem; }
  th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--trait); }
  th { font-size: .72rem; text-transform: uppercase; letter-spacing: .02em; color: var(--gris); }
  .r { text-align: right; font-variant-numeric: tabular-nums; }
  .periode { color: var(--gris); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .zero { color: var(--ambre); }

  .dormants { list-style: none; padding: 0; margin: .6rem 0 0; font-size: .9rem; color: var(--gris); }
  .dormants li { padding: .25rem 0; }
  .dormants b { color: var(--encre); }
  .statut { color: var(--ambre); font-size: .82rem; }

  .lacunes { list-style: none; padding: 0; margin: .6rem 0 0; display: grid; gap: .6rem; }
  .lacunes li { border-left: 3px solid var(--trait); padding: .6rem .9rem;
                background: var(--papier); border-radius: 0 var(--rayon) var(--rayon) 0; }
  .lacunes li.absent { border-left-color: var(--depense); }
  .lacunes li.incomplet { border-left-color: var(--ambre); }
  .lacunes li.partiel { border-left-color: var(--gris); }
  .sujet { margin: 0 0 .2rem; font-weight: 600; display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline; }
  .etat { font-size: .68rem; text-transform: uppercase; letter-spacing: .04em;
          color: var(--gris); border: 1px solid var(--trait); border-radius: 99px; padding: .05rem .45rem; }
  .detail { margin: 0; font-size: .88rem; line-height: 1.55; color: var(--gris); }

  .liens { margin-top: 2rem; font-size: .88rem; }
</style>
