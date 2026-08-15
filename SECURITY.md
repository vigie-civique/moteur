# Signaler un problème

## Une donnée publiée à tort

Si vous constatez sur un site produit par ce dispositif une donnée qui vous
concerne et qui n'a pas à y figurer, écrivez à l'adresse de contact indiquée sur
ce site (page « Mentions légales »). Toute rectification est appliquée puis
**signalée comme telle** : la donnée collectée est conservée à côté de la
rectification, jamais remplacée en silence.

Les personnes physiques ne figurent sur un site public qu'au titre d'une
fonction publique, d'un mandat électif ou d'une responsabilité inscrite dans un
registre public. Si ce n'est pas votre cas, c'est un défaut du filtre, et il
sera traité comme tel — pas comme une demande de retrait ordinaire.

## Une faille dans le code

Les défauts les plus graves de ce dispositif ne sont pas des failles
d'exécution : ce sont des fuites du filtre de publication. Si vous en trouvez
une, **ne la démontrez pas sur un site en ligne** et ne l'ouvrez pas en issue
publique. Passez par un signalement privé (bouton « Report a vulnerability » de
l'onglet Security), en décrivant le chemin.

Sont particulièrement concernés :

- une donnée `probable` ou `hypothesis` atteignant un site public ;
- une entité hors périmètre publiée comme si elle était de la commune ;
- un fichier d'instance ou une base entrant dans l'archive distribuable ;
- une route de l'atelier accessible sans jeton.

## Ce qui n'en est pas une

L'atelier sert la base de travail non filtrée : c'est **voulu**, et c'est
pourquoi `deploy/README.md` recommande de ne pas l'exposer. Un atelier accessible
publiquement est une erreur de déploiement, pas une faille du moteur.
