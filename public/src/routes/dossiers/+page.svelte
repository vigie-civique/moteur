<script>
  import { CONTACT_EMAIL, SITE_NOM } from '$lib/instance.js'

  export let data
  $: publies = data.dossiers.filter((d) => d.statut !== 'a_developper')
  $: annonces = data.dossiers.filter((d) => d.statut === 'a_developper')

  const fmt = (d) => {
    try { return new Date(d + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) }
    catch { return d }
  }
</script>

<svelte:head>
  <title>Dossiers thématiques - {SITE_NOM}</title>
  <meta name="description" content="Dossiers thématiques : des faits sourcés reliés autour d'une question d'intérêt public, avec ce que nous ne savons pas encore." />
</svelte:head>

<section>
  <h1>Dossiers thématiques</h1>
  <p class="chapeau">
    Le reste du site est de la donnée publique, rangée. Ici, nous écrivons&nbsp;:
    un dossier relie des faits épars autour d'une question, ce que l'on paie,
    qui décide, depuis quand, et dit ce que nous ne savons pas encore. Chaque
    fait renvoie à sa source. Une personne citée peut répondre par la page
    <a href="/contact">Droit de réponse</a>{#if CONTACT_EMAIL} ou à
    <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>{/if}.
  </p>

  {#if !data.dossiers.length}
    <p class="vide">Aucun dossier n'est publié pour l'instant.</p>
  {/if}

  {#if publies.length}
    <ul class="liste">
      {#each publies as d}
        <li>
          <a href="/dossiers/{d.slug}">{d.titre}</a>
          {#if d.statut === 'brouillon'}<span class="brouillon">brouillon</span>{/if}
          {#if d.chapeau}<p>{d.chapeau}</p>{/if}
          {#if d.maj}<p class="maj">Mis à jour le {fmt(d.maj)}</p>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if data.sujets?.length}
    <h2>{data.dossiers.length ? 'Sans dossier écrit' : 'Ce que les données disent de…'}</h2>
    <p class="aide">Des sujets que personne n'a encore instruits ici, mais sur lesquels les sources publiques ont déjà des faits&nbsp;: les voici, sans commentaire.</p>
    <ul class="liste">
      {#each data.sujets as s}
        <li><b>{s.titre}</b>
          <p>{#each s.sections as sec, i}{#if i} · {/if}<a href="{sec.page}{sec.ancre ? `#${sec.ancre}` : ''}">{sec.titre}</a>{/each}</p>
        </li>
      {/each}
    </ul>
  {/if}

  {#if annonces.length}
    <h2>En préparation</h2>
    <p class="aide">Sujets identifiés, pas encore instruits&nbsp;: la page annonce le sujet, rien de plus.</p>
    <ul class="liste">
      {#each annonces as d}
        <li><a href="/dossiers/{d.slug}">{d.titre}</a>{#if d.chapeau}<p>{d.chapeau}</p>{/if}</li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  section { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 3rem; color: var(--encre); }
  h1 { font-size: 1.85rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  .chapeau { color: var(--gris); max-width: 62ch; line-height: 1.6; margin: 0 0 1.5rem; }
  .chapeau a { color: var(--ardoise); }
  .aide { color: var(--gris); font-size: .88rem; margin: 0 0 .8rem; }
  .vide { max-width: 62ch; border-left: 3px solid var(--trait); padding: .1rem 0 .1rem 1rem; color: var(--gris); }
  .liste { list-style: none; padding: 0; margin: 0; }
  .liste li { padding: .9rem 0; border-bottom: 1px solid var(--trait-pale); }
  .liste a { font-weight: 600; font-size: 1.05rem; color: var(--ardoise); }
  .liste p { margin: .3rem 0 0; line-height: 1.5; font-size: .92rem; max-width: 66ch; }
  .maj { color: var(--gris); font-size: .8rem; }
  .brouillon { margin-left: .5rem; font-size: .68rem; font-weight: 700; text-transform: uppercase;
               color: #8a4b00; background: #fdebd0; border-radius: .5rem; padding: .1rem .45rem; }
</style>
