"""Le `.gitignore` du moteur : ce qu'il doit taire, et ce qu'il ne doit jamais taire.

Deux défauts réels, tous deux invisibles jusqu'à ce qu'on lise le fichier :

  * `territoire/`, sans barre de tête, désignait n'importe quel répertoire de ce
    nom à n'importe quelle profondeur — dont `public/src/routes/territoire/`, la
    page « Le territoire en chiffres ». Ses deux fichiers étaient déjà suivis,
    donc rien n'a été perdu ; un fichier NEUF y aurait été ignoré en silence.
  * à l'inverse, `dashboard/static/public_api/` et `public/static/data/` étaient
    ignorés mais pas leurs voisins `.public_api.precedent/` et
    `.data.precedent/` — 1 441 fichiers et 18 Mo chacun, que le premier
    `git add -A` d'une instance aurait versionnés dans un dépôt PUBLIC. La
    publication en deux temps n'écrit pas SUR le répertoire servi : elle écrit
    À CÔTÉ, puis renomme.

Les deux sens comptent donc, et ce test les tient tous les deux : rien de suivi
ne doit être ignoré, et rien de ce qui appartient à une instance ne doit cesser
de l'être.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    """Sortie de git, ou skip si le dépôt n'est pas là (archive, tarball, kit)."""
    if not (ROOT / ".git").exists():
        pytest.skip("pas un dépôt git : rien à contrôler ici")
    try:
        r = subprocess.run(("git", "-C", str(ROOT), *args),
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:  # pragma: no cover
        pytest.skip(f"git indisponible : {e}")
    assert r.returncode in (0, 1), f"git {' '.join(args)} : {r.stderr.strip()}"
    return r.stdout


def test_aucun_fichier_suivi_n_est_ignore():
    """Le défaut se voit d'une seule commande, et il n'a pas d'exception
    légitime : un fichier à la fois suivi et ignoré est une contradiction. Il
    survit tant que personne ne le touche, puis avale son voisin neuf."""
    ignores = [l for l in git("ls-files", "-i", "-c", "--exclude-standard").splitlines() if l]
    assert not ignores, (
        "Ces fichiers sont SUIVIS et pourtant ignorés :\n  "
        + "\n  ".join(ignores)
        + "\n\nUne règle de .gitignore est trop large. Presque toujours : il lui "
          "manque la barre de tête qui l'ancre à la racine (`/territoire/` et non "
          "`territoire/`), sans quoi elle vise ce nom à toutes les profondeurs.")


# Ce qui appartient à une instance, et jamais au moteur. Écrit ici pour qu'on ne
# puisse pas faire passer le test ci-dessus en RETIRANT une règle.
@pytest.mark.parametrize("chemin", [
    "territoire/pois_30140.geojson",          # périmètre communal, produit par osm
    "db/30140.db",                            # la base
    "db/30140.db.avant-purge-20260826-2051",  # ses sauvegardes
    "config/instance.json",                   # le périmètre déclaré
    "config/publication_rules.json",
    "config/publication_rules.json.avant-decp-20260824-211251",
    "config/arbitrages_entites.json",         # décisions humaines, nominatives
    "config/dossiers_locaux.json",
    "public/static/data/entities.json",       # le snapshot servi
    "public/static/.data.precedent/entities.json",   # son retour arrière
    "dashboard/static/public_api/budget.json",
    "dashboard/static/.public_api.precedent/budget.json",
    "public/static/carte/fond.pmtiles",       # artefact d'instance, borné à sa commune
    ".wrangler/cache/pages.json",             # cache local de l'hébergeur
    ".env",
])
def test_ce_qui_appartient_a_une_instance_reste_ignore(chemin):
    assert git("check-ignore", "--no-index", chemin).strip(), (
        f"« {chemin} » n'est plus ignoré : il partirait dans le dépôt public.")


@pytest.mark.parametrize("chemin", [
    "public/src/routes/territoire/+page.svelte",   # la page, pas le périmètre
    "config/publication_rules.exemple.json",       # l'exemple livré par le moteur
    "scripts/carte_fond.py",
])
def test_le_code_du_moteur_n_est_jamais_ignore(chemin):
    assert not git("check-ignore", "--no-index", chemin).strip(), (
        f"« {chemin} » est ignoré : une règle d'instance déborde sur le moteur.")
