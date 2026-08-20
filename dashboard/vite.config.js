import { sveltekit } from '@sveltejs/kit/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // `127.0.0.1` et non `localhost` : sur macOS, `localhost` résout
        // d'abord en IPv6 (`::1`), alors qu'`uvicorn` n'écoute par défaut qu'en
        // IPv4. Le proxy visait donc une adresse où rien n'écoutait, et
        // l'atelier affichait « Serveur inaccessible » avec les deux services
        // pourtant démarrés et une API qui répondait très bien — le diagnostic
        // le plus coûteux qui soit, puisque tout a l'air en ordre.
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      }
    }
  }
})
