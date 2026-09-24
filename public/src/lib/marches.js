// Un marché ATTRIBUÉ a un titulaire et un montant ; tout le reste — avis de
// marché, de publicité, d'intention de conclure, résultat sans titulaire ou
// sans montant — est un AVIS PUBLIÉ, jamais un marché.
// Un seul prédicat pour tout le site : l'accueil annonçait « 58 marchés »
// quand /marches n'en comptait aucun d'attribué (audit du 24/09/2026).
export const estAttribue = (m) => Boolean(m.titulaire_nom && m.montant)
