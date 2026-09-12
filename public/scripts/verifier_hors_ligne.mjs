#!/usr/bin/env node
// Garde-fou du dossier remis : l'éprouver comme un LECTEUR l'ouvre.
//
// Le 11/09/2026, un dossier national livrait encore deux défauts que toute la
// chaîne déclarait verts : les liens de la barre de navigation tombaient sur
// une liste de fichiers, et le sélecteur d'exercice du budget ne répondait pas.
// Ni `verifier_build.mjs` ni `validate_offline_export` ne pouvaient les voir :
// le premier lit le HTML comme du TEXTE, le second ne balaie que les `.html`.
// Or les deux défauts naissent de ce que le navigateur FAIT — il repose les
// adresses en absolu au chargement, et il hydrate ou il meurt.
//
// « Vérifier une page interactive, c'est lire sa console, pas son HTML » était
// écrit dans les leçons depuis le 29/08 ; le contrôle écrit ensuite était un
// lecteur de texte. Celui-ci ouvre un navigateur.
//
// Il éprouve les DEUX conditions de lecture qui existent réellement :
//
//   1. servi par un serveur statique QUELCONQUE, qui ne devine rien — c'est
//      `python -m http.server`, nginx, l'extension d'un éditeur. Le serveur
//      embarqué dans l'archive, lui, rattrapait les adresses absolues à la
//      volée : l'éprouver LUI aurait déclaré sain un dossier qui ne l'est que
//      chez lui.
//   2. ouvert en `file://` par un double-clic. Aucun module ES ne s'y charge —
//      c'est une contrainte du navigateur, pas un défaut à corriger — mais les
//      pages doivent s'afficher et leurs liens désigner des fichiers qui
//      existent.
//
// Usage : node scripts/verifier_hors_ligne.mjs <répertoire du dossier>
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { createReadStream, existsSync, mkdtempSync, rmSync, statSync } from 'node:fs'
import { join, extname, resolve, sep } from 'node:path'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'

const BUILD = resolve(process.argv[2] || process.env.VIGIE_BUILD_DIR || 'build')

// Les pages éprouvées. Pas toutes : ce contrôle ouvre un navigateur, il coûte
// des secondes. Celles-ci couvrent les quatre façons dont une adresse est
// fabriquée — le gabarit statique, la barre de navigation (tableau JS), une
// fiche nommée par un identifiant, et un millésime.
const PAGES = ['/', '/budgets', '/acteurs-publics', '/comprendre/budget']

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/plain; charset=utf-8', '.xml': 'application/xml; charset=utf-8',
  '.pmtiles': 'application/octet-stream', '.woff2': 'font/woff2',
}

/**
 * Le plus bête des serveurs statiques, et c'est exprès.
 *
 * Il sert un fichier s'il existe, redirige un répertoire vers lui-même suivi
 * d'une barre pour y servir `index.html`, et répond 404 pour tout le reste. Il
 * ne DEVINE aucune extension : c'est le comportement commun à `http.server`, à
 * nginx et aux serveurs d'éditeur. Un dossier qui tient ici tient partout.
 */
function serveurNu(racine) {
  return createServer((req, res) => {
    const chemin = decodeURIComponent((req.url || '/').split('?')[0])
    const cible = resolve(join(racine, chemin))
    if (cible !== racine && !cible.startsWith(racine + sep)) {
      res.statusCode = 403
      return res.end('hors du dossier')
    }
    if (existsSync(cible) && statSync(cible).isDirectory()) {
      if (!chemin.endsWith('/')) {
        res.statusCode = 301
        res.setHeader('Location', chemin + '/')
        return res.end()
      }
      const index = join(cible, 'index.html')
      if (!existsSync(index)) { res.statusCode = 404; return res.end('pas d\'index') }
      res.setHeader('Content-Type', MIME['.html'])
      return createReadStream(index).pipe(res)
    }
    if (!existsSync(cible) || !statSync(cible).isFile()) {
      res.statusCode = 404
      return res.end('absent')
    }
    res.setHeader('Content-Type', MIME[extname(cible)] || 'application/octet-stream')
    res.setHeader('Accept-Ranges', 'bytes')
    createReadStream(cible).pipe(res)
  })
}

const CHROMES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter(Boolean)

function trouverNavigateur() {
  const trouve = CHROMES.find((c) => existsSync(c))
  if (trouve) return trouve
  // Un contrôle qui se saute tout seul est pire qu'absent : il rend un « ✓ »
  // qui ne veut rien dire. On échoue, et on dit quoi installer.
  console.error('\n✖ Aucun navigateur Chrome/Chromium trouvé.')
  console.error('\nCe contrôle EXIGE un navigateur : les défauts qu\'il cherche')
  console.error('n\'existent que dans celui du lecteur. Posez CHROME_PATH, ou')
  console.error('installez chromium.\n')
  process.exit(1)
}

/** Un client CDP minimal — Node 22+ apporte `WebSocket` en natif. */
async function ouvrirNavigateur(url) {
  const profil = mkdtempSync(join(tmpdir(), 'vigie-hl-'))
  const port = 9330 + Math.floor(Math.random() * 400)
  const proc = spawn(trouverNavigateur(), [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--disable-dev-shm-usage', '--no-sandbox',
    `--user-data-dir=${profil}`, `--remote-debugging-port=${port}`, url,
  ], { stdio: 'ignore' })

  let cibles = null
  for (let essai = 0; essai < 60 && !cibles; essai++) {
    await new Promise((r) => setTimeout(r, 250))
    try {
      const liste = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      cibles = liste.find((t) => t.type === 'page') ? liste : null
    } catch { /* le navigateur n'écoute pas encore */ }
  }
  if (!cibles) { proc.kill(); throw new Error('le navigateur n\'a pas ouvert son port de pilotage') }

  const page = cibles.find((t) => t.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  const attentes = new Map()
  const erreurs = []
  let id = 0
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && attentes.has(m.id)) { attentes.get(m.id)(m.result); attentes.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      erreurs.push(m.params.exceptionDetails?.exception?.description
        || m.params.exceptionDetails?.text || 'exception sans description')
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      erreurs.push(m.params.args.map((a) => a.description || a.value).join(' '))
    }
  }
  await new Promise((r) => { ws.onopen = r })
  const envoyer = (method, params = {}) => new Promise((res) => {
    const i = ++id
    attentes.set(i, res)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
  await envoyer('Runtime.enable')
  await envoyer('Page.enable')

  return {
    erreurs,
    async aller(adresse) {
      erreurs.length = 0
      await envoyer('Page.navigate', { url: adresse })
      // Le chargement ne suffit pas : l'hydratation est asynchrone, et c'est
      // elle qu'on éprouve. SvelteKit retire son amorce en démarrant — c'est
      // ce retrait qu'on attend, pas `readyState`, qui est vrai bien avant.
      for (let essai = 0; essai < 40; essai++) {
        await new Promise((r) => setTimeout(r, 250))
        const pret = await this.evaluer('document.readyState === "complete" && '
          + '![...document.scripts].some(s => s.textContent.includes("__sveltekit"))')
        if (pret) break
      }
      await new Promise((r) => setTimeout(r, 400))
    },
    async evaluer(expression) {
      const r = await envoyer('Runtime.evaluate',
        { expression, returnByValue: true, awaitPromise: true })
      if (r?.exceptionDetails) {
        throw new Error(r.exceptionDetails.exception?.description || 'évaluation impossible')
      }
      return r?.result?.value
    },
    fermer() {
      try { ws.close() } catch { /* déjà fermé */ }
      proc.kill()
      // Le navigateur écrit encore dans son profil en mourant : un retrait
      // synchrone échoue en ENOTEMPTY et l'exception REMPLACE le verdict —
      // c'est un dossier réellement défaillant qui est sorti « ✖ ENOTEMPTY »
      // au lieu de ses treize liens morts. Le ménage ne décide de rien.
      try { rmSync(profil, { recursive: true, force: true, maxRetries: 3 }) }
      catch { /* profil jetable dans /tmp */ }
    },
  }
}

const problemes = []
// Ce qui n'a PAS été éprouvé. Le verdict final le rappelle : un « ✓ » qui
// couvre moins qu'il ne le dit est la forme la plus coûteuse d'erreur — c'est
// « ✓ 0 pages vérifiées » devant un répertoire inexistant, en août 2026.
const nonEprouve = []
const dire = (m) => console.log('  ' + m)

async function eprouverServi(nav, base) {
  console.log(`\n▸ Servi par un serveur statique nu (${base})`)
  for (const page of PAGES) {
    // La page elle-même, AVANT d'examiner ce qu'elle contient. Sans cette
    // ligne, une adresse que le serveur ne sait pas résoudre rend une page
    // d'erreur vide, dont on compte sereinement les zéro liens morts : le
    // dossier du 11/09 sortait « 0 lien, 0 mort » sur trois pages introuvables.
    const reponse = await fetch(base + page, { redirect: 'follow' })
    if (!reponse.ok) {
      problemes.push(`${page} : la page ne se sert pas — ${reponse.status}`)
      dire(`${page} — INTROUVABLE (${reponse.status})`)
      continue
    }
    await nav.aller(base + page)

    // L'amorce `__sveltekit` est encore là = le module ES n'a pas démarré.
    // C'est la signature exacte d'une page qui s'affiche et ne répond à rien.
    const hydrate = await nav.evaluer(
      '![...document.scripts].some(s => s.textContent.includes("__sveltekit"))')
    if (!hydrate) {
      problemes.push(`${page} : le site ne s'est pas hydraté — tout ce qui répond au clic est mort`)
    }
    for (const e of nav.erreurs) {
      problemes.push(`${page} : erreur console — ${String(e).slice(0, 200)}`)
    }

    // Les liens du DOM VIVANT, pas ceux du HTML prérendu : ce sont deux
    // ensembles différents dès que le navigateur a repeuplé la page.
    const liens = await nav.evaluer(`JSON.stringify([...new Set(
      [...document.querySelectorAll('a[href]')]
        .map(a => new URL(a.getAttribute('href'), location.href).href)
        .filter(u => u.startsWith(location.origin))
    )])`)
    const adresses = JSON.parse(liens || '[]')
    let morts = 0
    for (const adresse of adresses) {
      const r = await fetch(adresse, { redirect: 'follow' })
      if (!r.ok) {
        morts++
        problemes.push(`${page} : lien mort ${r.status} → ${adresse.slice(base.length)}`)
      }
    }
    dire(`${page} — ${adresses.length} liens internes vivants, ${morts} mort(s)`)
  }
}

async function eprouverSelecteur(nav, base) {
  console.log('\n▸ Le sélecteur d\'exercice du budget répond')
  const reponse = await fetch(base + '/budgets', { redirect: 'follow' })
  if (!reponse.ok) {
    dire(`page introuvable (${reponse.status}) — déjà signalé plus haut`)
    return
  }
  await nav.aller(base + '/budgets')
  const annees = await nav.evaluer(
    'JSON.stringify([...document.querySelectorAll("select option")].map(o => o.value))')
  const liste = JSON.parse(annees || '[]')
  if (liste.length < 2) {
    // Une commune peut n'avoir qu'un exercice publié : ce n'est pas un défaut.
    // Mais on le DIT, sinon un sélecteur mort passerait pour éprouvé.
    dire('un seul exercice dans ces données — le sélecteur n\'est pas éprouvé ici')
    nonEprouve.push('le sélecteur d\'exercice (ces données n\'ont qu\'une année)')
    return
  }
  const lire = () => nav.evaluer('document.body.innerText')
  const avant = await lire()
  await nav.evaluer(`{const s = document.querySelector('select');
    s.value = ${JSON.stringify(liste[liste.length - 1])};
    s.dispatchEvent(new Event('change', { bubbles: true }))}`)
  await new Promise((r) => setTimeout(r, 700))
  const apres = await lire()
  const retenu = await nav.evaluer('document.querySelector("select").value')
  if (retenu !== liste[liste.length - 1]) {
    problemes.push(`/budgets : le sélecteur n'a pas retenu l'exercice ${liste[liste.length - 1]}`)
  } else if (avant === apres) {
    problemes.push(
      `/budgets : changer d'exercice (${liste[0]} → ${liste[liste.length - 1]}) `
      + "n'a RIEN changé à l'affichage — la page est inerte")
  } else {
    dire(`${liste[0]} → ${liste[liste.length - 1]} : l'affichage suit`)
  }
}

async function eprouverFichier(nav) {
  console.log('\n▸ Ouvert en file:// par un double-clic')
  // Les chemins relatifs sont posés par `prepare_offline_export`, qui vit dans
  // le dépôt du portail. Un build brut du moteur n'est pas encore une archive
  // remise : on le DIT, plutôt que de compter des liens absolus comme un défaut
  // de ce build — ou, pire, de rendre un « ✓ » sur une épreuve qui n'a pas eu
  // lieu.
  if (!existsSync(join(BUILD, 'servir-le-dossier.py'))) {
    dire('build brut, non passé par prepare_offline_export — condition non éprouvée')
    nonEprouve.push('la lecture en file:// (build non mis en forme d\'archive)')
    return
  }
  // `index.html` et non `/` : c'est le fichier sur lequel le lecteur clique.
  const url = pathToFileURL(join(BUILD, 'index.html')).href
  await nav.aller(url)
  const rendu = await nav.evaluer('document.body.innerText.length')
  if (!rendu || rendu < 500) {
    problemes.push('file:// : la page d\'accueil ne montre presque rien')
  }
  const liens = await nav.evaluer(`JSON.stringify([...new Set(
    [...document.querySelectorAll('a[href]')]
      .map(a => a.getAttribute('href'))
      .filter(h => h && !/^(https?:|mailto:|#)/.test(h))
  )])`)
  const relatifs = JSON.parse(liens || '[]')
  const absolus = relatifs.filter((h) => h.startsWith('/'))
  if (absolus.length) {
    problemes.push(
      `file:// : ${absolus.length} lien(s) en chemin absolu, morts au double-clic `
      + `(${absolus.slice(0, 4).join(', ')})`)
  }
  let morts = 0
  for (const h of relatifs.filter((x) => !x.startsWith('/'))) {
    const cible = resolve(BUILD, decodeURIComponent(h.split('#')[0].split('?')[0]))
    const existe = existsSync(cible)
      && (statSync(cible).isFile() || existsSync(join(cible, 'index.html')))
    if (!existe) { morts++; problemes.push(`file:// : lien vers un fichier absent — ${h}`) }
  }
  dire(`${relatifs.length} liens, ${absolus.length} absolus, ${morts} vers un fichier absent`)
}

async function principal() {
  if (!existsSync(join(BUILD, 'index.html'))) {
    console.error(`\n✖ ${BUILD} ne contient pas index.html.\n`)
    process.exit(1)
  }
  const serveur = serveurNu(BUILD)
  await new Promise((r) => serveur.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${serveur.address().port}`
  const nav = await ouvrirNavigateur('about:blank')
  try {
    await eprouverServi(nav, base)
    await eprouverSelecteur(nav, base)
    await eprouverFichier(nav)
  } finally {
    nav.fermer()
    serveur.close()
  }

  if (problemes.length) {
    console.error(`\n✖ ${problemes.length} problème(s) dans le dossier hors-ligne :\n`)
    for (const p of problemes) console.error('  ' + p)
    console.error('\nLien mort servi : une adresse fabriquée par le JavaScript ne')
    console.error('désigne aucun fichier — vérifier `trailingSlash` dans')
    console.error('src/routes/+layout.js (le dossier remis se construit avec')
    console.error('VIGIE_HORS_LIGNE=1) et la réécriture de offline_export.py.')
    console.error('Page inerte : une fonction `const` qui lit une variable')
    console.error("réactive ne crée aucune dépendance — la déclarer en `$:`.\n")
    process.exit(1)
  }
  console.log('\n✓ Le dossier tient servi par n\'importe quel serveur statique.')
  if (nonEprouve.length) {
    console.log('  Non éprouvé ici : ' + nonEprouve.join(' ; ') + '.')
  } else {
    console.log('  Et il se lit au double-clic.')
  }
  console.log('')
}

principal().catch((e) => { console.error('\n✖ ' + e.message + '\n'); process.exit(1) })
