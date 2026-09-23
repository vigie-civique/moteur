// Les trois axes d'une donnée, tels qu'on les lit à l'écran.
// Côté serveur : collectors/verdict.py et collectors/origine.py.
//
// Jusqu'au 21/09/2026 un seul mot en portait deux : « verified » voulait dire
// « écrit par un script », et le statut qu'on posait sur une fiche n'était lu
// par aucune étape de publication. Trois questions, trois mots :
//   origine    — comment le fait est entré
//   fiabilité  — ce que la MACHINE en sait
//   verdict    — ce qu'un HUMAIN en a dit, et ce que le site en fera

export const VERDICTS = [
  { cle: 'jamais_relu', libelle: 'Jamais relu', geste: 'Remettre à relire',
    effet: "Publié si les règles l'admettent. Personne ne l'a encore regardé." },
  { cle: 'a_revoir', libelle: 'À revoir', geste: 'À revoir',
    effet: "Reste publié. Quelqu'un doit y revenir." },
  { cle: 'retenu', libelle: 'Retenu', geste: 'Retenir',
    effet: "Publié, et signé : vous l'avez regardé et vous l'assumez." },
  { cle: 'ecarte', libelle: 'Écarté', geste: 'Écarter',
    effet: 'Retiré du site à la prochaine publication.' },
]
export const VERDICT = Object.fromEntries(VERDICTS.map(v => [v.cle, v]))

export const FIABILITE = {
  verified: 'Sûre', confirmed: 'Confirmée', probable: 'Probable', hypothesis: 'Hypothèse',
}
export const FIABILITE_AIDE = {
  verified: 'Source officielle, écrite par un collecteur — pas encore relue par un humain',
  confirmed: 'Recoupée ou saisie avec sa source',
  probable: 'Déduite par croisement : ne sort pas sur le site',
  hypothesis: 'Supposée — à vérifier : ne sort pas sur le site',
}

export const ORIGINES = {
  institutionnel: 'Registre officiel',
  verbatim: 'Lue dans un document',
  atelier: 'Saisie à la main',
}
export const ORIGINE_AIDE = {
  institutionnel: "Une administration l'a structurée (SIRENE, RNA, RNE…). L'atelier peut l'écarter, pas la réécrire.",
  verbatim: 'Nous l\'avons lue dans un procès-verbal ou une page : notre lecture peut se tromper.',
  atelier: 'Écrite à la main par un membre de l\'atelier, source à l\'appui.',
}
