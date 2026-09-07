#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Vigie Civique — installation
#
#  DOUBLE-CLIQUER CE FICHIER, puis « Exécuter » si le gestionnaire de fichiers
#  le demande. (Certains environnements ouvrent les .sh dans un éditeur : dans
#  ce cas, clic droit → « Exécuter comme un programme ».)
#
#  L'installation se passe dans votre navigateur ; cette fenêtre affiche
#  l'avancement et doit rester ouverte.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
exec ./installateur/amorcage.sh
