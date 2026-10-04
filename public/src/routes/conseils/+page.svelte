<script>
  import { SITE_NOM } from '$lib/instance.js'

  // Rendu au build par +page.server.js.
  export let data
  $: seances = data.seances || []
  $: annees = [...new Set(seances.map((s) => s.date.slice(0, 4)))].sort().reverse()

  const fmt = (d) => {
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
</script>

<svelte:head>
  <title>Les conseils en clair — {SITE_NOM}</title>
  <meta name="description" content="Chaque séance du conseil municipal et du conseil communautaire en trois feuilles : ce qui était annoncé, ce qui a été décidé, et ce que les documents publics ont de faux ou d'incomplet." />
</svelte:head>

<section>
  <p class="fil"><a href="/qui-decide">Qui décide</a> › Les conseils en clair</p>
  <h1>Les conseils en clair</h1>
  <p class="chapeau">
    Chaque séance en trois feuilles A4&nbsp;: ce qui était annoncé, ce qui a été
    décidé, et ce que les documents publics ont de faux ou d'incomplet. Chaque
    chiffre renvoie à la pièce qui l'établit, citée en bas de page.
  </p>
  <p class="aide">
    Ces feuilles sont rédigées à partir des procès-verbaux et délibérations, puis
    vérifiées automatiquement et relues par une personne avant d'être publiées.
    Une séance absente de cette liste n'a pas encore été relue.
  </p>

  {#if data.seances === null}
    <p class="vide">Ces feuilles n'existaient pas encore lors de la dernière publication des données.</p>
  {:else if !seances.length}
    <p class="vide">Aucune séance n'a encore été relue et publiée.</p>
  {:else}
    {#each annees as a}
      <h2>{a}</h2>
      <ol class="seances">
        {#each seances.filter((s) => s.date.startsWith(a)).reverse() as s}
          <li>
            <span class="nature" class:cc={s.code === 'cc'}>{s.code === 'cc' ? 'Communauté de communes' : 'Conseil municipal'}</span>
            <a href="/data/{s.fichier}"><time datetime={s.date}>{fmt(s.date)}</time> — {s.titre}</a>
            <span class="quand">
              {#if s.actes}{s.actes} délibération{s.actes > 1 ? 's' : ''}, dont {s.unanimite} à l'unanimité ·{/if}
              relu le {s.relu_le}
            </span>
          </li>
        {/each}
      </ol>
    {/each}
  {/if}
</section>

<style>
  section { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  .fil { font-size: .82rem; color: var(--gris); margin: 0 0 .5rem; }
  .fil a, .chapeau a { color: var(--ardoise); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 .6rem; }
  .aide { color: var(--gris); font-size: .88rem; max-width: 66ch; line-height: 1.55; margin: 0 0 .8rem; }
  .vide { max-width: 62ch; border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem;
          color: var(--gris); line-height: 1.6; }
  .seances { list-style: none; padding: 0; margin: 0; }
  .seances li { display: flex; flex-wrap: wrap; gap: .2rem .7rem; align-items: baseline;
                padding: .6rem 0; border-bottom: 1px solid var(--trait-pale); font-size: .92rem; }
  .seances a { flex: 1; min-width: 14rem; color: var(--ardoise); overflow-wrap: anywhere; }
  .seances time { font-weight: 600; }
  .nature { font-size: .68rem; font-weight: 700; text-transform: uppercase; color: var(--ardoise-fonce);
            background: var(--ardoise-pale); border-radius: .5rem; padding: .1rem .45rem; }
  .nature.cc { background: var(--trait-pale); color: var(--encre); }
  .quand { flex-basis: 100%; color: var(--gris); font-size: .8rem; font-variant-numeric: tabular-nums; }
</style>
