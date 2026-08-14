// Fichier GÉNÉRÉ par scripts/generer_libelles.py — ne pas éditer.
//
// Identité de l'instance : tout ce que le site doit dire de la commune
// sans que le code le sache. Les formes grammaticales sont calculées :
// un nom commençant par une voyelle élide le « de », un nom précédé
// d'un article le contracte (« du », « des », « au », « aux »). Une
// chaîne « de {COMMUNE} » écrite à la main finit toujours par produire
// une faute d'accord sur la commune suivante.
//
// Régénérer :  python3 scripts/generer_libelles.py

export const COMMUNE = 'Brassac'
export const COMMUNE_DE = 'de Brassac'
export const COMMUNE_A = 'à Brassac'
export const GENTILE = ''
export const INSEE = '81037'
export const CODE_POSTAL = '81260'
export const DEPARTEMENT = '81'
export const DEPARTEMENT_NOM = ''
export const EPCI = 'CC Sidobre Vals et Plateaux'
export const EPCI_COURT = 'CCSVP'
export const EPCI_NB_COMMUNES = 16
export const EPCI_NB_AUTRES = 15
export const SITE_NOM = 'Vigie Civique Brassac'
export const SITE_URL = 'https://vigie-civique-brassac.pages.dev'
export const SITE_BASELINE = 'Brassac, au clair'
export const CONTACT_EMAIL = ''
export const EDITEUR_NOM = ''
export const EDITEUR_STATUT = ''
export const HEBERGEUR = ''
export const PREFECTURE = 'Préfecture du Tarn'

// Raccourci : « la commune de X » avec l'élision correcte.
export const LA_COMMUNE = `la commune ${COMMUNE_DE}`

// L'intercommunalité, nommée puis reprise en sigle.
export const L_EPCI = EPCI || "l'intercommunalité"
