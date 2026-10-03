<script>
  import { heureLocale } from '$lib/heure.js'
  import { champLisible, valeurLisible } from '$lib/champs.js'

  export let audit = []
</script>

<section class="card">
  <h2>Historique des modifications</h2>
  {#if audit.length === 0}
    <p class="muted">Aucune modification enregistrée.</p>
  {:else}
    <div class="defile">
      <table class="audit-table">
        <thead>
          <tr><th>Date</th><th>Utilisateur</th><th>Champ</th><th>Avant</th><th>Après</th></tr>
        </thead>
        <tbody>
          {#each audit as a}
            <tr>
              <td>{heureLocale(a.at)}</td>
              <td>{a.user_email ?? '—'}</td>
              <td>{champLisible(a.field) ?? a.action}</td>
              <td class="old-val">{valeurLisible(a.field, a.old_value) ?? '—'}</td>
              <td class="new-val">{valeurLisible(a.field, a.new_value) ?? '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  .defile { overflow-x: auto; }
  .audit-table { width: 100%; border-collapse: collapse; font-size: .76rem; }
  .audit-table th {
    text-align: left; padding: .3rem .5rem; color: #94a3b8; font-weight: 600;
    font-size: .7rem; text-transform: uppercase; letter-spacing: .04em;
    border-bottom: 1px solid #334155;
  }
  .audit-table td {
    padding: .32rem .5rem; color: #94a3b8;
    border-bottom: 1px solid #1e293b; vertical-align: top;
  }
  .old-val { color: #f87171; text-decoration: line-through; }
  .new-val { color: #4ade80; }
</style>
