<script>
  import { lienSur } from '$lib/liens.js'
  import { cleLocale } from './brouillon.js'

  export let contacts = []
  export let brouillon            // { ajouts, suppr }

  const CONTACT_TYPES = ['website','phone','email','other']
  let nouveau = { type: 'website', value: '', label: '' }

  function ajouter() {
    if (!nouveau.value.trim()) return
    brouillon.ajouts = [...brouillon.ajouts, { cle: cleLocale(), corps: { ...nouveau } }]
    nouveau = { type: 'website', value: '', label: '' }
  }
  const basculerSuppr = id => brouillon.suppr = brouillon.suppr.includes(id)
    ? brouillon.suppr.filter(x => x !== id) : [...brouillon.suppr, id]
  const retirer = cle => brouillon.ajouts = brouillon.ajouts.filter(a => a.cle !== cle)

  function contactIcon(type) {
    return { website: '🌐', phone: '📞', email: '✉️', other: '🔗' }[type] ?? '🔗'
  }
</script>

<section class="card">
  <h2>Contacts <span class="count-badge">{contacts.length}</span></h2>
  {#if contacts.length || brouillon.ajouts.length}
    <ul class="contact-list">
      {#each contacts as c (c.id)}
        <li class:a-supprimer={brouillon.suppr.includes(c.id)}>
          <span class="contact-icon">{contactIcon(c.type)}</span>
          <span class="contact-type">{c.type}</span>
          {#if c.type === 'website'}
            <a href={lienSur(c.value)} target="_blank" rel="noopener" class="contact-value">{c.value}</a>
          {:else}
            <span class="contact-value">{c.value}</span>
          {/if}
          {#if c.label}<span class="contact-label">{c.label}</span>{/if}
          {#if brouillon.suppr.includes(c.id)}
            <span class="tag-attente">supprimé à l'enregistrement</span>
            <button class="lien-annuler" on:click={() => basculerSuppr(c.id)}>rétablir</button>
          {:else}
            <button class="contact-del" title="Supprimer" on:click={() => basculerSuppr(c.id)}>✕</button>
          {/if}
        </li>
      {/each}
      {#each brouillon.ajouts as a (a.cle)}
        <li class="a-enregistrer">
          <span class="contact-icon">{contactIcon(a.corps.type)}</span>
          <span class="contact-type">{a.corps.type}</span>
          <span class="contact-value">{a.corps.value}</span>
          {#if a.corps.label}<span class="contact-label">{a.corps.label}</span>{/if}
          <span class="tag-attente">à enregistrer</span>
          <button class="lien-annuler" on:click={() => retirer(a.cle)}>retirer</button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">Aucun contact renseigné.</p>
  {/if}

  <div class="add-contact">
    <select bind:value={nouveau.type}>
      {#each CONTACT_TYPES as t}<option value={t}>{t}</option>{/each}
    </select>
    <input bind:value={nouveau.value} placeholder="Valeur (URL, numéro, email…)" />
    <input bind:value={nouveau.label} placeholder="Étiquette (optionnel)" class="label-input" />
    <button class="btn-add-small" on:click={ajouter} disabled={!nouveau.value.trim()}>
      + Ajouter à la fiche
    </button>
  </div>
</section>

<style>
  .contact-list { list-style: none; display: flex; flex-direction: column; gap: .3rem; margin-bottom: .75rem; }
  .contact-list li {
    display: flex; align-items: center; gap: .45rem;
    background: var(--fond); border: 1px solid var(--bordure); border-radius: 5px;
    padding: .38rem .6rem; font-size: .8rem;
  }
  .contact-icon { font-size: .9rem; }
  .contact-type { color: var(--texte-doux); font-size: .72rem; min-width: 52px; }
  .contact-value { flex: 1; color: var(--info); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .contact-value:is(a):hover { text-decoration: underline; }
  .contact-label { color: var(--texte-doux); font-size: .72rem; }
  .contact-del { margin-left: auto; color: var(--danger); font-size: .78rem; cursor: pointer; padding: 0 .2rem; }
  .contact-del:hover { color: var(--danger-texte); }

  .add-contact { display: flex; gap: .4rem; flex-wrap: wrap; }
  .add-contact select { width: 100px; }
  .add-contact input  { flex: 1; min-width: 120px; }
  .add-contact .label-input { max-width: 130px; }
</style>
