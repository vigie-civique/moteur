import adapter from '@sveltejs/adapter-static'

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    adapter: adapter({
      pages: 'dist',
      assets: 'dist',
      fallback: 'index.html',
      precompress: false,
      strict: false
    }),
    paths: {
      base: ''
    },
    // Le build SIGNE son bloc d'amorçage (une empreinte dans une balise
    // <meta> de la page) : c'est ce qui permet d'interdire tout autre script
    // écrit dans la page, sans `'unsafe-inline'`. Une balise injectée dans une
    // donnée affichée ne s'exécute plus, même si un échappement est oublié.
    // Le reste de la politique (cadres, images, connexions) est posé par le
    // serveur — cf. deploy/nginx-atelier.conf — qui laisse `script-src` ici.
    csp: {
      mode: 'hash',
      directives: { 'script-src': ['self'] }
    }
  }
}
