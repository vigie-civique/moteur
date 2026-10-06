"""Un seul build du site à la fois, quel que soit le chemin qui le lance.

Le 04/10/2026, sur l'atelier de Lasalle, un « Mettre en ligne » parti pendant la
construction d'un aperçu a montré les deux visages du même défaut :

- la mise en ligne a échoué — `ENOTEMPTY … public/.svelte-kit/output/prerendered/
  pages/entite` ;
- l'aperçu est sorti tronqué, 88 pages sur 1 528, sans `_app/immutable`, donc
  servi sans feuille de style ni JavaScript — et `verifier_build.mjs` a annoncé
  « ✓ 72 pages vérifiées ».

L'aperçu (`publication.construire_apercu`) et la mise en ligne
(`deploy/publier-site.sh`) lancent le même `npm run build`, qui vide puis
remplit `public/.svelte-kit/output`. Seuls les aperçus prenaient un verrou.

Le premier essai lance les DEUX chemins pour de bon, en deux processus, dans une
copie du moteur. Seul `npm` est remplacé, par un script qui fait de
`.svelte-kit/output` l'usage qu'en fait le vrai build — vider, écrire page à
page, relire — et qui échoue s'il y trouve les pages d'un autre. C'est le
partage du répertoire qui est éprouvé, pas SvelteKit : sur le vrai build, deux
lancements décalés de quatre secondes donnent `ENOENT … output/server/
manifest-full.js` (relevé joint à la PR).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GARDE = ROOT / "public" / "scripts" / "verifier_build.mjs"
SCRIPT = (ROOT / "deploy" / "publier-site.sh").read_text(encoding="utf-8")
PAGES = 30

# Le build, réduit à ce qui a cassé : un répertoire de travail commun, vidé au
# départ, rempli page à page, recopié à la fin. Chaque page porte le numéro du
# processus qui l'a écrite.
FAUX_NPM = textwrap.dedent(f"""\
    #!/usr/bin/env bash
    set -u
    travail=.svelte-kit/output/prerendered/pages
    rm -rf .svelte-kit/output
    for i in $(seq 1 {PAGES}); do
      mkdir -p "$travail" && echo "$$" > "$travail/$i.html" || exit 1
      sleep 0.1
    done
    miennes=$(grep -lx "$$" "$travail"/*.html 2>/dev/null | wc -l | tr -d ' ')
    if [ "$miennes" -ne {PAGES} ]; then
      echo "build tronqué : $miennes pages sur {PAGES} sont les miennes" >&2
      exit 1
    fi
    sortie="${{VIGIE_BUILD_DIR:-build}}"
    mkdir -p "$sortie" && cp "$travail"/*.html "$sortie"/ && echo accueil > "$sortie/index.html"
    """)

APERCU = textwrap.dedent("""\
    import json, sys
    sys.path.insert(0, sys.argv[1])
    from scripts import publication as p
    p.BROUILLON.mkdir(parents=True, exist_ok=True)
    (p.BROUILLON / "stats.json").write_text("{}")
    p.ETAT.parent.mkdir(parents=True, exist_ok=True)
    p.ETAT.write_text(json.dumps({"brouillon": {
        "complet": True, "repertoire": str(p.BROUILLON.resolve())}}))
    try:
        p.construire_apercu()
    except p.PublicationRefusee as e:
        sys.exit(f"aperçu refusé : {e.message} {e.detail}")
    """)


@pytest.fixture
def moteur(tmp_path):
    """Une copie du moteur où `ROOT` est jetable : le script et `publication.py`
    déduisent leur racine de leur propre emplacement."""
    racine = tmp_path / "moteur"
    for dossier in ("scripts", "collectors", "deploy"):
        shutil.copytree(ROOT / dossier, racine / dossier,
                        ignore=shutil.ignore_patterns("__pycache__"))
    # Ce que les deux chemins exigent avant de construire : des dépendances
    # installées, une version promue, et où écrire les libellés du site.
    (racine / "public" / "node_modules" / ".bin").mkdir(parents=True)
    (racine / "public" / "node_modules" / ".bin" / "vite").write_text("")
    (racine / "public" / "src" / "lib").mkdir(parents=True)
    (racine / "public" / "static" / "data").mkdir(parents=True)
    (racine / "public" / "static" / "data" / "version.json").write_text("{}")
    outils = tmp_path / "outils"
    outils.mkdir()
    (outils / "npm").write_text(FAUX_NPM)
    (outils / "npm").chmod(0o755)
    env = {**os.environ, "PATH": f"{outils}{os.pathsep}{os.environ['PATH']}",
           "PY": sys.executable}
    return racine, env


def _attendre(condition, delai: float = 30.0) -> None:
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin, "le premier build n'a jamais commencé"
        time.sleep(0.05)


def test_un_apercu_et_une_mise_en_ligne_lances_ensemble_aboutissent_tous_les_deux(moteur):
    """Le défaut du 04/10/2026, rejoué : l'aperçu construit, la mise en ligne
    part. Avant, le second build vidait le répertoire du premier — l'un des deux
    au moins sortait en échec. Maintenant le second attend, et le DIT."""
    racine, env = moteur
    travail = racine / "public" / ".svelte-kit" / "output" / "prerendered" / "pages"

    apercu = subprocess.Popen([sys.executable, "-c", APERCU, str(racine)],
                              cwd=str(racine), env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    _attendre(lambda: (travail / "1.html").is_file())
    en_ligne = subprocess.run(
        ["bash", str(racine / "deploy" / "publier-site.sh"), "--deja-promu"],
        cwd=str(racine), env=env, text=True, timeout=120,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    sortie_apercu, _ = apercu.communicate(timeout=120)

    assert apercu.returncode == 0, f"l'aperçu a échoué :\n{sortie_apercu}"
    assert en_ligne.returncode == 0, f"la mise en ligne a échoué :\n{en_ligne.stdout}"
    for build in (racine / "audits" / "apercu_build", racine / "public" / "build"):
        auteurs = {p.read_text().strip() for p in build.glob("[0-9]*.html")}
        assert len(list(build.glob("[0-9]*.html"))) == PAGES and len(auteurs) == 1, \
            f"{build.name} mêle les pages de deux builds : {auteurs}"
    # Celui qui attend le dit à l'écran, et nomme qui il attend.
    assert "un aperçu construit déjà le site" in en_ligne.stdout, en_ligne.stdout
    assert "la mise en ligne attend son tour" in en_ligne.stdout
    assert en_ligne.stdout.index("attend son tour") < en_ligne.stdout.index("3/5")


def test_la_mise_en_ligne_qui_n_obtient_pas_le_site_echoue_en_le_disant(moteur):
    """Un verrou tenu trop longtemps n'est pas une attente infinie : la mise en
    ligne sort en échec, dit qui elle attendait, et n'a rien construit."""
    racine, env = moteur
    verrou = racine / "audits" / "apercu-build.lock"
    verrou.parent.mkdir(parents=True)
    tenir = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""\
        import fcntl, json, sys, time
        f = open(sys.argv[1], "a+")
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"qui": "un aperçu", "genre": "apercu"})); f.flush()
        print("tenu", flush=True); time.sleep(60)
        """), str(verrou)], stdout=subprocess.PIPE, text=True)
    try:
        assert tenir.stdout.readline().strip() == "tenu"
        r = subprocess.run(
            [sys.executable, str(racine / "scripts" / "publication.py"),
             "verrou-de-build", "--fd", "9", "--delai", "1.5"],
            cwd=str(racine), env=env, text=True, capture_output=True,
            pass_fds=(9,), preexec_fn=lambda: os.dup2(
                os.open(verrou, os.O_WRONLY | os.O_APPEND), 9))
    finally:
        tenir.kill()
    assert r.returncode == 1
    assert "un aperçu construit déjà le site" in r.stdout
    assert "n'a pas eu son tour" in r.stderr and "Rien n'a été construit" in r.stderr
    assert not (racine / "public" / "build").exists()


# ── Le verrou, de près ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def publication():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "publication_un_build", ROOT / "scripts" / "publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def verrou(publication, tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "VERROU_BUILD", tmp_path / "audits" / "build.lock")
    return publication.VERROU_BUILD


def test_personne_ne_construit_tant_que_le_verrou_est_libre(publication, verrou):
    assert publication.build_en_cours() is None        # le fichier n'existe pas
    with publication._verrou_de_build("un aperçu", genre="apercu"):
        pass
    # Le fichier garde le nom du dernier build : il n'est cru que verrou TENU.
    assert "un aperçu" in verrou.read_text(encoding="utf-8")
    assert publication.build_en_cours() is None


def test_celui_qui_construit_est_nomme_a_qui_regarde(publication, verrou):
    with publication._verrou_de_build("un aperçu", genre="apercu"):
        tenant = publication.build_en_cours()
        assert tenant["qui"] == "un aperçu" and tenant["genre"] == "apercu"
        assert tenant["depuis"]
        # C'est ce que la page Publication lit pour griser « Mettre en ligne ».
        assert publication.etat_mise_en_ligne()["build"]["genre"] == "apercu"
    assert publication.etat_mise_en_ligne()["build"] is None


def test_un_second_build_attend_le_dit_puis_passe(publication, verrou):
    dit, ordre = [], []

    def second():
        with publication._verrou_de_build("la mise en ligne", genre="mise_en_ligne",
                                          delai=20, dire=dit.append):
            ordre.append("second")

    with publication._verrou_de_build("un aperçu", genre="apercu"):
        fil = threading.Thread(target=second)
        fil.start()
        time.sleep(1.8)                # au-delà de la seconde où il se tait
        ordre.append("premier")
    fil.join(timeout=20)
    assert ordre == ["premier", "second"]
    assert len(dit) == 2, dit
    assert "un aperçu construit déjà le site" in dit[0] and "attend son tour" in dit[0]
    assert "la mise en ligne commence" in dit[1]


def test_un_build_qui_n_attend_pas_ne_dit_rien(publication, verrou):
    dit = []
    with publication._verrou_de_build("un aperçu", dire=dit.append):
        pass
    assert dit == []


def test_un_apercu_qui_attend_trop_refuse_en_nommant_qui_tient_le_site(publication, verrou):
    with publication._verrou_de_build("la mise en ligne", genre="mise_en_ligne"):
        with pytest.raises(publication.PublicationRefusee) as refus:
            with publication._verrou_de_build("un aperçu", delai=0.6):
                pytest.fail("deux builds tiennent le site en même temps")
    assert "la mise en ligne construit le site" in refus.value.message


def test_le_verrou_d_un_build_tue_est_rendu(publication, verrou):
    """`flock`, pas un témoin sur disque : le noyau rend le verrou d'un processus
    mort. Un build tué ne doit pas griser « Mettre en ligne » pour toujours."""
    verrou.parent.mkdir(parents=True)
    tenir = subprocess.Popen([sys.executable, "-c",
                              "import fcntl,sys,time; f=open(sys.argv[1],'a+'); "
                              "fcntl.flock(f, fcntl.LOCK_EX); print('tenu', flush=True); "
                              "time.sleep(60)", str(verrou)],
                             stdout=subprocess.PIPE, text=True)
    assert tenir.stdout.readline().strip() == "tenu"
    assert publication.build_en_cours() is not None
    tenir.kill()
    tenir.wait()
    assert publication.build_en_cours() is None


# ── Le script et la page : des décisions, relues dans le texte ───────────────

def test_le_script_prend_le_verrou_avant_tout_ce_qu_il_ecrit_dans_public():
    """Le verrou couvre la régénération des libellés (`src/lib/instance.js`, lu
    par un aperçu en construction), le build, et la copie de `public/build`."""
    prise = SCRIPT.index('"$PUBLICATION" verrou-de-build --fd 9 ||')
    assert prise < SCRIPT.index("generer_libelles.py") \
        < SCRIPT.index("&& npm run build )")
    assert SCRIPT.index("rsync -rlpt") < SCRIPT.rindex("\nrendre_le_site") \
        < SCRIPT.index('"$PUBLICATION" verifier')
    # Le chemin du verrou n'est écrit qu'une fois, dans publication.py.
    assert "apercu-build.lock" not in SCRIPT and "flock " not in SCRIPT


def test_ssh_n_herite_pas_du_verrou():
    """Un maître de connexion ssh persistant garderait le descripteur — donc le
    verrou — bien après la fin du script."""
    ligne = next(l for l in SCRIPT.splitlines() if '"$VIGIE_CIBLE_HOTE:' in l)
    assert ligne.rstrip().endswith("9>&-"), ligne


def test_la_page_n_offre_pas_la_mise_en_ligne_pendant_un_apercu():
    page = (ROOT / "dashboard" / "src" / "routes" / "atelier" / "publication"
            / "+page.svelte").read_text(encoding="utf-8")
    bouton = page[page.index("on:click={mettreEnLigne}"):]
    bouton = bouton[:bouton.index("</button>")]
    assert "serveurEnCours" in bouton and "apercuEnConstruction" in bouton
    assert "deploiement.build?.genre === 'apercu'" in page
    # La raison est écrite à côté du bouton grisé, pas seulement dans le code.
    assert "« Mettre en ligne » attend : un aperçu se construit" in page


# ── Un build incomplet est refusé ────────────────────────────────────────────

PAGE = "<html><body>" + "<p>contenu réel de la page</p>" * 400 + "</body></html>"
ACCUEIL = ('<html><head><link href="./_app/immutable/assets/0.css" rel="stylesheet">'
           '<link rel="modulepreload" href="./_app/immutable/entry/start.js">'
           '<link rel="canonical" href="https://exemple.test/"></head><body>'
           + "<p>contenu réel de la page</p>" * 400
           + '<script>import("./_app/immutable/entry/start.js")</script></body></html>')


def _build(racine: Path, fiches: int) -> Path:
    build = racine / "build"
    for nom in ("assets/0.css", "entry/start.js"):
        f = build / "_app" / "immutable" / nom
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("/* */")
    (build / "index.html").write_text(ACCUEIL, encoding="utf-8")
    (build / "entite").mkdir()
    for i in range(fiches):
        (build / "entite" / f"{i}.html").write_text(PAGE, encoding="utf-8")
    return build


def _snapshot(racine: Path, fiches: int | None) -> Path:
    donnees = racine / "donnees"
    donnees.mkdir()
    if fiches is not None:
        (donnees / "manifeste.json").write_text(json.dumps({"fichiers": [
            {"chemin": "entity_index.json", "objets": fiches},
            {"chemin": "stats.json", "objets": 1}]}))
    return donnees


def _verifier(build: Path, donnees: Path):
    return subprocess.run(["node", str(GARDE)], cwd=str(build.parent),
                          env={**os.environ, "VIGIE_BUILD_DIR": str(build),
                               "VIGIE_DATA_DIR": str(donnees)},
                          capture_output=True, text=True)


avec_node = pytest.mark.skipif(shutil.which("node") is None, reason="node absent")


@avec_node
def test_un_build_entier_passe_et_dit_ce_qu_il_a_compte(tmp_path):
    r = _verifier(_build(tmp_path, 12), _snapshot(tmp_path, 12))
    assert r.returncode == 0, r.stderr
    assert "12 fiches pour 12 annoncées" in r.stdout


@avec_node
def test_un_build_sans_app_immutable_est_refuse(tmp_path):
    """Le 04/10/2026 : 72 pages pleines, aucune feuille de style, et un « ✓ »."""
    build = _build(tmp_path, 12)
    shutil.rmtree(build / "_app" / "immutable")
    r = _verifier(build, _snapshot(tmp_path, 12))
    assert r.returncode == 1 and "_app/immutable est absent" in r.stderr, r.stderr
    assert "✓" not in r.stdout


@avec_node
def test_une_ressource_de_l_accueil_qui_manque_est_refusee(tmp_path):
    build = _build(tmp_path, 12)
    (build / "_app" / "immutable" / "assets" / "0.css").unlink()
    r = _verifier(build, _snapshot(tmp_path, 12))
    assert r.returncode == 1, r.stdout
    assert "index.html référence ./_app/immutable/assets/0.css" in r.stderr
    # Ce qui est ailleurs que sur le site n'est pas cherché sur le disque.
    assert "exemple.test" not in r.stderr


@avec_node
def test_moins_de_fiches_que_le_manifeste_n_en_annonce_est_refuse(tmp_path):
    r = _verifier(_build(tmp_path, 12), _snapshot(tmp_path, 1528))
    assert r.returncode == 1, r.stdout
    assert "12 fiches sur les 1528 qu'annonce le manifeste" in r.stderr


@avec_node
def test_sans_manifeste_le_compte_non_fait_est_annonce(tmp_path):
    """Un dépôt sans données se construit : le contrôle qui n'a pas pu se faire
    le dit, il ne s'affiche pas en vert."""
    r = _verifier(_build(tmp_path, 12), _snapshot(tmp_path, None))
    assert r.returncode == 0, r.stderr
    assert "nombre de pages NON contrôlé" in r.stdout
