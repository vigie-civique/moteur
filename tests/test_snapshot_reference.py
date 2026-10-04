"""Le builder produit, sur la base de la CI, exactement le snapshot de référence.

La référence (`tests/fixtures/snapshot_reference/`) a été construite depuis
`main` avant que `build_snapshot()` soit découpé en étapes. Tant que ce test
passe, le découpage n'a déplacé que du code : pas un filtre, pas un ordre de
tri, pas une forme de JSON.

Il ne prouve que ce que la base de la CI exerce — six entités, huit actes, un
dossier. Les tables qu'elle ne porte pas (télécoms, eau, déchets, marchés,
flux…) sortent vides des deux côtés : pour elles, la preuve se joue sur les
bases des instances, avec le même comparateur.

Régénérer la référence quand la sortie DOIT changer : cf.
`tests/snapshot_reference.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from snapshot_reference import REFERENCE, ROOT, construire, horloge_de_reference  # noqa: E402

from scripts.comparer_snapshots import comparer_snapshots, lignes_du_rapport  # noqa: E402


def test_le_snapshot_de_la_base_de_ci_est_celui_de_reference(tmp_path):
    out = construire(ROOT, tmp_path, horloge_de_reference())
    rapport = comparer_snapshots(REFERENCE, out)
    assert rapport["identiques"], "\n" + "\n".join(lignes_du_rapport(rapport))
