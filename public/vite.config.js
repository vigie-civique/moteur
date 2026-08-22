import { sveltekit } from '@sveltejs/kit/vite'
import { defineConfig } from 'vite'
import { createReadStream, cpSync, existsSync, statSync } from 'node:fs'
import { join, normalize, resolve, sep } from 'node:path'

/**
 * L'aperçu de l'atelier fait tourner CE site sur un snapshot brouillon.
 *
 * Les pages prérendues lisent déjà `VIGIE_DATA_DIR` (cf. `src/lib/donnees.server.js`),
 * mais une partie des données part en `fetch('/data/…')` depuis le navigateur, et
 * celles-là sortiraient de `static/data` — le snapshot PUBLIÉ. Sans ce raccord,
 * l'aperçu mélangerait deux snapshots sans le dire, ce qui est pire que pas
 * d'aperçu du tout : on croirait avoir vérifié.
 *
 * Variable absente — tout build de production, toute la CI — le plugin ne fait
 * rien et le site lit `static/` comme avant.
 */
function donneesBrouillon() {
  const declare = process.env.VIGIE_DATA_DIR
  const racine = declare ? resolve(declare) : null

  return {
    name: 'vigie-donnees-brouillon',

    // Aperçu vivant : `vite dev` sert /data/ depuis le brouillon.
    configureServer(server) {
      if (!racine) return
      server.middlewares.use('/data', (req, res, next) => {
        const demande = decodeURIComponent((req.url || '/').split('?')[0])
        const cible = resolve(join(racine, normalize(demande)))
        // Vérifié SOUS la racine : `/data/../../.env` ne sort pas du snapshot.
        if (cible !== racine && !cible.startsWith(racine + sep)) {
          res.statusCode = 403
          return res.end('hors du snapshot')
        }
        if (!existsSync(cible) || !statSync(cible).isFile()) return next()
        res.setHeader('Content-Type',
          cible.endsWith('.geojson') || cible.endsWith('.json')
            ? 'application/json; charset=utf-8'
            : 'application/octet-stream')
        createReadStream(cible).pipe(res)
      })
    },

    // Aperçu figé : un `npm run build` avec la variable produit un site dont les
    // pages ET les fichiers `/data/` viennent du brouillon. Sans ça, le build
    // embarquerait `static/data`, c'est-à-dire le snapshot publié.
    closeBundle() {
      if (!racine || !existsSync(racine)) return
      const sortie = join(process.cwd(), process.env.VIGIE_BUILD_DIR || 'build', 'data')
      cpSync(racine, sortie, { recursive: true, force: true })
    },
  }
}

export default defineConfig({
  plugins: [sveltekit(), donneesBrouillon()],
})
