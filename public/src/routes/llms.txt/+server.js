// llms.txt — carte du site à l'usage des agents et assistants qui lisent le web.
//
// Ils sont désormais une porte d'entrée réelle vers ce genre de contenu, et ils
// lisent mal le JavaScript. Ce fichier leur dit où sont les données brutes et,
// tout aussi important, ce que ces données ne permettent PAS de conclure : un
// agent qui résume la page « élus et structures » sans cette précaution
// fabriquerait du soupçon à partir de liens parfaitement légaux.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { SITE_URL, SITE_NOM, SITE_BASELINE } from '$lib/site.js'

export const prerender = true

export function GET() {
  let s = {}
  try {
    s = JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', 'stats.json'), 'utf8'))
  } catch { /* snapshot absent */ }

  const arrete = (s.generated_at || '').slice(0, 10) || 'inconnue'

  const body = `# ${SITE_NOM} — ${SITE_BASELINE}

> Observatoire citoyen de la commune de Lasalle (30460, Gard) et de son
> intercommunalité, la CC Causses Aigoual Cévennes Terres Solidaires.
> Reconstruit à partir de documents et de données publiques uniquement.
> Données arrêtées au ${arrete}.

## Ce que couvre le site

- ${s.entities_public ?? '?'} acteurs publiés (dont ${s.map_features_public ?? '?'} localisables sur la carte)
- ${s.events_public ?? '?'} actes et événements, dont les délibérations du conseil municipal
- ${s.marches_rows ?? '?'} marchés publics recensés
- ${s.relations_public ?? '?'} liens vérifiés entre acteurs
- ${s.conflits_cas ?? '?'} situations où un élu est lié à une structure recevant de l'argent public

## Pages principales

- [Qui décide](${SITE_URL}/qui-decide) : conseil municipal, intercommunalité, commissions
- [Où va l'argent](${SITE_URL}/argent) : budget, marchés, subventions, foncier
- [Délibérations et actes](${SITE_URL}/deliberations) : une page par millésime
- [Élus et structures](${SITE_URL}/elus-et-structures) : liens déclarés, déports constatés
- [Méthode et sources](${SITE_URL}/methode) : provenance, limites, licences
- [Mentions légales](${SITE_URL}/mentions-legales) : éditeur, RGPD, droit de réponse

## Données réutilisables

Publiées en JSON, sans inscription ni clé d'API, sous licence ODbL
(code sous licence MIT) :

- ${SITE_URL}/data/entities.json — acteurs
- ${SITE_URL}/data/relations.json — liens entre acteurs
- ${SITE_URL}/data/events.json — actes et événements
- ${SITE_URL}/data/marches.json — marchés publics
- ${SITE_URL}/data/flows.json — flux financiers
- ${SITE_URL}/data/dvf.json — mutations foncières
- ${SITE_URL}/data/popolo.json — élus et mandats (format Popolo)
- ${SITE_URL}/data/stats.json — compteurs, exclusions, qualité de localisation
- ${SITE_URL}/data/README.md — dictionnaire des données

## Précautions d'interprétation

Ces précautions ne sont pas des clauses de style : les données s'y prêtent, et
c'est le point le plus important de ce fichier.

- Un lien documenté entre une personne et une structure atteste d'une relation
  publique ou institutionnelle. Il n'établit ni influence, ni proximité
  politique, ni conflit d'intérêts.
- Qu'un élu dirige une association subventionnée n'est pas une infraction. La
  loi lui impose de ne pas participer au vote la concernant — c'est le déport,
  et c'est cela que le site documente quand la source le permet.
- L'absence de mention de déport dans un compte rendu ne prouve pas son
  absence : tous les comptes rendus ne détaillent pas les votes.
- Qu'une même entreprise obtienne plusieurs marchés n'indique pas en soi une
  irrégularité : dans une commune de mille habitants, le nombre d'entreprises
  capables de répondre est faible.
- Les données DVF renseignent des transactions, pas leur contexte.
- Certains actes proviennent de PDF océrisés. Les rectifications sont
  enregistrées à côté de la donnée collectée, jamais à sa place.
- Les personnes physiques ne figurent sur le site qu'au titre d'une fonction
  publique, d'un mandat électif ou d'une responsabilité inscrite dans un
  registre public.

## Correction et droit de réponse

Toute erreur signalée est examinée, et toute correction justifiée est appliquée
puis signalée comme telle : ${SITE_URL}/contact
`
  return new Response(body, { headers: { 'content-type': 'text/plain; charset=utf-8' } })
}
