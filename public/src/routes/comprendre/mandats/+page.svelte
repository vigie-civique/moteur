<script>
  import Icon from '$lib/components/Icon.svelte'
</script>

<svelte:head>
  <title>Comprendre les mandats et les délibérations — Vigie Civique Lasalle</title>
  <meta name="description" content="Fiche pédagogique : conseil municipal, maire, adjoints, délégations — et comment lire une délibération ou demander un document administratif." />
</svelte:head>

<article>
  <p class="crumb"><a href="/comprendre">← Comprendre</a></p>
  <h1 class="avec-icone"><Icon name="elections" size={26} />Mandats, conseil municipal et délibérations</h1>

  <h2>Le conseil municipal</h2>
  <p>Élu pour <strong>six ans</strong>, il compte 15 conseillers dans une commune de la taille de
     Lasalle. C'est lui — pas le maire seul — qui vote le budget, les ventes de terrains communaux,
     les subventions aux associations, les créations de postes. Le maire prépare et exécute ;
     le conseil délibère.</p>

  <h2>Maire, adjoints, délégations</h2>
  <p>Le maire est élu par le conseil, pas directement par les habitants. Il délègue des domaines à
     ses <strong>adjoints</strong> (travaux, école, associations…) par arrêté. Ces
     <strong>délégations</strong> sont publiques : elles disent qui instruit réellement quoi.
     Un point de vigilance classique : quand le délégataire d'un domaine a des intérêts privés
     dans ce même domaine.</p>

  <h2>Lire une délibération</h2>
  <p>Chaque décision du conseil laisse une trace écrite : la <strong>délibération</strong>, résumée
     au compte-rendu de séance. Les bons réflexes :</p>
  <ul>
    <li><strong>Le vote</strong> — unanimité, abstentions, votes contre : une abstention isolée
        sur une vente de terrain est un signal.</li>
    <li><strong>Les montants</strong> — et leur comparaison dans le temps (une subvention qui
        triple, un loyer symbolique…).</li>
    <li><strong>Les absents et les « ne prend pas part au vote »</strong> — un élu concerné par une
        affaire doit se déporter ; le compte-rendu le mentionne (ou pas).</li>
  </ul>

  <h2>Vos droits d'accès</h2>
  <p>Les comptes-rendus, budgets, arrêtés et marchés sont des <strong>documents administratifs
     communicables</strong> : toute personne peut les demander à la mairie, sans motif. En cas de
     refus ou de silence d'un mois, la <strong>CADA</strong> (commission d'accès aux documents
     administratifs) peut être saisie gratuitement. Ce site archive par ailleurs les comptes-rendus
     publiés, y compris ceux retirés du site municipal depuis.</p>

  <p class="voir">
    Voir : <a href="/elus">Les élus et leurs mandats</a> ·
    <a href="/deliberations">Les délibérations</a> · <a href="/qui-decide">Qui décide</a>.
  </p>
</article>

<style>
  article { max-width: 760px; margin: 0 auto; padding: 1.5rem; line-height: 1.65; }
  h1 { color: var(--encre); } h2 { color: var(--encre); margin-top: 1.5rem; }
  .crumb a { color: var(--gris); font-size: .9rem; }
  .voir { margin-top: 1.6rem; padding: .9rem 1.1rem; background: var(--papier);
          border: 1px solid var(--trait); border-radius: 10px; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
