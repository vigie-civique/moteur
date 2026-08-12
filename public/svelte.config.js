import adapter from '@sveltejs/adapter-static'

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    // adapter-static → Cloudflare Pages
    adapter: adapter({
      pages:      'build',
      assets:     'build',
      fallback:   '404.html',
      precompress: false,
      strict:     false,
    }),
    // Les données sont dans ../public-data/ (généré par build_public_snapshot.py)
    // En prod : servies par Cloudflare depuis le même repo, sans backend.
  }
}
