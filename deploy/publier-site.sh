#!/usr/bin/env bash
# Publication du SITE PUBLIC : base locale → snapshot → build → hébergeur.
#
#   ./deploy/publier-site.sh                    # snapshot + build, sans mise en ligne
#   CF_PROJECT=vigie-civique-macommune ./deploy/publier-site.sh --deployer
#
# Ce script tourne sur la MACHINE QUI PORTE LA BASE, pas sur un serveur : le
# site public n'a pas de backend, tout est figé au build. La base ne quitte
# jamais la machine.
#
# L'étape de mise en ligne est optionnelle et volontairement séparée : `wrangler`
# est propre à Cloudflare Pages. Pour un autre hébergeur (Netlify, GitHub Pages,
# un simple rsync vers un OVH), il n'y a rien à changer avant l'étape 4 — le
# répertoire `public/build/` est un site statique ordinaire.
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

DEPLOYER=0
[ "${1:-}" = "--deployer" ] && DEPLOYER=1

# Quel hébergeur, et pourquoi rien n'est choisi par défaut.
#
# Ce moteur est destiné à être REPRIS : il ne doit imposer aucun fournisseur.
# `rsync` n'est pas « OVH » — c'est « une machine à vous, jointe par ssh », ce
# qui vaut pour un VPS, un serveur associatif ou un mutualisé. Et `cloudflare`
# reste là pour qui l'utilise déjà.
#
# Sans indication, on déduit de `CF_PROJECT` afin de ne pas casser les appels
# existants ; à défaut on REFUSE, plutôt que de deviner. Un script qui choisit
# tout seul où publier un site public publiera un jour au mauvais endroit.
cible() {
  if [ -n "${VIGIE_CIBLE:-}" ]; then echo "$VIGIE_CIBLE"; return; fi
  if [ -n "${CF_PROJECT:-}" ]; then echo cloudflare; return; fi
  echo indecis
}

# Contrôlé AVANT de travailler : découvrir qu'il manque un nom de projet après
# trois minutes de build, c'est trois minutes perdues pour une variable.
if [ "$DEPLOYER" -eq 1 ] && [ "$(cible)" = "cloudflare" ]; then
  if [ -z "${CF_PROJECT:-}" ]; then
    echo "✖ CF_PROJECT non défini : nom du projet Cloudflare Pages à publier." >&2
    echo "  Sans --deployer, le site est construit dans public/build/ et" >&2
    echo "  se téléverse tel quel chez n'importe quel hébergeur statique." >&2
    exit 1
  fi
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

echo "1/4 — Snapshot public (base → snapshot → public/static/data)"
# Le snapshot refuse de se construire si `entities.perimetre` n'a jamais été
# renseignée : sans classement, le site publierait l'intercommunalité entière
# à la place de la commune. Lancer alors `python3 -m collectors.run_all --step perimetre`.
"$PY" "$ROOT/scripts/build_public_snapshot.py" | tail -5

# macOS sème des .DS_Store dans tout répertoire ouvert au Finder, et
# `verify_snapshot.py` les REFUSE — à juste titre : ce sont des fichiers du
# poste, ils n'ont rien à faire dans un site publié.
#
# Le nettoyage vivait dans `vigie_maj_instance.sh`, un script personnel. Une
# construction lancée directement échouait donc sur l'invariant, alors que la
# même construction lancée par l'autre chemin passait. Un nettoyage n'a de sens
# qu'au POINT DE PASSAGE OBLIGÉ : ici.
find "$ROOT/public/static/data" "$ROOT/public/build" -name '.DS_Store' -delete 2>/dev/null || true

echo "2/4 — Invariants du snapshot"
# Contrôle adverse, indépendant du builder : confidences privées, relations hors
# liste, coordonnées de personnes, secrets, et part de la commune dans ce qui est
# publié. Un snapshot qui fuit ne doit pas atteindre l'étape suivante.
"$PY" "$ROOT/scripts/verify_snapshot.py" "$ROOT/public/static/data" || {
  echo "   ✖ snapshot refusé : un invariant est violé. Publication interrompue." >&2
  exit 1
}

echo "3/4 — Build du site (adapter-static → public/build)"
# `npm run build` échoue si une page est livrée sans son contenu :
# cf. public/scripts/verifier_build.mjs.
( cd "$ROOT/public" && npm run build )

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
case "$(cible)" in
  rsync)
    : "${VIGIE_CIBLE_HOTE:?cible rsync : VIGIE_CIBLE_HOTE manquant (hôte ssh)}"
    : "${VIGIE_CIBLE_CHEMIN:?cible rsync : VIGIE_CIBLE_CHEMIN manquant (dossier servi)}"
    echo "4/4 — Mise en ligne par rsync ($VIGIE_CIBLE_HOTE:$VIGIE_CIBLE_CHEMIN)"

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
    echo "✓ Site public en ligne."
    ;;
  cloudflare)
    echo "4/4 — Mise en ligne Cloudflare Pages ($CF_PROJECT)"
    # --branch=main force l'environnement Production : sans lui, wrangler
    # détecte la branche git courante et déploie en Preview — la production
    # reste vide.
    ( cd "$ROOT/public" && npx wrangler pages deploy build \
        --project-name="$CF_PROJECT" --branch=main --commit-dirty=true )
    echo "✓ Site public en ligne."
    ;;
  *)
    echo "✖ Aucun hébergeur indiqué. Choisir explicitement :" >&2
    echo "    VIGIE_CIBLE=rsync VIGIE_CIBLE_HOTE=… VIGIE_CIBLE_CHEMIN=…" >&2
    echo "    VIGIE_CIBLE=cloudflare CF_PROJECT=…" >&2
    echo "  Le build est prêt dans public/build/ : il se téléverse tel quel" >&2
    echo "  chez n'importe quel hébergeur statique." >&2
    exit 1
    ;;
esac
