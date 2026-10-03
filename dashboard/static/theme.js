// Thème de l'atelier, posé AVANT le premier rendu : sans lui, une page choisie
// « Clair » s'ouvrirait d'abord en sombre (ou l'inverse), le temps que
// l'application démarre.
//
// Un fichier, et non un script écrit dans app.html : la CSP de l'atelier
// (svelte.config.js, kit.csp) n'admet que les scripts que le build signe et
// ceux servis par l'atelier lui-même ('self'). Un script en ligne non signé
// serait refusé par le navigateur — ou obligerait à affaiblir la CSP.
//
// Même clé et mêmes valeurs que src/lib/theme.js.
(function () {
  var choix = null
  try { choix = localStorage.getItem('atelier-theme') } catch (e) {}
  if (choix === 'light' || choix === 'dark') {
    document.documentElement.setAttribute('data-theme', choix)
    // Le fond peint avant que le CSS arrive suit aussi le choix.
    document.documentElement.style.colorScheme = choix
  }
})()
