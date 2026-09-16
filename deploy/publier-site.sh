#!/usr/bin/env bash
# Publication du SITE PUBLIC : base locale → aperçu → promotion → build → hébergeur.
#
#   ./deploy/publier-site.sh                         # aperçu + promotion + build, sans mise en ligne
#   ./deploy/publier-site.sh --deployer              # … et mise en ligne, puis constat
#   ./deploy/publier-site.sh --deployer --deja-promu # déployer la version promue, sans rien reconstruire
#
# Ce script tourne sur la MACHINE QUI PORTE LA BASE, pas sur un serveur : le
# site public n'a pas de backend, tout est figé au build. La base ne quitte
# jamais la machine.
#
# UN SEUL CHEMIN DE PUBLICATION. Les étapes 1 et 2 sont celles de la page
# Publication de l'atelier (`scripts/publication.py`), et le bouton « Mettre en
# ligne » de l'atelier rejoue les étapes 3 à 5 de ce script (`--deja-promu`).
# Jusqu'au 16/09/2026, chacun avait les siens : ce script écrivait le snapshot
# directement dans les répertoires servis, sans laisser de trace à l'atelier, et
# l'atelier téléversait par `wrangler` en dur, vers un hébergeur quitté depuis
# quinze jours.
#
# OÙ PART LE SITE : déclaré une fois, dans le bloc `publication` de
# `config/instance.json` —
#     {"cible": "rsync", "hote": "monserveur", "chemin": "/srv/site", "rsync_path": "sudo -u web rsync"}
#     {"cible": "cloudflare", "projet": "vigie-civique-macommune"}
# Les variables d'environnement (`VIGIE_CIBLE`, `VIGIE_CIBLE_HOTE`,
# `VIGIE_CIBLE_CHEMIN`, `VIGIE_CIBLE_RSYNC_PATH`, `CF_PROJECT`) restent
# prioritaires. Rien de déclaré : le script REFUSE plutôt que de deviner.
#
# Authentification Cloudflare, deux modes :
#   - poste de travail : `npx wrangler login` (interactif, session locale) ;
#   - machine sans écran : exporter CLOUDFLARE_API_TOKEN.
# Le jeton doit être RESTREINT au projet Pages (Cloudflare → My Profile → API
# Tokens → « Edit Cloudflare Workers », limité au compte et au projet). Un jeton
# global sur une machine exposée donne à qui le lit le contrôle du domaine.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$ROOT/venv/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"
PUBLICATION="$ROOT/scripts/publication.py"

DEPLOYER=0
DEJA_PROMU=0
for option in "$@"; do
  case "$option" in
    --deployer)   DEPLOYER=1 ;;
    --deja-promu) DEJA_PROMU=1 ;;
    *) echo "✖ option inconnue : $option" >&2; exit 1 ;;
  esac
done

# Où publier — résolu AVANT de travailler : découvrir qu'il manque une
# destination après trois minutes de build, c'est trois minutes perdues pour
# une ligne de configuration. La résolution vit dans `publication.py`, qui sert
# aussi l'atelier : un seul lecteur de la déclaration, un seul ordre de priorité.
if [ "$DEPLOYER" -eq 1 ]; then
  declaration="$("$PY" "$PUBLICATION" destination --shell)" || {
    echo "  Sans --deployer, le site est construit dans public/build/ et" >&2
    echo "  se téléverse tel quel chez n'importe quel hébergeur statique." >&2
    exit 1
  }
  eval "$declaration"
  echo "→ destination : $("$PY" "$PUBLICATION" destination)"
fi

if [ "$DEPLOYER" -eq 1 ] && [ "$VIGIE_CIBLE" = "cloudflare" ]; then
  # Trois façons d'être authentifié, et la troisième manquait : une session
  # `wrangler login` DÉJÀ ouverte tient dans un fichier et fonctionne sans
  # terminal. Exiger un tty refusait la publication depuis un script, un cron
  # ou un agent, alors que les identifiants étaient là.
  session_ouverte=0
  for c in "${WRANGLER_HOME:-}/config/default.toml" \
           "$HOME/.wrangler/config/default.toml" \
           "${XDG_CONFIG_HOME:-$HOME/.config}/.wrangler/config/default.toml"; do
    # Forme explicite : sous `set -e`, un « [ -f … ] && x=1 » qui échoue laisse
    # une liste en échec, et ce piège a déjà coûté une soirée sur ce projet.
    if [ -f "$c" ]; then session_ouverte=1; fi
  done
  if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ "$session_ouverte" -eq 0 ] && [ ! -t 0 ]; then
    echo "✖ Aucun moyen de s'authentifier chez Cloudflare : ni CLOUDFLARE_API_TOKEN," >&2
    echo "  ni session « npx wrangler login » ouverte, ni terminal interactif." >&2
    echo "  Inutile de construire le site." >&2
    exit 1
  fi
fi

# macOS sème des .DS_Store dans tout répertoire ouvert au Finder, et
# `verify_snapshot.py` les REFUSE — à juste titre : ce sont des fichiers du
# poste, ils n'ont rien à faire dans un site publié. Le nettoyage vit ici, au
# POINT DE PASSAGE OBLIGÉ, et couvre tout ce que le flux lit ou recopie.
nettoyer_finder() {
  find "$ROOT/public/static" "$ROOT/public/build" "$ROOT/public/.svelte-kit" \
       "$ROOT/audits" "$ROOT/dashboard/static" \
    -name '.DS_Store' -delete 2>/dev/null || true
}

if [ "$DEJA_PROMU" -eq 0 ]; then
  nettoyer_finder
  echo "1/5 — Aperçu : snapshot dans le brouillon, puis contrôle d'étanchéité"
  # Le snapshot refuse de se construire si `entities.perimetre` n'a jamais été
  # renseignée : sans classement, le site publierait l'intercommunalité entière
  # à la place de la commune. Lancer alors `python3 -m collectors.run_all --step perimetre`.
  #
  # Le contrôle est un adversaire du builder (`verify_snapshot.py`) : confidences
  # privées, relations hors liste, coordonnées de personnes, secrets, part de la
  # commune dans ce qui est publié. Un aperçu refusé n'atteint pas l'étape suivante.
  "$PY" "$PUBLICATION" apercu || {
    echo "   ✖ aperçu refusé : rien n'a été promu, le site est inchangé." >&2
    exit 1
  }

  echo "2/5 — Promotion : l'aperçu contrôlé devient la version servie"
  # Recontrôlé à l'arrivée, mis en service par renommage, `version.json` écrit :
  # c'est cette empreinte que l'étape 5 cherchera en ligne.
  "$PY" "$PUBLICATION" publier
else
  echo "1-2/5 — Sautées (--deja-promu) : la version promue part telle quelle"
  if [ ! -f "$ROOT/public/static/data/version.json" ]; then
    echo "✖ public/static/data ne déclare aucune version promue — publier d'abord." >&2
    exit 1
  fi
fi

echo "3/5 — Build du site (adapter-static → public/build)"
# Les libellés du site sont dérivés de la même instance que le snapshot : les
# régénérer ici évite qu'un site publie le nom d'une commune et les chiffres
# d'une autre.
"$PY" "$ROOT/scripts/generer_libelles.py" | tail -3
nettoyer_finder
# `npm run build` échoue si une page est livrée sans son contenu :
# cf. public/scripts/verifier_build.mjs.
( cd "$ROOT/public" && npm run build )
nettoyer_finder

# Tout ce qui est dans `public/static/` part en ligne, y compris ce qu'aucun
# Finder ne montre. Le 16/09/2026, lasalle.vigie-civique.fr servait ainsi
# `/.data.precedent/` — la version du 23/08, retour arrière de l'atelier rangé à
# côté du répertoire servi. Un site statique n'a pas de fichier caché à servir,
# hormis `.well-known`.
#
# Pas de `| head` ici : sous `pipefail`, head ferme le tube, find reçoit SIGPIPE
# et l'affectation échoue — le script s'arrêterait sans dire pourquoi.
caches="$(find "$ROOT/public/build" -name '.*' -not -name '.well-known')"
if [ -n "$caches" ]; then
  echo "✖ le build contient des fichiers cachés, qui partiraient en ligne :" >&2
  printf '%s\n' "$caches" | sed -n '1,5p' >&2
  echo "  Les retirer de public/static/ (ce sont des rebuts du poste), puis relancer." >&2
  exit 1
fi

if [ "$DEPLOYER" -eq 0 ]; then
  echo
  echo "✓ Site construit dans public/build/ — pas mis en ligne (--deployer pour publier)."
  exit 0
fi

# L'en-tête de ce fichier annonçait depuis toujours qu'« un simple rsync vers un
# OVH » suffirait, `public/build/` étant un site statique ordinaire : il n'y
# avait qu'à l'écrire. Fait le 01/09/2026, en déplaçant l'instance de Lasalle
# hors de Cloudflare Pages — le portail en était sorti le 31/08 et l'expliquait
# longuement pendant que les sites qu'il recommande y restaient.
case "$VIGIE_CIBLE" in
  rsync)
    echo "4/5 — Mise en ligne par rsync ($VIGIE_CIBLE_HOTE:$VIGIE_CIBLE_CHEMIN)"

    # `--delete` : une page retirée d'une collecte doit disparaître du site.
    # Sans lui, un fichier supprimé du build resterait servi indéfiniment — et
    # un site de transparence qui garde une page qu'il a cessé de publier ment
    # par omission inverse.
    #
    # `_redirects` est EXCLU : Cloudflare Pages le lisait, un serveur ordinaire
    # l'ignore. Ses règles doivent être traduites dans la configuration du
    # serveur ; le laisser ferait croire qu'elles agissent encore.
    #
    # `VIGIE_CIBLE_RSYNC_PATH` sert quand le compte qui se connecte n'est pas
    # celui qui possède les fichiers — sinon le serveur finit par servir des
    # fichiers que la publication suivante ne peut plus remplacer.
    rsync -az --delete --exclude='_redirects' \
      ${VIGIE_CIBLE_RSYNC_PATH:+--rsync-path="$VIGIE_CIBLE_RSYNC_PATH"} \
      "$ROOT/public/build/" "$VIGIE_CIBLE_HOTE:$VIGIE_CIBLE_CHEMIN/"
    ;;
  cloudflare)
    echo "4/5 — Mise en ligne Cloudflare Pages ($CF_PROJECT)"
    # --branch=main force l'environnement Production : sans lui, wrangler
    # détecte la branche git courante et déploie en Preview — la production
    # reste vide.
    ( cd "$ROOT/public" && npx wrangler pages deploy build \
        --project-name="$CF_PROJECT" --branch=main --commit-dirty=true )
    ;;
esac

echo "5/5 — Constat : le site en ligne sert-il la version promue ?"
# Un téléversement qui rend 0 dit que des fichiers sont partis, pas que le site
# les sert. `version.json` est relu EN LIGNE et comparé à l'empreinte promue ;
# le verdict est écrit dans l'état, que la page Publication affiche.
"$PY" "$PUBLICATION" verifier --essais 3
echo "✓ Site public en ligne."
