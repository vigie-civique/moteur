<script>
  import Icon from '$lib/components/Icon.svelte'
  import { euros } from '$lib/data.js'
  import Niveau from '$lib/components/Niveau.svelte'

  // Ces croisements étaient calculés en base depuis des mois (v_conflits_potentiels)
  // sans être exposés nulle part. Publication arbitrée le 26/07/2026.
  //
  // Parti pris éditorial : un lien n'est pas une faute. La loi n'interdit pas à
  // un élu de diriger une association subventionnée, elle lui impose de ne pas
  // participer au vote. La page est donc construite autour du DÉPORT, pas du
  // lien — et les déports constatés sont mis en avant, pas relégués.
  // Rendu au build par +page.server.js. La prop SvelteKit s'appelle `data` ;
  // le jeu de données est donc exposé sous `conflits` pour éviter la collision.
  export let data
  $: conflits = data.conflits

  const STATUTS = {
    deport_constate: {
      label: 'Déport constaté', ordre: 1, ton: 'ok',
      explication: "L'élu n'a pas participé au vote : c'est précisément ce que la loi demande. "
        + "Le compte rendu du conseil en porte la mention." },
    deport_non_trouve: {
      label: 'Déport non trouvé', ordre: 2, ton: 'attention',
      explication: "Aucune mention de retrait du vote n'a été trouvée dans les comptes rendus "
        + "exploités. Cela ne prouve pas qu'il n'y a pas eu de déport : tous les comptes rendus "
        + "ne sont pas encore dépouillés, et certains ne détaillent pas les votes." },
    chronologie_incertaine: {
      label: 'Date à vérifier', ordre: 3, ton: 'neutre',
      explication: "Le versement est antérieur aux mandats enregistrés dans notre base. "
        + "L'historique des mandatures précédentes est incomplet : nous ne pouvons pas dire "
        + "si la personne était élue à cette date." },
    hors_mandat: {
      label: 'Hors mandat', ordre: 4, ton: 'neutre',
      explication: "Le versement a eu lieu en dehors de la période de mandat : il n'y a pas "
        + "de situation à examiner." },
    lien_sans_versement: {
      label: 'Lien déclaré, aucun versement', ordre: 5, ton: 'neutre',
      explication: "La personne dirige cette structure, mais nous n'avons trouvé aucun "
        + "versement public à son bénéfice. Le lien est publié pour la transparence, "
        + "pas parce qu'il pose question." },
  }

  // Situations où le déport est constaté — à ne pas confondre avec le nombre
  // de délibérations mentionnant un déport (cf. le bloc de calcul plus bas).
  $: deportConstate = (conflits?.cas || []).filter((c) => c.statut === 'deport_constate').length

  $: groupes = conflits
    ? Object.entries(
        (conflits.cas || []).reduce((acc, c) => {
          (acc[c.statut] ||= []).push(c)
          return acc
        }, {})
      ).sort((a, b) => (STATUTS[a[0]]?.ordre ?? 99) - (STATUTS[b[0]]?.ordre ?? 99))
    : []

  const roles = (r) => (r || []).map(x => x.replace(/_/g, ' ')).join(', ')
</script>

<svelte:head>
  <title>Élus et structures subventionnées — Vigie Civique Lasalle</title>
  <meta name="description" content="Les élus de Lasalle qui dirigent une association ou une société, et ce que la commune verse à ces structures : situations à vérifier, déports constatés, méthode et droit de réponse." />
</svelte:head>

<section class="page">
  <!-- Droit de réponse en TÊTE de page, pas en pied : c'est la page où il compte. -->
  <aside class="reponse">
    <strong>Vous êtes concerné par une de ces situations ?</strong>
    Cette page peut contenir des erreurs ou des informations incomplètes.
    <a href="/contact">Demandez une rectification ou exercez votre droit de réponse</a> —
    toute correction justifiée est appliquée et signalée.
  </aside>

  <header>
    <h1 class="avec-icone"><Icon name="recherche" size={26} />Élus et structures subventionnées</h1>
    <p class="chapeau">
      Quand un élu dirige une association ou une société qui reçoit de l'argent
      public, la loi ne l'interdit pas : elle lui impose de <strong>ne pas
      participer au vote</strong>. Cette page recense ces situations et indique,
      quand l'information existe, si le retrait du vote a bien été consigné.
    </p>
    <p class="avertissement">
      <strong>Un lien n'est pas une faute.</strong> Dans une commune de mille
      habitants, les élus sont souvent les mêmes personnes que celles qui font
      vivre le tissu associatif. C'est normal, et c'est même souhaitable — ce qui
      compte est que la décision publique reste régulière.
    </p>
  </header>

  {#if !conflits?.cas?.length}<p class="etat">Aucune situation recensée.</p>
  {:else}
    <!-- Ces nombres ne figurent dans aucun document : ils résultent d'un
         croisement entre les mandats et les versements. Les présenter comme un
         relevé officiel serait leur prêter une autorité qu'ils n'ont pas —
         c'est exactement la page où cette nuance compte le plus.

         Attention aux dénominateurs, ils ne se rapportent pas au même objet :
         `total` et `deportConstate` comptent des SITUATIONS (une personne, une
         structure, un versement), tandis que `deports_repertories` compte des
         DÉLIBÉRATIONS portant une mention de retrait du vote. Écrire « 29
         situations dont 15 déports » serait faux, et faux dans le sens qui
         arrange. -->
    <Niveau type="calcul" base="les mandats en cours croisés avec les versements publics recensés">
      <b>{conflits.total}</b> situation{conflits.total > 1 ? 's' : ''} recensée{conflits.total > 1 ? 's' : ''},
      dont <b>{deportConstate}</b> où le retrait du vote de l'élu concerné est
      consigné au compte rendu.
      Par ailleurs, <b>{conflits.deports_repertories}</b> délibérations mentionnent
      un déport, toutes situations confondues — y compris des retraits sans
      rapport avec les liens listés ici.
    </Niveau>

    {#each groupes as [statut, cas]}
      {@const s = STATUTS[statut] || { label: statut, ton: 'neutre', explication: '' }}
      <section class="groupe {s.ton}">
        <h2>{s.label} <span class="compte">{cas.length}</span></h2>
        <p class="explication">{s.explication}</p>

        <ul class="cas">
          {#each cas as c}
            <li>
              <div class="entete">
                <a class="personne" href="/entite/{c.person_id}">{c.person_name}</a>
                <span class="role">{roles(c.roles_elu)}</span>
                <span class="fleche">→</span>
                <a class="structure" href="/entite/{c.entite_id}">{c.entite_nom}</a>
                <span class="role">{roles(c.roles_entite)}</span>
              </div>

              {#if c.flux_montant}
                <p class="montant">
                  {euros(c.flux_montant)}
                  {#if c.flux_annee}en {c.flux_annee}{/if}
                  {#if c.flux_type}<span class="type">({c.flux_type})</span>{/if}
                </p>
              {/if}

              {#if c.deport}
                <p class="deport">
                  ✓ <strong>« {c.deport.mention} »</strong>
                  — {c.deport.titre}{#if c.deport.date}, {c.deport.date}{/if}
                  {#if c.deport.source_url}
                    · <a href={c.deport.source_url} target="_blank" rel="noopener">compte rendu</a>
                  {/if}
                </p>
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {/each}

    <div class="note">
      <h3>Méthode</h3>
      <ul>
        <li><strong>Les liens</strong> proviennent des registres officiels
          (SIRENE pour les sociétés, journal officiel pour les associations) et
          des comptes rendus du conseil. Seuls les liens vérifiés sont publiés :
          les hypothèses et les liens présumés restent hors ligne.</li>
        <li><strong>Les versements</strong> sont les subventions et flux
          financiers de la commune effectivement réalisés — les demandes de
          subvention non obtenues sont exclues.</li>
        <li><strong>Les déports</strong> sont les mentions « ne participe pas »
          relevées dans les comptes rendus du conseil municipal.</li>
        <li><strong>Ce que nous ne publions pas :</strong> les adresses
          partagées et les liens familiaux présumés. Une adresse commune
          n'établit rien et relève de la vie privée.</li>
        <li><strong>Les entreprises individuelles sont écartées</strong> : « X
          dirige l'entreprise X » n'est pas une situation à examiner.</li>
      </ul>
      <p class="liens">
        <a href="/methode">Méthode générale et sources</a> ·
        <a href="/comprendre/mandats">Comprendre les mandats</a> ·
        <a href="/contact">Droit de réponse</a>
      </p>
    </div>
  {/if}
</section>

<style>
  .page { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
  h1 { font-size: 1.8rem; margin: 0 0 .5rem; color: var(--encre); }
  .chapeau { color: var(--gris); max-width: 64ch; line-height: 1.6; margin: 0 0 .8rem; }
  .avertissement { color: var(--gris); max-width: 64ch; line-height: 1.6; font-size: .9rem;
                   margin: 0 0 1rem; padding: .7rem .9rem; background: var(--papier);
                   border-radius: 8px; border: 1px solid var(--trait); }
  .source { font-size: .8rem; color: var(--gris-clair); margin: 0 0 1.75rem; }
  .etat { color: var(--gris); }
  .etat.err { color: var(--depense); }

  .reponse { font-size: .87rem; line-height: 1.55; color: #7c2d12; background: var(--ambre-pale);
             border: 1px solid #fcd34d; border-radius: 10px; padding: .8rem 1rem;
             margin-bottom: 1.5rem; }
  .reponse strong { display: block; margin-bottom: .2rem; color: var(--ambre); }

  .groupe { margin-bottom: 2rem; padding: 1rem 1.1rem; background: #fff;
            border: 1px solid var(--trait); border-radius: 12px; border-left: 3px solid var(--trait); }
  .groupe.ok { border-left-color: var(--recette); }
  .groupe.attention { border-left-color: var(--ambre); }
  .groupe h2 { font-size: 1.05rem; margin: 0 0 .35rem; color: var(--encre);
               display: flex; align-items: baseline; gap: .5rem; }
  .compte { font-size: .75rem; color: var(--gris); background: var(--trait-pale);
            padding: .1rem .45rem; border-radius: 999px; font-weight: 400; }
  .explication { font-size: .85rem; color: var(--gris); line-height: 1.55; margin: 0 0 .9rem; }

  .cas { list-style: none; margin: 0; padding: 0; display: grid; gap: .8rem; }
  .cas li { padding: .7rem .8rem; background: var(--papier); border-radius: 9px; }
  .entete { display: flex; flex-wrap: wrap; align-items: baseline; gap: .35rem .5rem; }
  .personne { font-weight: 600; color: var(--encre); }
  .structure { font-weight: 600; color: var(--ardoise-fonce); }
  .role { font-size: .74rem; color: var(--gris-clair); }
  .fleche { color: var(--trait); }
  .montant { font-size: .85rem; color: var(--gris); margin: .35rem 0 0;
             font-variant-numeric: tabular-nums; }
  .montant .type { color: var(--gris-clair); font-size: .78rem; }
  .deport { font-size: .82rem; color: #065f46; margin: .4rem 0 0; line-height: 1.5;
            padding: .35rem .5rem; background: #e7f0ea; border-radius: 6px; }

  .note { margin-top: 2rem; padding: 1.1rem 1.25rem; background: var(--papier);
          border: 1px solid var(--trait); border-left: 3px solid var(--ardoise); border-radius: 10px; }
  .note h3 { margin: 0 0 .6rem; font-size: 1rem; color: var(--encre); }
  .note ul { margin: 0 0 .7rem; padding-left: 1.1rem; }
  .note li { font-size: .86rem; line-height: 1.6; color: var(--gris); margin-bottom: .4rem; }
  .liens { font-size: .85rem; margin: 0; }
  h1.avec-icone { display: flex; align-items: center; gap: .6rem; }
  h1.avec-icone :global(.icon) { color: var(--ardoise); }
</style>
