// Le markdown d'un dossier, rendu en HTML qu'on peut poser tel quel dans la page.
//
// Un dossier est le seul endroit du site où un humain écrit, et depuis le
// 01/10/2026 il s'écrit dans l'atelier — donc par un contributeur. `marked`
// laisse passer le HTML brut et ne regarde pas l'adresse d'un lien : une balise
// `<script>` ou un lien `javascript:` écrits dans un dossier retenu
// s'exécutaient chez chaque visiteur du site public.
//
// Ce qui reste permis est ce dont les dossiers se servent VRAIMENT (relevé sur
// les huit dossiers de l'instance d'origine le 02/10/2026) : le repli
// « pour aller plus loin ». Tout le reste s'affiche comme du texte — on voit la
// balise au lieu de la subir, et celui qui relit la voit aussi.
import { Marked } from 'marked'

const BALISES_PERMISES = /^<(details( class="plus")?( open)?|\/details|summary|\/summary|br ?\/?|\/?(sup|sub))>$/
const ADRESSE_PERMISE = /^(https?:\/\/|mailto:|\/(?!\/)|#)/i

const echapper = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const rendu = new Marked({
  walkTokens(token) {
    if (token.type === 'html') {
      // Un bloc HTML peut porter plusieurs balises et du texte : chaque balise
      // est jugée seule. `>?` : une balise jamais refermée est une balise.
      token.text = token.text.replace(/<[^>]*>?/g, (b) => (BALISES_PERMISES.test(b) ? b : echapper(b)))
    } else if ((token.type === 'link' || token.type === 'image') && !ADRESSE_PERMISE.test(token.href.trim())) {
      token.href = '#'
    }
  },
})

export function markdownSur(texte) {
  return rendu.parse(texte)
}
