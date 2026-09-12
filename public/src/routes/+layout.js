// App publique = statique. Pages prérendues ; les données se chargent côté client.
export const prerender = true

// ⚠️ La forme des adresses décide de ce qui est ÉCRIT sur le disque, et donc de
// ce qu'un serveur statique quelconque saura retrouver.
//
// En ligne, `ignore` : adapter-static écrit `budgets.html`, servi sur
// `/budgets` par l'hébergeur, qui devine l'extension. C'est la forme canonique
// du site public, celle du sitemap, et elle ne bouge pas.
//
// Hors ligne, `always` : chaque route devient `budgets/index.html`. Le dossier
// remis est lu par des serveurs qui ne devinent RIEN — `python -m http.server`,
// une extension d'éditeur, le double-clic. Or le JavaScript du site repose les
// adresses en absolu au chargement (la barre de navigation est construite
// depuis un tableau, les fiches depuis un identifiant) : un clic demandait donc
// « /budgets » à un serveur qui n'y voyait qu'un RÉPERTOIRE — celui qui ne
// contient que `__data.json` — et servait une liste de fichiers. Avec
// `index.html` dedans, le même serveur redirige vers `/budgets/` et sert la
// page. Réglé à la source, une fois, plutôt qu'en réécrivant après coup les
// soixante adresses que le bundle fabrique.
//
// `__VIGIE_HORS_LIGNE__` est posé au build par vite.config.js (VIGIE_HORS_LIGNE).
export const trailingSlash = __VIGIE_HORS_LIGNE__ ? 'always' : 'ignore'
