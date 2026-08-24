"""
Connecteur DematDOC — portail public d'actes, lu par son API JSON.

DematDOC équipe des dizaines d'EPCI et de communes pour la publicité légale de
leurs actes. Le portail se présente comme une application JavaScript — une page
vide pour tout lecteur HTML —, mais il repose sur une API publique, anonyme et
typée, qui rend exactement ce qu'il faut :

    GET  /api/public/doctypes                → les corbeilles publiées et leur id
    POST /api/public/get-documents/{id}      → les actes de la corbeille
    POST /api/public/get-documents-lazy      → la suite, sur une liste d'ids
    GET  {chemin du document}                → le PDF, servi tel quel

La leçon de portage vaut d'être retenue : la première question devant un site
qui « n'existe qu'une fois le JavaScript exécuté » n'est pas quel navigateur
piloter, mais ce que son interface appelle. Ici, le paquet React nommait ses
routes en clair, et il n'y a pas une ligne de Playwright dans ce fichier.

Ce qu'un portail d'actes n'est PAS
----------------------------------
**Ce n'est pas une archive.** Un acte n'y figure que le temps de son affichage
légal — deux mois sur le portail relevé le 24/08/2026, qui montrait 53 actes du
25/06 au 17/08. Ce connecteur ne peut donc pas rattraper l'historique : il
accumule ce qu'il voit, et ce qu'il voit dépend de la fréquence des passages.
Une instance qui ne le lance qu'une fois par trimestre perdra des actes, sans
que rien ne le signale — c'est une propriété de la source, pas un défaut à
corriger ici.

**Ce ne sont pas des procès-verbaux.** Le portail publie les actes un par un,
chacun avec son numéro, son objet et son type. Il n'y a rien à découper, et
c'est une bien meilleure matière qu'un PV : le numéro d'acte est déclaré par la
collectivité, là où un découpage de PDF doit le deviner. `DocumentPublie.acte`
porte ces champs, et `conseils.traiter` s'en sert au lieu des analyseurs.

⚠ **`DATEACTE` est la date de télétransmission, pas celle de la séance.**
Vérifié le 24/08/2026 sur six actes : `DE2026098` à `DE2026102` portent
`DATEACTE = 2026-06-30` et `DE2026116BIS` porte `2026-07-06`, alors que les six
viennent de la séance du **25 juin 2026** — que leur référence de contrôle de
légalité (`026-200040509-20260625-…`) et leur en-tête donnent tous deux. Ce
connecteur transmet donc `DATEACTE` comme une date de télétransmission, et la
date de séance est établie à la lecture de la pièce (cf. `pv_parsers.reference_actes`).

Déclaration dans `config/instance.json` :

    "connecteur_epci": "dematdoc",
    "pages": {
      "epci": {"portail": "https://cccps.dematdoc.eu/public/14"}
    }

L'adresse est celle que l'exploitant a sous les yeux dans son navigateur : le
`14` final est l'identifiant de la corbeille (« ACTES ComCom »). Sans lui, le
connecteur interroge la liste des corbeilles et l'affiche, plutôt que d'en
choisir une à la place de l'exploitant.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .base import Article, Connecteur, DocumentPublie, Portee

# Le portail rend tout d'un coup ; `nextDocsIds` existe pour les corbeilles
# volumineuses. Plafond dur : une API qui annonce toujours une suite ne doit pas
# pouvoir faire tourner un collecteur indéfiniment.
MAX_LOTS = 40
LOT = 100

# Types d'acte que le conseil délibère lui-même. Les décisions du Président ou
# du bureau, prises par délégation, sont des actes publics eux aussi — mais ce
# ne sont pas des délibérations, et les compter comme telles fausserait le seul
# chiffre que le site met en avant. Elles sont dénombrées et annoncées, jamais
# tues. Surchargeable par `pages.<portee>.portail_deliberations`.
DELIBERATIONS_DEFAUT = r"délibération"


class Portail:
    """Un portail DematDOC, interrogé par son API publique."""

    def __init__(self, base: str, source: str):
        self.base = (base or "").rstrip("/")
        self.source = source

    def __bool__(self) -> bool:
        return bool(self.base)

    def _appel(self, chemin: str, corps: object | None = None,
               timeout: int = 30) -> object | None:
        from ..archive import archive_fetch
        from ..config import HEADERS

        if not self.base:
            return None
        url = f"{self.base}{chemin}"
        entetes = dict(HEADERS)
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps).encode("utf-8")
            entetes["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=donnees, headers=entetes)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                archive_fetch(self.source, url, raw,
                              r.headers.get_content_type(), r.status)
                return json.loads(raw.decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  [dematdoc][erreur] {url} → {e}")
            return None

    def corbeilles(self) -> list[dict]:
        """Les corbeilles publiées : `[{id, caption, name}, …]`."""
        rendu = self._appel("/api/public/doctypes")
        return rendu if isinstance(rendu, list) else []

    def documents(self, doctype: int) -> list[dict]:
        """Tous les documents d'une corbeille, pagination comprise.

        `filters` doit être présent et non nul : l'API rend une 500 quand il
        vaut `null`, ce qui se lit comme une panne alors que c'est un refus de
        requête. Un objet vide suffit.
        """
        rendu = self._appel(f"/api/public/get-documents/{doctype}",
                            {"filters": {}, "filtersURL": None})
        if not isinstance(rendu, dict):
            return []
        sorties = list(rendu.get("documents") or [])
        suite = list(rendu.get("nextDocsIds") or [])
        lots = 0
        while suite and lots < MAX_LOTS:
            lot, suite = suite[:LOT], suite[LOT:]
            # Le corps est la LISTE d'ids elle-même, pas un objet qui l'enrobe :
            # `{"ids": […]}` rend 200 avec un seul document, donc une collecte
            # silencieusement tronquée.
            rendu = self._appel("/api/public/get-documents-lazy", lot)
            if not isinstance(rendu, dict):
                break
            sorties.extend(rendu.get("documents") or [])
            suite.extend(rendu.get("nextDocsIds") or [])
            lots += 1
        if lots >= MAX_LOTS:
            print(f"  [dematdoc] plafond de {MAX_LOTS} lots atteint sur la "
                  f"corbeille {doctype} — collecte possiblement incomplète")
        return sorties


def champs(document: dict) -> dict:
    """Les champs indexés d'un document, aplatis en `{clé: valeur affichée}`.

    L'API les rend sous la forme `{clé: {indexField: {caption, type},
    displayValue}}` : la légende est là pour l'affichage, la valeur pour nous.
    """
    sorties = {}
    for cle, valeur in (document.get("values") or {}).items():
        if isinstance(valeur, dict):
            sorties[cle] = (valeur.get("displayValue") or "").strip()
    return sorties


class ConnecteurDematDOC(Connecteur):
    """Portail d'actes DematDOC — actes publiés un par un, avec leur numéro."""

    nom = "dematdoc"

    def __init__(self):
        from ..config import PAGES
        self.pages = PAGES

    # ── configuration ────────────────────────────────────────────────────────
    def _reglage(self, portee: Portee) -> tuple[Portail | None, list[int], re.Pattern]:
        reglages = self.pages.get(portee) or {}
        adresse = (reglages.get("portail") or "").strip()
        motif = re.compile(reglages.get("portail_deliberations")
                           or DELIBERATIONS_DEFAUT, re.I)
        if not adresse:
            return None, [], motif

        parties = urllib.parse.urlsplit(adresse)
        base = f"{parties.scheme}://{parties.netloc}"
        portail = Portail(base, _domaine(base))
        doctypes = [int(n) for n in re.findall(r"/(\d+)/?$", parties.path)]
        if not doctypes:
            # Choisir une corbeille à la place de l'exploitant serait deviner ce
            # qu'il publie. On montre ce qui existe, et on s'arrête là.
            listees = ", ".join(f"{c.get('id')} = {c.get('caption')}"
                                for c in portail.corbeilles())
            print(f"  [dematdoc] aucune corbeille dans « {adresse} ». "
                  f"Disponibles : {listees or 'aucune'}.\n"
                  f"  Compléter `pages.{portee}.portail` par /public/<id>.")
        return portail, doctypes, motif

    # ── actes ────────────────────────────────────────────────────────────────
    def catalogue_pv(self, portee: Portee = "commune") -> list[DocumentPublie]:
        """Les délibérations publiées, de la plus récente à la plus ancienne.

        Un acte sans chemin de fichier n'est pas catalogué : le portail sait
        décrire une pièce qu'il ne sert pas encore, et une entrée sans PDF
        produirait une délibération sans texte ni preuve.
        """
        portail, doctypes, motif = self._reglage(portee)
        if not portail or not doctypes:
            return []

        sorties: list[DocumentPublie] = []
        ecartes: dict[str, int] = {}
        for doctype in doctypes:
            adresse_corbeille = f"{portail.base}/public/{doctype}"
            for document in portail.documents(doctype):
                v = champs(document)
                type_acte = v.get("TYPE_DACTE_ACTE") or ""
                if not motif.search(type_acte):
                    ecartes[type_acte or "(sans type)"] = \
                        ecartes.get(type_acte or "(sans type)", 0) + 1
                    continue
                chemin = document.get("bifferPath") or document.get("path") or ""
                if not chemin:
                    continue
                # `DATEACTE` est une date de télétransmission (cf. l'en-tête de
                # ce fichier) : elle sert d'ordre et de repli, pas de vérité.
                date = v.get("DATEACTE") or (document.get("createdAt") or "")[:10]
                sorties.append(DocumentPublie(
                    date=date,
                    url=f"{portail.base}{chemin}",
                    libelle=v.get("OBJET") or document.get("name") or "",
                    source=portail.source,
                    acte={
                        "numero": v.get("NUMEROACTE") or "",
                        "objet": v.get("OBJET") or "",
                        "type": type_acte,
                        "date_teletransmission": date,
                        "portail": adresse_corbeille,
                    },
                ))

        if ecartes:
            detail = ", ".join(f"{n} {t.lower()}" for t, n in sorted(ecartes.items()))
            print(f"  [dematdoc] {sum(ecartes.values())} acte(s) hors conseil "
                  f"non catalogués : {detail}")
        sorties.sort(key=lambda d: d.date, reverse=True)
        return sorties

    # ── ce que ce portail ne publie pas ──────────────────────────────────────
    def articles(self, portee: Portee = "commune",
                 depuis: str | None = None) -> list[Article]:
        """Aucun : un portail d'actes ne publie pas de vie locale.

        Rendre une liste vide plutôt que de lever : une instance dont l'EPCI
        n'expose que ses actes est un cas ordinaire, pas une erreur de
        configuration.
        """
        return []


def _domaine(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.removeprefix("www.")


CONNECTEUR = ConnecteurDematDOC
