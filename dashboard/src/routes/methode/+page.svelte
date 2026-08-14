<script>
  import { COMMUNE_URL, LA_COMMUNE, SITE_NOM } from '$lib/instance.js'
  import { stats } from '$lib/stores/app.js'
</script>

<svelte:head>
  <title>Méthodologie — {SITE_NOM}</title>
</svelte:head>

<div class="page">
  <div class="content">
    <h1>Methodologie et sources</h1>

    <section>
      <h2>Principes</h2>
      <ul>
        <li><strong>Sources exclusivement publiques</strong> : registres officiels (SIRENE, RNA, DVF), comptes-rendus du conseil municipal, presse locale, OpenStreetMap.</li>
        <li><strong>Niveaux de confiance</strong> : chaque information est classee <em>verified</em>, <em>confirmed</em>, <em>probable</em>, <em>hypothesis</em> ou <em>unverified</em>. Seules les informations <em>verified</em> et <em>confirmed</em> entrent dans le snapshot public.</li>
        <li><strong>Mise a jour</strong> : les donnees sont collectees periodiquement depuis les APIs publiques. La date de derniere mise a jour est indiquee pour chaque source.</li>
        <li><strong>Transparence</strong> : le code source de cet outil est disponible. Toute erreur peut etre signalee via le formulaire de contact.</li>
      </ul>
    </section>

    <section>
      <h2>Sources de donnees</h2>
      <div class="sources-grid">
        <div class="src-card">
          <h3>SIRENE</h3>
          <p>Registre national des entreprises et etablissements. API recherche-entreprises.api.gouv.fr.</p>
          <p class="src-url">Donnees : SIREN, NAF, dirigeants, statut, adresse.</p>
        </div>
        <div class="src-card">
          <h3>RNA / Journal Officiel</h3>
          <p>Repertoire National des Associations. Extraction partielle par departement.</p>
          <p class="src-url">Donnees : identifiant RNA, objet, date de creation.</p>
        </div>
        <div class="src-card">
          <h3>DVF (Demandes de Valeurs Foncieres)</h3>
          <p>Transactions immobilieres publiees par la DGFiP. API Cerema.</p>
          <p class="src-url">Donnees : date, nature, prix, surface, localisation.</p>
        </div>
        <div class="src-card">
          <h3>Conseil municipal</h3>
          <p>Comptes-rendus publiés sur {COMMUNE_URL || 'le site de la mairie'}. Analyse automatique des délibérations, votes, subventions.</p>
          <p class="src-url">Donnees : deliberations, montants, votes, presences.</p>
        </div>
        <div class="src-card">
          <h3>OpenStreetMap</h3>
          <p>Points d'interet (POI) via l'API Overpass.</p>
          <p class="src-url">Donnees : commerces, services, lieux publics.</p>
        </div>
        <div class="src-card">
          <h3>OFGL</h3>
          <p>Observatoire des Finances et de la Gestion publique Locale.</p>
          <p class="src-url">Donnees : budgets, ratios financiers, evolution 2017-2024.</p>
        </div>
      </div>
    </section>

    <section>
      <h2>Statistiques actuelles</h2>
      {#if $stats}
        <div class="stats-grid">
          <div class="stat"><span>{$stats.businesses ?? 0}</span> entreprises</div>
          <div class="stat"><span>{$stats.associations ?? 0}</span> associations</div>
          <div class="stat"><span>{$stats.persons ?? 0}</span> personnes</div>
          <div class="stat"><span>{$stats.services ?? 0}</span> services publics</div>
          <div class="stat"><span>{$stats.places ?? 0}</span> lieux / POI</div>
          <div class="stat"><span>{$stats.relations ?? 0}</span> relations</div>
          <div class="stat"><span>{$stats.events ?? 0}</span> deliberations</div>
          <div class="stat"><span>{$stats.dvf_transactions ?? 0}</span> transactions DVF</div>
          <div class="stat"><span>{$stats.financial_flows ?? 0}</span> flux financiers</div>
        </div>
      {/if}
    </section>

    <section>
      <h2>Limites connues</h2>
      <ul>
        <li>Les noms des dirigeants d'associations ne sont plus disponibles dans le RNA depuis 2016 (retrait JOAFE pour raisons de vie privee).</li>
        <li>{LA_COMMUNE} est sous le seuil de 20 000 habitants : les declarations HATVP ne sont pas obligatoires pour les elus.</li>
        <li>Les marches publics sous 25 000 EUR ne sont pas publies (DECP/BOAMP).</li>
        <li>Les PDFs des comptes-rendus du conseil municipal ne sont pas accessibles directement (protection serveur). Le texte est extrait des pages HTML.</li>
      </ul>
    </section>

    <section>
      <h2>Contact et droit de reponse</h2>
      <p>Toute personne mentionnee dans cet outil peut exercer son droit de reponse ou signaler une erreur en ecrivant a l'adresse indiquee dans les mentions legales.</p>
    </section>
  </div>
</div>

<style>
  .page {
    flex: 1;
    overflow-y: auto;
    width: 100%;
  }
  .content {
    max-width: 900px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
  }
  h1 { font-size: 1.3rem; font-weight: 700; margin-bottom: 1.5rem; }
  section { margin-bottom: 2rem; }
  h2 {
    font-size: .95rem;
    font-weight: 700;
    color: #60a5fa;
    margin-bottom: .75rem;
    text-transform: uppercase;
    letter-spacing: .03em;
  }
  ul { padding-left: 1.2rem; }
  li { font-size: .85rem; line-height: 1.6; color: #cbd5e1; margin-bottom: .3rem; }

  .sources-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: .75rem;
  }
  .src-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: .75rem 1rem;
  }
  .src-card h3 { font-size: .85rem; font-weight: 600; margin-bottom: .3rem; }
  .src-card p { font-size: .78rem; color: #94a3b8; line-height: 1.4; }
  .src-url { color: #475569; font-size: .72rem; margin-top: .2rem; }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: .5rem;
  }
  .stat {
    background: #1e293b;
    border-radius: 8px;
    padding: .5rem .75rem;
    font-size: .82rem;
    color: #94a3b8;
  }
  .stat span { font-weight: 700; color: #60a5fa; font-size: 1.1rem; margin-right: .3rem; }
</style>
