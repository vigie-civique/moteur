<script>
  import { SITE_NOM, CONTACT_EMAIL, EDITEUR_NOM } from '$lib/instance.js'

  // Compte de l'association porteuse (Qonto), le même pour toutes les instances.
  // Clé de contrôle vérifiée le 07/09/2026. Vider IBAN replie sur le courriel.
  const IBAN = 'FR76 1695 8000 0141 1078 0382 249'
  const BIC = 'QNTOFRP1XXX'
  const TITULAIRE = 'Association À Bout de Champ'
  const HELLOASSO = 'https://www.helloasso.com/beta/associations/a-bout-de-champ/adhesions/adhesion/'
</script>

<svelte:head><title>Soutenir - {SITE_NOM}</title>
  <meta name="description" content="Adhérer à l'association qui édite ce site, ou la soutenir par un don : par carte via HelloAsso ou par virement." /></svelte:head>

<section>
  <h1>Soutenir</h1>
  <p>
    Ce site est gratuit, sans compte et sans publicité. Il est édité par {EDITEUR_NOM}, association
    loi 1901. Adhérer ou donner finance le serveur qui collecte les données, sans rien acheter dans
    le contenu : aucune influence sur ce qui est publié ou omis.
  </p>

  <div class="card">
    <h2>Par carte, via HelloAsso</h2>
    <p>Adhésion à l'association, ponctuelle ou annuelle. HelloAsso ne prélève aucune commission : la
      plateforme se finance par une contribution volontaire, que vous pouvez ramener à zéro au paiement.</p>
    <p><a class="bouton" href={HELLOASSO} target="_blank" rel="noreferrer">Adhérer ou donner sur HelloAsso ↗</a></p>
  </div>

  {#if IBAN}
  <div class="card">
    <h2>Par virement</h2>
    <p>Aucune commission : la totalité arrive à l'association.</p>
    <dl>
      <div><dt>Titulaire</dt><dd>{TITULAIRE}</dd></div>
      <div><dt>IBAN</dt><dd><code>{IBAN}</code></dd></div>
      {#if BIC}<div><dt>BIC</dt><dd><code>{BIC}</code></dd></div>{/if}
    </dl>
    <p>Indiquez « soutien » en libellé.</p>
  </div>
  {/if}

  <p class="note">
    Les dons n'ouvrent pas, à ce jour, droit à réduction d'impôt : aucun reçu fiscal ne peut être
    délivré. Une question : <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.
  </p>
</section>

<style>
  section { max-width: 720px; margin: 0 auto; padding: 1.5rem; line-height: 1.6; }
  h1 { color: var(--encre); }
  h2 { font-size: 1.1rem; margin: 0 0 .5rem; }
  .card { background: #fff; border: 1px solid var(--trait); border-radius: 10px; padding: 1.25rem; margin: 1rem 0; }
  .bouton { display: inline-block; padding: .55rem 1rem; border-radius: 8px; background: var(--encre); color: #fff; font-weight: 600; text-decoration: none; }
  dl div { display: flex; gap: 1rem; padding: .25rem 0; flex-wrap: wrap; }
  dt { width: 6rem; color: var(--gris); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .note { color: var(--gris); font-size: .9rem; }
</style>
