// Libellés des trois axes de provenance produits par build_public_snapshot.py.
//
// Le vocabulaire compte autant que le calcul : « registre » doit dire au
// lecteur qu'un tiers officiel atteste d'une DÉCLARATION, pas du fait déclaré.
// Une annonce BODACC n'est pas moins fiable qu'une délibération — elle prouve
// autre chose.

export const PROVENANCE = {
  primaire: {
    court: 'Source primaire',
    long: "Publié par l'autorité qui a pris la décision.",
  },
  registre: {
    court: 'Registre national',
    long: "Enregistré par un tiers officiel. Le registre atteste fidèlement de la déclaration qui lui a été faite, pas du fait déclaré.",
  },
  secondaire: {
    court: 'Source secondaire',
    long: "Rapporté par un tiers, sans valeur officielle. Les sources que nous n'avons pas classées tombent ici : le doute joue contre nous.",
  },
}

export const DOCUMENT = {
  acte: {
    court: 'Acte consultable',
    long: "Le document de l'acte lui-même est accessible.",
  },
  page_source: {
    court: 'Page source',
    long: "Le lien mène à la page qui contient l'acte — souvent le compte rendu entier, pas la délibération isolée. Il faut y chercher le passage.",
  },
  aucun: {
    court: 'Sans document',
    long: "Aucun document n'est accessible en ligne pour cet acte.",
  },
}

export const TRAITEMENT = {
  structure: {
    court: 'Donnée structurée',
    long: "Reprise telle quelle d'un flux structuré. Aucune étape d'interprétation entre la source et l'affichage.",
  },
  extraction: {
    court: 'Extrait d’un document',
    long: "Lu dans un document rédigé (PDF, compte rendu) par reconnaissance de caractères ou par modèle de langage. C'est ici que naissent les erreurs de lecture — un numéro d'article pris pour un montant, des chiffres accolés.",
  },
  rectifie: {
    court: 'Rectifié',
    long: "Une erreur a été constatée sur le document d'origine et corrigée. La donnée collectée est conservée à côté de la rectification, jamais remplacée.",
  },
}

/** Les trois axes d'un acte, prêts à afficher. Ignore les axes absents. */
export function axesDe(acte) {
  return [
    PROVENANCE[acte?.provenance] && { axe: 'provenance', cle: acte.provenance, ...PROVENANCE[acte.provenance] },
    DOCUMENT[acte?.document] && { axe: 'document', cle: acte.document, ...DOCUMENT[acte.document] },
    TRAITEMENT[acte?.traitement] && { axe: 'traitement', cle: acte.traitement, ...TRAITEMENT[acte.traitement] },
  ].filter(Boolean)
}
