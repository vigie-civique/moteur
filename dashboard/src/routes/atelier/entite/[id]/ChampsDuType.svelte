<script>
  export let form
  export let modifies = []

  $: m = k => modifies.includes(k)
</script>

{#if form.type === 'person'}
  <section class="card">
    <h2>Personne</h2>
    <div class="grid2">
      <label class:modifie={m('firstname')}>Prénom<input bind:value={form.firstname} /></label>
      <label class:modifie={m('lastname')}>Nom de famille<input bind:value={form.lastname} /></label>
      <label class:modifie={m('birth_year')}>Année de naissance<input type="number" bind:value={form.birth_year} placeholder="1970" /></label>
      <label class:modifie={m('birth_month')}>Mois de naissance<input type="number" min="1" max="12" bind:value={form.birth_month} /></label>
      <label class:modifie={m('gender')}>
        Genre
        <select bind:value={form.gender}>
          <option value="">—</option>
          <option value="M">Masculin</option>
          <option value="F">Féminin</option>
        </select>
      </label>
    </div>
  </section>

{:else if form.type === 'business'}
  <section class="card">
    <h2>Entreprise</h2>
    <div class="grid2">
      <label class:modifie={m('naf_code')}>Code NAF<input bind:value={form.naf_code} placeholder="ex: 6820B" /></label>
      <label class:modifie={m('naf_label')}>Libellé NAF<input bind:value={form.naf_label} /></label>
      <label class:modifie={m('legal_form')}>Forme juridique<input bind:value={form.legal_form} /></label>
      <label class:modifie={m('biz_status')}>
        Statut
        <select bind:value={form.biz_status}>
          <option value="">—</option>
          <option value="A">Actif (A)</option>
          <option value="F">Fermé (F)</option>
        </select>
      </label>
      <label class:modifie={m('capital')}>Capital (€)<input type="number" bind:value={form.capital} /></label>
      <label class:modifie={m('employees_range')}>Tranche effectif<input bind:value={form.employees_range} placeholder="ex: 1-2" /></label>
      <label class:modifie={m('biz_creation')}>Date création<input bind:value={form.biz_creation} placeholder="AAAA-MM-JJ" /></label>
      <label class:modifie={m('closing_date')}>Date fermeture<input bind:value={form.closing_date} placeholder="AAAA-MM-JJ" /></label>
    </div>
  </section>

{:else if form.type === 'association'}
  <section class="card">
    <h2>Association</h2>
    <div class="grid2">
      <label class:modifie={m('rna_id')}>N° RNA<input bind:value={form.rna_id} placeholder="W30..." /></label>
      <label class:modifie={m('asso_status')}>
        Statut
        <select bind:value={form.asso_status}>
          <option value="">—</option>
          <option value="A">Active</option>
          <option value="D">Dissoute</option>
        </select>
      </label>
      <label class="col2" class:modifie={m('asso_object')}>
        Objet social
        <textarea bind:value={form.asso_object} rows="3"></textarea>
      </label>
      <label class:modifie={m('asso_creation')}>Date création<input bind:value={form.asso_creation} placeholder="AAAA-MM-JJ" /></label>
      <label class:modifie={m('dissolution_date')}>Date dissolution<input bind:value={form.dissolution_date} placeholder="AAAA-MM-JJ" /></label>
    </div>
  </section>

{:else if form.type === 'place'}
  <section class="card">
    <h2>Lieu</h2>
    <div class="grid2">
      <label class:modifie={m('osm_category')}>Catégorie OSM<input bind:value={form.osm_category} placeholder="ex: amenity" /></label>
      <label class:modifie={m('osm_value')}>Valeur OSM<input bind:value={form.osm_value} placeholder="ex: restaurant" /></label>
    </div>
  </section>

{:else if form.type === 'service'}
  <section class="card">
    <h2>Service public</h2>
    <div class="grid2">
      <label class:modifie={m('svc_category')}>Catégorie<input bind:value={form.svc_category} placeholder="santé, éducation…" /></label>
      <label class:modifie={m('operator')}>Opérateur<input bind:value={form.operator} /></label>
      <label class="col2" class:modifie={m('opening_hours')}>Horaires<input bind:value={form.opening_hours} placeholder="Mo-Fr 09:00-17:00" /></label>
    </div>
  </section>
{/if}
