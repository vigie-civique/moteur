"""Ce que la forme juridique INSEE dit du type d'une entité.

`nature_juridique` (catégorie juridique, niveau III) est publiée par SIRENE sur
chaque unité légale, et le collecteur la stockait déjà dans
`businesses.legal_form_code` — sans jamais s'en servir pour typer l'entité.
Tout entrait donc en base comme « entreprise » : associations loi 1901,
communes, préfectures et trésoreries comprises.

Ce n'est pas un détail d'affichage. Une commune ne peut pas subventionner une
entreprise : présenter une association subventionnée comme telle contredit
l'acte qu'on publie à côté. Et comme l'index unique porte sur `(type, name)`,
la même structure collectée par le RNA ressortait en DOUBLE, un exemplaire par
type — ou pire, restait seule et mal classée quand le RNA ne l'avait pas.

La correspondance ne couvre QUE les familles où le code suffit à trancher. Tout
le reste garde « business », qui est le sens de SIRENE par défaut :

  71-74  personnes morales de droit public — administration de l'État,
         collectivité territoriale, établissement public administratif.
  92     associations de la loi de 1901 (déclarée, non déclarée, reconnue
         d'utilité publique, de droit local).

Volontairement absentes, faute d'évidence :
  91  syndicats de copropriétaires et associations syndicales libres — ce sont
      des groupements de propriétaires, ni entreprise ni association loi 1901 ;
  93  fondations — proches des associations, mais la publication les traite
      autrement ; à trancher avec une vraie fiche, pas par un préfixe.
"""

# Préfixe de deux chiffres → (type d'entité, libellé lisible de la famille)
FAMILLES: dict[str, tuple[str, str]] = {
    "71": ("service", "administration de l'État"),
    "72": ("service", "collectivité territoriale"),
    "73": ("service", "établissement public administratif"),
    "74": ("service", "autre personne morale de droit public administratif"),
    "92": ("association", "association loi 1901"),
}

TYPE_PAR_DEFAUT = "business"


def type_pour_forme(code: str | None) -> str:
    """Type d'entité qu'impose la forme juridique, `business` si elle ne dit rien."""
    if not code:
        return TYPE_PAR_DEFAUT
    return FAMILLES.get(str(code)[:2], (TYPE_PAR_DEFAUT, ""))[0]


def libelle_famille(code: str | None) -> str:
    """Libellé de la famille juridique, vide si elle n'est pas dans la table."""
    if not code:
        return ""
    return FAMILLES.get(str(code)[:2], ("", ""))[1]
