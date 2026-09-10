"""Une liasse d'actes se découpe au cachet du contrôle de légalité, pas au style.

Une collectivité ne publie pas toujours un procès-verbal rédigé : elle dépose
souvent la LIASSE de ses délibérations, chacune sur deux ou trois pages, à la
suite dans un seul PDF. Aucun des cinq régimes existants ne sait la découper, et
`_capitales`, qui prenait le relais, faisait un titre de chaque ligne de
mobilier — 1 035 actes sur les 39 liasses scannées de Lasalle, pour 621 réels.

Mesuré sur ces liasses, en prenant pour vérité terrain les lignes « Objet : »
que la collectivité écrit elle-même — une preuve INDÉPENDANTE du cachet :

    33 liasses portant une vérité terrain lisible
    écart au vrai nombre d'actes    AVANT : 639   (19,4 par document)
                                    APRÈS : 110   ( 3,3 par document)

Et le mouvement va dans les deux sens à la fois, ce qui est le signe qu'on a
changé de preuve et non réglé un curseur : la séance du 16/03/2022 tombe de 142
actes à 23, celle du 02/04/2025 monte de 1 à 43.

⚠️ Deux documents s'écartent PLUS qu'avant, et les deux dans le sens du
sous-comptage : la séance du 12/04/2023 rend 25 actes pour 35 réels, celle du
13/04/2022 en rend 18 pour 23. Le cachet y est illisible sur une page sur trois
— rien dans le comptage ne peut le rendre, c'est à l'océrisation de le faire.
Le régime préfère taire un acte que d'en inventer un.

⚠️ Ce que ce régime NE couvre PAS : six liasses de la même collectivité ne
portent AUCUN cachet — ce sont des extraits de registre édités avant la
télétransmission. Vérifié : « ID : », « préfecture » et « Publié » y sont
absents du document entier. Elles portent en revanche « N°73/2022 » en tête de
chaque page, que `ENTETE_NUMEROTE` ne reconnaît pas parce qu'il n'attend pas de
« N° » devant le nombre. C'est une autre piste, et un autre essai.

Sur les 135 procès-verbaux TEXTUELS de Lasalle, le régime ne change RIEN : zéro
document, zéro acte de différence. Il se refuse de lui-même là où il n'a pas sa
preuve.

Les extraits gardent la forme et les défauts des documents d'origine.
"""
from __future__ import annotations

from collectors.pv_parsers import (_actes_teletransmis, _rang_dans_la_seance,
                                   _suffixe_de_seance, deliberations)

# Le cachet tel que l'océrisation le rend sur les liasses de la Communauté de
# communes Causses Aigoual Cévennes, relevé sur les documents servis.
BANDEAU = ("DEPARTEMENT : GARD\n"
           "ARRONDISSEMENT : LE VIGAN\n"
           "ID : 030-200034601-20240529-{numero}-DE\n"
           "Délibération du Conseil\n"
           "SEANCE DU 29 MAI 2024\n")


def _page(numero: str, objet: str = "", corps: str = "") -> str:
    page = BANDEAU.format(numero=numero)
    if objet:
        page += f"Objet : {objet}\n"
    return page + (corps or "Le Conseil communautaire, après en avoir délibéré,\n")


def test_une_liasse_se_decoupe_a_chaque_changement_de_numero():
    texte = "\n".join([
        _page("107_2024", "Approbation du procès-verbal du 6 mars 2024"),
        _page("107_2024"),
        _page("108_2024", "Convention de mise à disposition de services"),
        _page("109_2024", "Tarifs de la déchèterie intercommunale"),
        _page("109_2024"),
    ])
    actes = _actes_teletransmis(texte)
    assert [a["numero_acte"] for a in actes] == ["107", "108", "109"]
    assert actes[0]["titre"] == "Approbation du procès-verbal du 6 mars 2024"
    assert actes[2]["titre"] == "Tarifs de la déchèterie intercommunale"
    assert all(a["regime"] == "actes_teletransmis" for a in actes)


def test_le_suffixe_se_compte_sur_les_numeros_distincts():
    """🔴 Le défaut qui rendait UN acte là où la séance en avait vingt-trois.

    La séance du 29/05/2024 ouvre sur une délibération dont les annexes tiennent
    trente-six pages. Comptées une à une, elles imposent « 72024 » comme fin de
    numéro la plus fréquente — c'est la fin de « 107_2024 », répétée trente-six
    fois. Le suffixe retiré, il ne restait plus « 107, 108, 109 » mais « 10, 108,
    109 » : plus aucune suite, donc plus aucun acte. Compté sur les numéros
    DISTINCTS, le suffixe redevient « 2024 ».
    """
    avec_annexes = ["107_2024"] * 36 + ["108_2024", "109_2024", "110_2024"]
    assert _suffixe_de_seance(avec_annexes) == "2024"
    assert _rang_dans_la_seance("107_2024", "2024") == 107


def test_les_chiffres_du_numero_sont_recolles():
    """L'océrisation sème des séparations qui n'existent pas.

    « 1 10_2024 » est le n° 110 de la séance, lu sur la page 46 du 29/05/2024,
    entre deux pages qui portent « 109_2024 » et « 110_2024 ». Ne garder que le
    premier groupe de chiffres en ferait le n° 1, qui casse la suite et emporte
    un acte réel avec lui.
    """
    assert _rang_dans_la_seance("1 10_2024", "2024") == 110
    assert _rang_dans_la_seance("11_1_2024", "2024") == 111
    assert _rang_dans_la_seance("D36_2025", "2025") == 36


def test_un_numero_hors_suite_est_du_bruit_et_rejoint_son_voisin():
    """Un « 29 » au milieu des quatre-vingt-dix ne crée pas une délibération.

    Relevé sur la séance du 24/05/2023 : entre deux pages du n° 92, une page
    rend « 29_2022 ». La collectivité numérote dans l'ordre ; l'océrisation, non.
    Ce qui sort de la suite croissante revient à l'acte qu'il coupait — avec son
    texte, qui n'est pas perdu.
    """
    texte = "\n".join([
        _page("92_2023", "Subvention à l'association des parents d'élèves"),
        _page("29_2022", corps="Suite de la même délibération, page abîmée.\n"),
        _page("93_2023", "Modification du tableau des effectifs"),
        _page("94_2023", "Convention avec le Département"),
    ])
    actes = _actes_teletransmis(texte)
    assert [a["numero_acte"] for a in actes] == ["92", "93", "94"]
    assert "page abîmée" in actes[0]["texte"]


def test_un_proces_verbal_de_seance_nest_pas_une_liasse():
    """Un PV est lui-même télétransmis : il porte UN cachet, et se découpe autrement.

    Sans ce garde, le régime réduisait chaque procès-verbal à une délibération
    unique et écartait les régimes qui savent le lire. Mesuré : dix documents de
    Lasalle, dont un de trente-six pages ramené à un seul acte.
    """
    texte = "\n".join([_page("PV2024_03") for _ in range(12)])
    assert _actes_teletransmis(texte) == []


def test_le_regime_se_tait_sans_cachet():
    texte = ("EXTRAIT du registre des Délibérations du Conseil\n"
             "SEANCE DU 18 MAI 2022\n"
             "Objet : Approbation du compte administratif\n")
    assert _actes_teletransmis(texte) == []


def test_la_graphie_dune_autre_collectivite():
    """Saillans numérote « 1_300622 » : le rang, puis la DATE de séance.

    Le suffixe commun n'est donc pas l'année mais la date entière, et il faut
    l'apprendre du document — l'écrire en dur pour une commune ne vaudrait que
    pour elle. C'est la leçon d'un premier lecteur écrit sur la seule graphie
    « DEL2606_02 », qui ne voyait que quatre documents sur cinquante-huit.
    """
    cachet = "ID : 026-212602890-20220630-DELIB{n}300622-DE\n"
    texte = "\n".join(
        cachet.format(n=n) + f"Objet : Délibération numéro {n}\n"
        for n in (1, 2, 3, 4, 5))
    actes = _actes_teletransmis(texte)
    assert [a["numero_acte"] for a in actes] == ["1", "2", "3", "4", "5"]


def test_le_regime_passe_avant_les_autres():
    """L'ordre est la doctrine du module : un cachet est une preuve, pas un indice.

    Sans cette priorité, `_capitales` prend la main sur les liasses scannées et
    fait un titre de chaque ligne de bandeau.
    """
    texte = "\n".join([
        _page("53_2024", "Approbation du procès-verbal"),
        _page("54_2024", "Budget primitif 2024"),
        _page("55_2024", "Tarifs communaux"),
    ])
    actes = deliberations(texte, pagine=True)
    assert [a["regime"] for a in actes] == ["actes_teletransmis"] * 3


def test_le_titre_nest_jamais_le_cachet_qui_a_servi_a_decouper():
    """Le régime coupe SUR le cachet : le repli tombait donc dessus.

    Mesuré le 10/09/2026 sur la base servie de Lasalle : 64 des 237 actes du
    régime, soit 27 %, s'appelaient du nom de leur propre ancre —
    « ID : 030-213001407-20260630-DEL2606_02-DE » — ou du timbre qui la suit,
    « REPUBLIQUE FRANÇAISE EXTRAIT DU RE D: 030 213001407-… ». Toutes ces
    lignes sont en capitales, toutes précèdent l'objet, et toutes passaient.

    Le comptage, lui, était juste : c'est la leçon de l'indicateur aveugle un
    étage plus haut — on avait mesuré COMBIEN d'actes, jamais leurs titres.
    """
    texte = "".join(_page(f"{n}_2024") for n in (41, 42, 43))
    actes = _actes_teletransmis(texte)

    assert len(actes) == 3
    for acte in actes:
        assert "ID :" not in acte["titre"]
        assert "DEPARTEMENT" not in acte["titre"]
        assert "ARRONDISSEMENT" not in acte["titre"]
    # Sans objet lisible, le repli numéroté est la bonne réponse : il avoue que
    # le découpage a trouvé l'acte sans trouver son objet.
    assert [a["titre"] for a in actes] == ["Délibération n° 41",
                                           "Délibération n° 42",
                                           "Délibération n° 43"]


def test_un_acte_ne_prend_pas_lobjet_de_son_successeur():
    """La borne à la formule de vote, et pourquoi elle n'est pas facultative.

    Quand le cachet d'une page est trop abîmé pour être lu, cette page reste
    dans l'acte PRÉCÉDENT — avec son bandeau et son objet. Sans borne, la
    recherche du titre traversait tout le corps et rapportait l'objet du
    SUIVANT : sur la liasse du 30/06/2026 de Lasalle, l'acte n° 2 s'appelait
    « TARIFS LOCAUX PROFESSIONNELS MAISON DE SANTE 2026 », qui est le n° 3.
    """
    illisible = ("REPUBLIQUE FRANÇAISE EXTRAIT DU REG 6021205 0D€L126006 037\n"
                 "DEPARTEMENT : GARD\n"
                 "Objet : Tarifs des locaux professionnels\n")
    texte = (_page("41_2024", corps="Le Conseil, après en avoir délibéré, DECIDE\n")
             + illisible
             + _page("42_2024") + _page("43_2024"))
    actes = _actes_teletransmis(texte)

    assert len(actes) == 3
    assert actes[0]["titre"] == "Délibération n° 41"
    # L'objet reste dans le TEXTE de l'acte 41 — il n'est pas perdu, seulement
    # pas promu en titre d'un acte qui n'est pas le sien.
    assert "Tarifs des locaux professionnels" in actes[0]["texte"]
