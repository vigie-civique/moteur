// Le fond de carte, servi avec le site — jamais chez un tiers.
//
// Les trois cartes du site chargeaient leurs tuiles ailleurs : CARTO pour la
// carte des acteurs, `tile.openstreetmap.org` pour l'urbanisme et les fiches
// d'entité. Trois conséquences, dont deux invisibles au développeur :
//
//   · l'adresse IP de chaque lecteur partait chez un tiers, alors que la page
//     Confidentialité promet qu'aucun traceur ne le suit ;
//   · un dossier hors-ligne n'avait aucun fond : des repères sur du vide ;
//   · la politique d'usage des tuiles d'openstreetmap.org exclut l'usage
//     systématique qu'en fait un site prérendu de plusieurs milliers de fiches.
//
// `static/carte/fond.pmtiles` est un extrait du fond Protomaps (OpenStreetMap,
// ODbL) borné à l'emprise de l'instance — 2,2 Mo pour une commune au zoom 15.
// Il est produit par `scripts/carte_fond.py`, lu par plages d'octets, et il
// vient du même domaine que le reste du site.
// Chemin relatif : dans un dossier hors-ligne, `/carte/fond.pmtiles` désignerait
// la racine du disque. `base` vaut '' sur le site servi et le préfixe qui
// convient dans une archive.
import { base } from '$app/paths'

const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'

/**
 * Pose le fond de carte sur une carte Leaflet.
 *
 * @param {object} L      Leaflet, déjà importé par l'appelant.
 * @param {object} carte  l'instance de carte.
 * @returns {Promise<{ok: boolean, raison?: string}>} — jamais de rejet : une
 *   carte sans fond reste utile (les repères, eux, sont là), une page qui casse
 *   ne l'est pas.
 */
export async function poserFond(L, carte) {
  try {
    const [{ PMTiles }, protomaps] = await Promise.all([
      import('pmtiles'),
      import('protomaps-leaflet'),
    ])
    const url = `${base}/carte/fond.pmtiles`
    const source = new PMTiles(url)
    // Lecture de l'en-tête AVANT de monter la couche : c'est le seul moyen de
    // distinguer « fichier absent » de « fichier présent mais illisible », et
    // de le dire à l'appelant plutôt que de laisser une carte grise sans
    // explication.
    const entete = await source.getHeader()
    const couche = protomaps.leafletLayer({
      url: source,
      maxDataZoom: entete.maxZoom,
      // Sans `flavor`, les règles de peinture sont VIDES : la couche se monte,
      // les canvas se créent, et rien ne s'y dessine. Une carte blanche sous
      // des repères, sans la moindre erreur.
      flavor: 'light',
      attribution: ATTRIBUTION,
    })
    couche.addTo(carte)
    return { ok: true }
  } catch (e) {
    return { ok: false, raison: e?.message || String(e) }
  }
}
