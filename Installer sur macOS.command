#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Vigie Civique — installation
#
#  DOUBLE-CLIQUER CE FICHIER. Rien d'autre à faire, rien à taper.
#
#  La première fois, macOS peut refuser d'ouvrir un fichier téléchargé :
#  faire alors un CLIC DROIT dessus → « Ouvrir », puis confirmer. C'est le
#  contrôle de provenance d'Apple, il ne se prononce pas sur le contenu.
#
#  Cette fenêtre de terminal sert à afficher l'avancement ; l'installation,
#  elle, se passe dans votre navigateur. La laisser ouverte jusqu'au bout.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
exec ./installateur/amorcage.sh
