<script>
  // Qui a fait quoi, toutes fiches confondues.
  import { onMount } from 'svelte'
  import { authFetch } from '$lib/stores/auth.js'
  import { COMMUNE } from '$lib/instance.js'
  import { heureLocale } from '$lib/heure.js'
  import { LIBELLE_ROLE, messageErreur } from '$lib/roles.js'
  import { LIBELLES } from '$lib/champs.js'

  const PAGE = 100
  let lignes = []
  let total = 0
  let auteurs = []
  let tables = {}
  let qui = ''
  let quoi = ''
  let erreur = ''
  let chargement = false

  const ACTIONS = {
    update: 'modification', annotate: 'revue', create: 'création', delete: 'suppression',
    retrait: 'retrait', reservation: 'réservation', liberation: 'libération',
    invitation: 'invitation', invitation_annulee: 'invitation annulée', inscription: 'inscription',
    role: 'changement de rôle', desactivation: 'désactivation', reactivation: 'réactivation',
    mot_de_passe: 'mot de passe changé', lien_mot_de_passe: 'lien de mot de passe',
    apercu: 'aperçu', publication: 'publication', 'mise-en-ligne': 'mise en ligne',
    'verification-en-ligne': 'vérification en ligne',
    proposer: 'proposition', acceptee: 'proposition acceptée', refusee: 'proposition refusée',
    retiree: 'proposition retirée', ia: "branchement de l'IA",
  }

  onMount(() => charger(true))

  async function charger(depuisLeDebut) {
    chargement = true; erreur = ''
    const qs = new URLSearchParams({ limit: PAGE, offset: depuisLeDebut ? 0 : lignes.length })
    if (qui) qs.set('qui', qui)
    if (quoi) qs.set('quoi', quoi)
    try {
      const r = await authFetch(`/atelier/journal?${qs}`)
      const d = await r.json()
      if (!r.ok) { erreur = messageErreur(d.detail); return }
      lignes = depuisLeDebut ? d.lignes : [...lignes, ...d.lignes]
      total = d.total; auteurs = d.auteurs; tables = d.tables
    } finally {
      chargement = false
    }
  }

  // Les valeurs de rôle et de statut sont des codes : les dire en français.
  function valeur(v) {
    if (v == null || v === '') return '—'
    return LIBELLE_ROLE[v] ?? v
  }
  // Une publication ou une revue garde un détail en JSON : utile à relire, pas à
  // afficher en ligne.
  const estDetail = (v) => typeof v === 'string' && v.trimStart().startsWith('{')
</script>

<svelte:head><title>Journal — Atelier {COMMUNE}</title></svelte:head>

<div class="page">
  <h1>Journal des modifications</h1>
  <p class="intro">Tout ce qui a été écrit depuis l'atelier : par qui, quand, et ce que la valeur était avant.</p>

  <div class="filtres">
    <label>Par
      <select bind:value={qui} on:change={() => charger(true)}>
        <option value="">tout le monde</option>
        {#each auteurs as a}<option value={a}>{a}</option>{/each}
      </select>
    </label>
    <label>Sur
      <select bind:value={quoi} on:change={() => charger(true)}>
        <option value="">tout</option>
        {#each Object.entries(tables) as [cle, libelle]}<option value={cle}>{libelle}</option>{/each}
      </select>
    </label>
    <span class="muted">{total.toLocaleString('fr-FR')} écriture{total > 1 ? 's' : ''}</span>
  </div>

  {#if erreur}<p class="avis">{erreur}</p>{/if}

  <div class="table">
    <table>
      <thead><tr><th>Quand</th><th>Qui</th><th>Quoi</th><th>Sur</th><th>Avant</th><th>Après</th></tr></thead>
      <tbody>
        {#each lignes as l (l.id)}
          <tr>
            <td class="date">{heureLocale(l.at)}</td>
            <td>{l.par ?? '—'}</td>
            <td>{ACTIONS[l.action] ?? l.action} <span class="muted">· {l.quoi_libelle}</span></td>
            <td>
              {#if l.entity_id}<a href="/atelier/entite/{l.entity_id}">{l.fiche ?? `fiche ${l.entity_id}`}</a>{#if l.champ}&nbsp;<span class="muted">· {LIBELLES[l.champ] ?? l.champ}</span>{/if}
              {:else}{l.champ ?? '—'}{/if}
            </td>
            {#each [[l.avant, 'valeur avant'], [l.apres, 'valeur']] as [v, classe]}
              <td class={classe}>
                {#if estDetail(v)}<details><summary>détail</summary><code>{v}</code></details>
                {:else}{valeur(v)}{/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !lignes.length && !chargement}<p class="muted vide">Aucune écriture.</p>{/if}
  </div>

  {#if lignes.length < total}
    <button class="plus" on:click={() => charger(false)} disabled={chargement}>
      {chargement ? 'Chargement…' : `Afficher les suivantes (${total - lignes.length} restantes)`}
    </button>
  {/if}
</div>

<style>
  .page { padding: 1.2rem; display: flex; flex-direction: column; gap: .8rem; font-size: .85rem; }
  h1 { font-size: 1.2rem; color: var(--texte); }
  .intro { color: var(--texte-2); }
  .filtres { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .filtres label { display: flex; gap: .4rem; align-items: center; color: var(--texte-2); }
  select { background: var(--fond); border: 1px solid var(--bordure); color: var(--texte); border-radius: 5px; padding: .3rem .45rem; }
  .table { overflow-x: auto; background: var(--surface); border: 1px solid var(--bordure); border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--texte-doux); font-weight: 500; font-size: .78rem; padding: .45rem .55rem; border-bottom: 1px solid var(--bordure); }
  td { padding: .45rem .55rem; border-bottom: 1px solid var(--bordure-douce); color: var(--texte); vertical-align: top; }
  .date { white-space: nowrap; }
  .valeur { max-width: 28ch; overflow-wrap: anywhere; }
  .avant { color: var(--danger-texte); }
  details code { display: block; white-space: pre-wrap; font-size: .72rem; color: var(--texte-doux); margin-top: .3rem; }
  summary { cursor: pointer; color: var(--texte-doux); }
  .muted { color: var(--texte-doux); }
  .vide { padding: 1rem; }
  .avis { background: var(--alerte-doux); border: 1px solid var(--alerte-bordure); border-radius: 6px; color: var(--alerte-texte); padding: .5rem .75rem; }
  .plus { align-self: flex-start; border: 1px solid var(--bordure-forte); border-radius: 6px; padding: .45rem .8rem; color: var(--texte-2); }
</style>
