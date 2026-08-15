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

# Contrôlé AVANT de travailler : découvrir qu'il manque un nom de projet après
# trois minutes de build, c'est trois minutes perdues pour une variable.
if [ "$DEPLOYER" -eq 1 ]; then
  if [ -z "${CF_PROJECT:-}" ]; then
    echo "✖ CF_PROJECT non défini : nom du projet Cloudflare Pages à publier." >&2
    echo "  Sans --deployer, le site est construit dans public/build/ et" >&2
    echo "  se téléverse tel quel chez n'importe quel hébergeur statique." >&2
    exit 1
  fi
  if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ ! -t 0 ]; then
    echo "✖ Ni CLOUDFLARE_API_TOKEN ni terminal interactif : wrangler ne pourra" >&2
    echo "  pas s'authentifier. Inutile de construire le site." >&2
    exit 1
  fi
fi

echo "1/4 — Snapshot public (base → snapshot → public/static/data)"
# Le snapshot refuse de se construire si `entities.perimetre` n'a jamais été
# renseignée : sans classement, le site publierait l'intercommunalité entière
# à la place de la commune. Lancer alors `python3 -m collectors.run_all --step perimetre`.
"$PY" "$ROOT/scripts/build_public_snapshot.py" | tail -5

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

echo "4/4 — Mise en ligne Cloudflare Pages ($CF_PROJECT)"
# --branch=main force l'environnement Production : sans lui, wrangler détecte la
# branche git courante et déploie en Preview — la production reste vide.
( cd "$ROOT/public" && npx wrangler pages deploy build \
    --project-name="$CF_PROJECT" --branch=main --commit-dirty=true )

echo "✓ Site public en ligne."
