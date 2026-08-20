"""Une ligne de tableau n'est pas une délibération.

Les procès-verbaux contiennent des tableaux de plan de financement, et tous les
régimes de découpage finissent par couper dedans. Le 20/08/2026, la base de
Lasalle comptait 275 « actes » de cette nature, TOUS publiés, dont un en
première page du site : « 2 506,51 € TTC (TVA: 20%) ». Aucun n'avait de flux
extrait — l'information chiffrée était perdue et affichée comme une décision du
conseil municipal.

Les cas ci-dessous sont relevés tels quels dans la base.
"""
from __future__ import annotations

import pytest

from collectors.pv_parsers import _titre_plausible

# Relevés dans events.title, tous sans aucun flux financier extrait.
LIGNES_DE_TABLEAU = [
    "2 506,51 € TTC (TVA: 20%)",
    "CD30 8 800,00 €",
    "22 000,00 € FEDER 2014-2020 25 296,00 € 2,1%",
    "106 170,74 € CD30 142 570,00 € 11,8%",
    "FEDER 2021-2027 156 812,54 € 13,0%",
    "CC CACTS 20% 39 560,00 €",
    "CT/CSPS 15 000,00 € 8 146,43 € 6 853,57 €",
    "124 188,00 € HT",
    "TEL : 168,00 € TTC",
    "10 ML 150,00 € 300,00 €",
    "000,00 € TTC (TVA 20%)",
    "529 055,00 € PAM 30% 194 699,42 €",
]

# De vraies délibérations, dont certaines portent un montant.
VRAIS_ACTES = [
    "SUBVENTIONS AUX ASSOCIATIONS",
    "CHAMP CONTRE CHAMP 3 000,00 € - € (déjà versé)",
    "TRAVAUX ECOLE LE COLOMBIER – DEMANDES DE SUBVENTIONS",
    "SUBVENTION 2024 – CLUB AÏKIDO",
    "Cession de la parcelle AD180",
    "Remplacement luminaire Glycines — SMEG 2 088,76 € HT",
    "DETERMINATION DU NOMBRE DE MEMBRES SIEGEANT AU CONSEIL",
]


@pytest.mark.parametrize("titre", LIGNES_DE_TABLEAU)
def test_une_ligne_de_tableau_est_refusee(titre):
    assert not _titre_plausible(titre), f"{titre!r} accepté comme délibération"


@pytest.mark.parametrize("titre", VRAIS_ACTES)
def test_une_vraie_deliberation_passe(titre):
    assert _titre_plausible(titre), f"{titre!r} refusé à tort"


@pytest.mark.parametrize("titre", [
    "VOIRIE 2026",
    "PLU",
    "Motion",
    "TARIFS",
])
def test_un_titre_court_sans_montant_reste_intact(titre):
    """La règle ne mord que sur les titres portant un montant. Un intitulé
    laconique mais réel ne doit pas disparaître au passage."""
    assert _titre_plausible(titre)


def test_le_decoupage_ecarte_les_lignes_de_tableau():
    """Bout en bout : un PV mêlant une vraie délibération et un tableau de
    financement ne doit produire que la première."""
    from collectors.pv_parsers import deliberations

    pv = """
48/2026 : n° 4713 : TRAVAUX DE VOIRIE RUE BASSE
Le Conseil Municipal, après en avoir délibéré, approuve les travaux.
49/2026 : n° 4714 : CD30 8 800,00 €
50/2026 : n° 4715 : FEDER 2021-2027 156 812,54 € 13,0%
"""
    titres = [d["titre"] for d in deliberations(pv)]
    assert any("VOIRIE" in t for t in titres), f"vraie délibération perdue : {titres}"
    assert not [t for t in titres if "CD30" in t or "FEDER" in t], \
        f"ligne de tableau retenue : {titres}"
