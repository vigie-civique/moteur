// Le rendu des dossiers ne laisse passer ni script, ni gestionnaire d'événement,
// ni adresse exécutable — et garde le repli dont les dossiers se servent.
//
// Joué à chaque `npm run build` : un dossier est écrit dans l'atelier par un
// contributeur et publié tel quel dans la page (`{@html}`). Si ce contrôle
// tombe, le site ne se construit pas.
import assert from 'node:assert/strict'
import { markdownSur } from '../src/lib/markdown.js'

const CAS = [
  // [markdown, ce qui NE doit PAS sortir, ce qui DOIT sortir]
  ['<script>alert(1)</script>', /<script/i, /&lt;script&gt;/],
  ['Texte <img src=x onerror=alert(1)> suite', /<img/i, /&lt;img/],
  ['<details class="plus" ontoggle="alert(1)">\n<summary>x</summary>\n\ny\n\n</details>', /<details[^>]*ontoggle/i, /&lt;details/],
  ['<iframe src="https://exemple.fr"></iframe>', /<iframe/i, /&lt;iframe/],
  ['<svg onload=alert(1)', /<svg/i, /&lt;svg/],
  ['[cliquer](javascript:alert(1))', /javascript:/i, /href="#"/],
  ['[cliquer](JaVaScRiPt:alert(1))', /javascript:/i, /href="#"/],
  ['[cliquer](data:text/html,x)', /data:text/i, /href="#"/],
  ['[cliquer](//exemple.fr/x)', /href="\/\/exemple/, /href="#"/],
  ['![x](javascript:alert(1))', /javascript:/i, /src="#"/],
]
for (const [texte, interdit, attendu] of CAS) {
  const html = markdownSur(texte)
  assert.doesNotMatch(html, interdit, `passe à travers : ${texte}\n→ ${html}`)
  assert.match(html, attendu, `rendu inattendu : ${texte}\n→ ${html}`)
}

// Ce dont les dossiers se servent doit sortir INTACT.
const repli = markdownSur('## Partie\n\n<details class="plus">\n<summary>Pour aller plus loin</summary>\n\nLe **détail**.\n\n</details>\n')
assert.match(repli, /<details class="plus">\s*<summary>Pour aller plus loin<\/summary>/)
assert.match(repli, /<strong>détail<\/strong>/)
assert.match(repli, /<\/details>/)
for (const [texte, attendu] of [
  ['[source](https://exemple.fr/pv.pdf)', /href="https:\/\/exemple\.fr\/pv\.pdf"/],
  ['[la page](/deliberations)', /href="\/deliberations"/],
  ['[plus bas](#l-essentiel)', /href="#l-essentiel"/],
  ['[écrire](mailto:contact@exemple.fr)', /href="mailto:contact@exemple\.fr"/],
  ['| a | b |\n|---|---|\n| 1 | 2 |', /<table>/],
  ['Un prix < 40 000 € et > 0', /&lt; 40 000/],
  // Les liens que pose le résolveur de citations (collectors/citations.py) :
  // une adresse interne ancrée sur la clé datée, et une infobulle.
  ['([CM du 14/04/2021](/deliberations/2021#c-2021-41 "Délibération n°41 — Conseil municipal"))',
   /<a href="\/deliberations\/2021#c-2021-41" title="Délibération n°41 — Conseil municipal">CM du 14\/04\/2021<\/a>/],
  ['| [17/02/2016](/deliberations/2016#a12 "Délibération") | Motion | CM |\n|---|---|---|', /href="\/deliberations\/2016#a12"/],
]) assert.match(markdownSur(texte), attendu, texte)

// La syntaxe explicite (`acte:`, `seance:`, `piece:`) est remplacée AU BUILD.
// Si elle arrivait jusqu'ici — un aperçu local des brouillons —, elle ne doit
// rien ouvrir : ce n'est pas une adresse.
for (const texte of ['[le vote](acte:c-2021-41)', '[la séance](seance:c-2021-04-14)', '[la pièce](piece:c-2021-41)'])
  assert.match(markdownSur(texte), /href="#"/, texte)
// Une infobulle ne sort pas de son attribut, quoi qu'un titre d'acte contienne :
// le résolveur remplace les guillemets droits, marked échappe le reste.
assert.doesNotMatch(markdownSur('[x](/deliberations/2021#c-2021-41 "a <b onmouseover=alert(1)> & c")'),
                    /<b onmouseover/)

console.log(`✓ rendu des dossiers : ${CAS.length} injections arrêtées, le repli et les liens ordinaires passent`)
