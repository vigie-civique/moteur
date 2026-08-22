import adapter from '@sveltejs/adapter-static'

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
  }
}
