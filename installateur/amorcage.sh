#!/bin/sh
# amorcage.sh — trouver un Python, et seulement ça.
#
# C'est le seul fichier de l'installation qui ne PEUT PAS être écrit en Python :
# il s'exécute sur une machine où il n'y en a peut-être aucun. Il fait donc le
# strict minimum — obtenir un interpréteur assez récent — et passe la main à
# `assistant.py`, qui parle au navigateur.
#
# Ordre de préférence, et il compte :
#   1. un Python ≥ 3.11 déjà installé — on ne télécharge pas 40 Mo pour rien ;
#   2. à défaut, un Python posé DANS installateur/.outils/, par `uv`.
#
# Rien n'est installé sur le système, rien ne demande de mot de passe
# d'administrateur, rien ne modifie le PATH. Jeter le dossier suffit à tout
# désinstaller.
#
# POSIX strict (`/bin/sh`) : sur une Debian minimale, `bash` peut manquer.
set -eu

ICI=$(cd "$(dirname "$0")" && pwd)
OUTILS="$ICI/.outils"
PYTHON_MIN="3.11"

dire() { printf '%s\n' "$*"; }
# Vers la sortie d'erreur : la fonction qui pose Python RETOURNE un chemin
# sur sa sortie standard. Un message d'avancement mêlé à ce chemin, et
# c'est « Python : téléchargement… » qu'on tente ensuite d'exécuter.
raconter() { printf '%s\n' "$*" >&2; }

assez_recent() {
  [ -x "$1" ] || return 1
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

# `/usr/bin/python3` sur macOS est un LEURRE tant que les outils de développement
# ne sont pas installés : l'appeler ouvre une fenêtre système qui propose de
# télécharger un compilateur. Pour un installateur qui promet de ne rien
# demander, c'est le pire des accueils. On ne l'interroge donc jamais dans ce cas.
utilisable() {
  if [ "$(uname -s)" = "Darwin" ] && [ "$1" = "/usr/bin/python3" ] \
     && [ ! -x /Library/Developer/CommandLineTools/usr/bin/python3 ]; then
    return 1
  fi
  assez_recent "$1"
}

trouver_python() {
  for chemin in "$OUTILS"/python/*/bin/python3 \
                /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if utilisable "$chemin"; then dire "$chemin"; return 0; fi
  done
  for nom in python3.14 python3.13 python3.12 python3.11 python3; do
    chemin=$(command -v "$nom" 2>/dev/null) || continue
    if utilisable "$chemin"; then dire "$chemin"; return 0; fi
  done
  return 1
}

telecharger() {
  # curl est partout sur macOS, wget sur beaucoup de Linux : on prend celui
  # qui est là plutôt que d'exiger l'autre.
  if command -v curl >/dev/null 2>&1; then
    curl -fL --proto '=https' --tlsv1.2 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    dire "✖ Ni curl ni wget sur cette machine : impossible de télécharger."
    dire "  Installer Python 3.11 ou plus récent, puis relancer."
    exit 1
  fi
}

cible_uv() {
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)   dire "uv-aarch64-apple-darwin" ;;
    Darwin-x86_64)  dire "uv-x86_64-apple-darwin" ;;
    Linux-aarch64)  dire "uv-aarch64-unknown-linux-gnu" ;;
    Linux-x86_64)   dire "uv-x86_64-unknown-linux-gnu" ;;
    *) dire "" ;;
  esac
}

poser_python() {
  cible=$(cible_uv)
  if [ -z "$cible" ]; then
    raconter "✖ Système non reconnu : $(uname -s) $(uname -m)."
    raconter "  Installer Python $PYTHON_MIN ou plus récent, puis relancer ce fichier."
    exit 1
  fi
  mkdir -p "$OUTILS"
  raconter ""
  raconter "  Aucun Python récent sur cette machine."
  raconter "  Je vais en poser un DANS ce dossier (≈ 40 Mo, rien sur le système)."
  raconter ""

  # `latest` plutôt qu'une version figée : cet outil ne sert qu'à télécharger un
  # interpréteur, aucune reproductibilité ne repose sur lui — alors qu'un numéro
  # figé qui disparaît un jour du dépôt bloquerait toute installation, sur toutes
  # les machines, sans recours pour celui qui la subit.
  telecharger "https://github.com/astral-sh/uv/releases/latest/download/$cible.tar.gz" \
              "$OUTILS/uv.tar.gz"
  tar -xzf "$OUTILS/uv.tar.gz" -C "$OUTILS"
  rm -f "$OUTILS/uv.tar.gz"
  UV=$(find "$OUTILS" -type f -name uv -perm -u+x 2>/dev/null | head -1)
  [ -n "$UV" ] || { raconter "✖ uv téléchargé mais introuvable dans l'archive."; exit 1; }

  # Les deux variables enferment uv dans notre dossier : sans elles il écrit
  # dans ~/.local/share/uv et ~/.cache/uv, c'est-à-dire hors de ce que
  # l'utilisateur croit avoir installé — et qu'il ne saura pas retirer.
  UV_PYTHON_INSTALL_DIR="$OUTILS/python" UV_CACHE_DIR="$OUTILS/cache-uv" \
    "$UV" python install 3.12 >&2

  for chemin in "$OUTILS"/python/*/bin/python3; do
    if assez_recent "$chemin"; then dire "$chemin"; return 0; fi
  done
  raconter "✖ Python posé mais introuvable ensuite."
  exit 1
}

PY=$(trouver_python || true)
if [ -z "$PY" ]; then
  # `poser_python` tourne dans un sous-shell : son `exit 1` n'arrête que
  # celui-ci et rend une chaîne vide. Sans ce contrôle, l'échec se traduirait
  # trois lignes plus bas par un `exec` sur un chemin vide — message
  # incompréhensible pour une cause parfaitement claire.
  PY=$(poser_python) || true
fi
if [ -z "$PY" ]; then
  dire ""
  dire "✖ Installation impossible : aucun Python utilisable, et le téléchargement"
  dire "  n'a pas abouti. Les lignes ci-dessus disent où ça s'est arrêté."
  exit 1
fi

dire ""
dire "  Python : $PY"
exec "$PY" "$ICI/assistant.py"
