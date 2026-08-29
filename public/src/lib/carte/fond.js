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

/** Source PMTiles qui télécharge le fichier une fois et sert les plages depuis
 *  la mémoire — l'interface attendue par la bibliothèque. */
class FichierEntier {
  constructor(url) { this.url = url; this.tampon = null }
  getKey() { return this.url }
  async getBytes(offset, length) {
    if (!this.tampon) {
      const r = await fetch(this.url)
      if (!r.ok) throw new Error(`${r.status} sur ${this.url}`)
      this.tampon = await r.arrayBuffer()
    }
    return { data: this.tampon.slice(offset, offset + length) }
  }
}

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
    // Le fichier est chargé ENTIER, une fois, plutôt que lu par plages.
    //
    // Un PMTiles se lit normalement par requêtes Range. Or Cloudflare Pages les
    // IGNORE : il répond 200 avec les 3,3 Mo complets, sans `accept-ranges`, et
    // la bibliothèque refuse alors le fichier — carte sans fond, en production,
    // alors que le fichier était bien servi. `python -m http.server`, celui du
    // dossier hors-ligne, faisait la même chose ; on avait corrigé le serveur
    // embarqué sans vérifier l'hébergeur.
    //
    // Dépendre d'une capacité que l'hébergeur n'offre pas est un pari : à cette
    // taille — 3 Mo, mis en cache par le navigateur, une seule requête au lieu
    // de deux cent cinquante — le charger d'un bloc est plus simple et marche
    // partout. Le jour où un fond dépassera la dizaine de mégaoctets, il faudra
    // un hébergement qui gère Range, et le dire ici.
    const source = new PMTiles(new FichierEntier(url))
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
