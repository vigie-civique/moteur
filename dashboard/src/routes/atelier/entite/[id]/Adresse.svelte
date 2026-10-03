<script>
  export let form
  export let modifies = []
</script>

<section class="card">
  <h2>Adresse</h2>
  <label class:modifie={modifies.includes('address')}>
    Adresse postale
    <input bind:value={form.address} />
  </label>
</section>
