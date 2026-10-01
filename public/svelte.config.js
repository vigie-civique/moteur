import adapter from '@sveltejs/adapter-static'
import { existsSync } from 'node:fs'
import { join, normalize } from 'node:path'

// L'aperçu de l'atelier construit le site sur le BROUILLON (`VIGIE_DATA_DIR`),
// mais les fichiers servis sous `/data/` viennent de `static/data`, c'est-à-dire
// de ce qui est déjà en ligne. Un lien vers une donnée NOUVELLE du brouillon
// (une feuille « en clair » tout juste retenue) n'y est pas encore : le
// prérendu le voyait en 404 et refusait tout l'aperçu (01/10/2026). Il n'est
// toléré que si le fichier existe dans le brouillon — l'atelier le recopie dans
// l'aperçu après le build. Un build de production n'a pas `VIGIE_DATA_DIR` :
// rien n'y change, et tout lien mort y reste bloquant.
const BROUILLON = process.env.VIGIE_DATA_DIR

function dansLeBrouillon(path) {
  if (!BROUILLON || !path.startsWith('/data/')) return false
  const rel = normalize(decodeURIComponent(path.slice('/data/'.length)))
  return !rel.startsWith('..') && existsSync(join(BROUILLON, rel))
}

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    // adapter-static → Cloudflare Pages
    // `VIGIE_BUILD_DIR` sert à construire un aperçu figé sans écraser le build
    // de production ; non définie, rien ne change.
    adapter: adapter({
      pages:      process.env.VIGIE_BUILD_DIR || 'build',
      assets:     process.env.VIGIE_BUILD_DIR || 'build',
      fallback:   '404.html',
      precompress: false,
      strict:     false,
    }),
    // Les données sont dans ../public-data/ (généré par build_public_snapshot.py)
    // En prod : servies par Cloudflare depuis le même repo, sans backend.

    // Détection des nouvelles versions du site. Sans ce réglage, un onglet resté
    // ouvert garde le JavaScript de la version qu'il a chargée : à la
    // publication suivante, les fragments qu'il réclame sous
    // `/_app/immutable/` sont empreintés et n'existent plus chez l'hébergeur, la
    // navigation interne échoue en silence, et le lecteur croit le site cassé.
    // Le client interroge `_app/version.json` toutes les cinq minutes ; le
    // layout force un vrai chargement au clic suivant.
    version: { pollInterval: 300000 },

    prerender: {
      handleHttpError: ({ path, message }) => {
        if (dansLeBrouillon(path)) return
        throw new Error(message)
      },
    },
  }
}
