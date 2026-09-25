#!/usr/bin/env bash
# Contrôle d'un site Vigie Civique EN LIGNE, avant de le partager.
#
#   scripts/verifier_ligne.sh [domaine] [depot]
#   (aussi joignable par ~/Claude/scripts/vigie_verifier_ligne.sh, lien symbolique)
#   défaut : lasalle.vigie-civique.fr  vigie-civique/moteur
#
# Ne modifie rien. Sort 1 à la première anomalie bloquante, pour être câblable
# après un déploiement. Les avertissements ne font pas échouer.
set -uo pipefail

DOM="${1:-lasalle.vigie-civique.fr}"
DEPOT="${2:-vigie-civique/moteur}"
BASE="https://$DOM"
CB="?v=$RANDOM$RANDOM"   # contourne le cache de bord : juste après un
                         # déploiement, un nœud peut encore servir l'ancienne page
ERR=0; AVERT=0

ok()    { printf "  \033[32m✓\033[0m %s\n" "$1"; }
ko()    { printf "  \033[31m✗\033[0m %s\n" "$1"; ERR=$((ERR+1)); }
avert() { printf "  \033[33m!\033[0m %s\n" "$1"; AVERT=$((AVERT+1)); }
titre() { printf "\n\033[1m%s\033[0m\n" "$1"; }

code() { curl -s -o /dev/null -m 25 -w "%{http_code}" "$1"; }
destination() { curl -s -o /dev/null -m 25 -w "%{redirect_url}" "$1"; }
corps() { curl -s -m 25 "$1"; }

# ATTENTION — ne jamais écrire `corps … | grep -q …` dans ce script.
# `grep -q` sort dès la première correspondance et ferme le tube ; curl reçoit
# un SIGPIPE, rend un code non nul, et `pipefail` le propage à tout le
# pipeline. Une correspondance TROUVÉE serait donc rapportée comme un échec —
# et pour les contrôles d'étanchéité, dont la logique est inversée, une fuite
# détectée serait annoncée « aucune trace ». On capture le corps d'abord, on
# cherche ensuite.
contient() { # $1 = texte, $2 = motif
  case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac
}

# Juste après un déploiement, les nœuds de bord de Cloudflare ne basculent pas
# tous en même temps : une requête peut rendre l'ancienne page pendant quelques
# secondes. Un contrôle qui échoue là-dessus crie au loup. On réessaie donc
# trois fois, avec un paramètre différent à chaque fois, avant de conclure.
attendre_motif() { # $1 = url, $2 = motif
  for _ in 1 2 3; do
    contient "$(corps "$1?v=$RANDOM$RANDOM")" "$2" && return 0
    sleep 4
  done
  return 1
}

titre "Adresses"
for u in "" "/qui-decide" "/argent" "/acteurs-publics" "/deliberations" "/carte" \
         "/recherche" "/methode" "/couverture" "/repliquer" \
         "/mentions-legales" "/contact"; do
  c=$(code "$BASE$u$CB")
  [ "$c" = "200" ] && ok "$BASE$u" || ko "$BASE$u → HTTP $c"
done
# Pages optionnelles : `/dossiers` et `/repliquer` n'existent que là où
# l'instance les a activées. Absentes, ce n'est pas une anomalie.
for u in "/dossiers"; do
  c=$(code "$BASE$u$CB")
  [ "$c" = "200" ] && ok "$BASE$u" || avert "$BASE$u → HTTP $c (page optionnelle)"
done

# `www` n'a de sens que sur un domaine en propre : un sous-domaine d'hébergeur
# (*.pages.dev) n'en a pas, et l'exiger faisait échouer le contrôle des sites de
# démonstration pour une raison qui n'en était pas une.
#
# ⚠️ Ce contrôle a exigé un 200 jusqu'au 01/09/2026, et c'était l'habitude de
# l'hébergeur érigée en règle : Cloudflare Pages servait le site sous les DEUX
# noms. nginx, lui, renvoie `www` vers l'apex — un seul nom canonique, ce que
# fait déjà le portail et ce que demande la balise `canonical` contrôlée plus
# bas. Le déménagement de Lasalle a donc fait échouer un contrôle sur un
# comportement MEILLEUR que celui qu'il consacrait.
#
# La propriété de fond n'est pas le code rendu, c'est OÙ MÈNE le `www` : un
# 301 vers un autre site serait un vrai défaut, un 200 et un 301 vers l'apex
# sont deux façons également correctes de répondre. On vérifie donc la
# destination, pas la forme.
# 08/09/2026 : même raisonnement, un cran plus général. Saillans et Brassac ont
# quitté Cloudflare pour `saillans.` et `brassac.vigie-civique.fr` — des
# sous-domaines, mais de NOTRE domaine cette fois. `www.saillans.vigie-civique.fr`
# n'existe pas, ne servirait à rien, et personne ne le taperait : l'exiger
# faisait échouer une publication parfaitement correcte. Le critère n'est donc
# pas « est-ce un hébergeur », c'est « y a-t-il un apex » — un nom à plus de
# deux étiquettes est déjà un sous-domaine.
etiquettes=$(echo "${DOM%.}" | tr '.' '\n' | grep -c .)
case "$DOM" in
  *.pages.dev|*.netlify.app|*.github.io)
    ok "www non applicable sur un sous-domaine d'hébergeur" ;;
  *)
  if [ "$etiquettes" -gt 2 ]; then
    ok "www non applicable sur un sous-domaine ($DOM)"
  else
    c=$(code "https://www.$DOM$CB")
    case "$c" in
      200) ok "www répond" ;;
      301|308)
        cible=$(destination "https://www.$DOM$CB")
        case "$cible" in
          "$BASE"|"$BASE"/*|"$BASE"?*) ok "www → $c vers l'apex" ;;
          *) ko "www → $c vers « $cible », qui n'est pas $BASE" ;;
        esac ;;
      *) ko "www → HTTP $c" ;;
    esac
  fi ;;
esac

titre "Fichiers de référencement"
for f in /robots.txt /sitemap.xml /llms.txt; do
  c=$(code "$BASE$f"); [ "$c" = "200" ] && ok "$f" || ko "$f → HTTP $c"
done
n=$(corps "$BASE/sitemap.xml" | grep -c "<loc>")
[ "$n" -gt 50 ] && ok "sitemap : $n URL" || ko "sitemap : $n URL seulement"
contient "$(corps "$BASE/robots.txt")" "$DOM/sitemap.xml" \
  && ok "robots.txt renvoie au sitemap du bon domaine" \
  || ko "robots.txt ne pointe pas vers $DOM"

titre "Adresse canonique"
CAN=$(corps "$BASE$CB" | grep -o '<link rel="canonical" href="[^"]*"' | head -1)
contient "$CAN" "https://$DOM/" && ok "accueil : $CAN" || ko "accueil : $CAN"
# L'ancienne adresse d'hébergeur doit désigner la nouvelle comme canonique.
PD="https://${DOM%%.fr}.pages.dev"
PD="https://$(echo "$DOM" | sed 's/\.fr$//').pages.dev"
if [ "$(code "$PD")" = "200" ]; then
  attendre_motif "$PD" "rel=\"canonical\" href=\"https://$DOM/\"" \
    && ok "$PD désigne $DOM comme canonique" \
    || ko "$PD ne désigne pas $DOM comme canonique"
fi
contient "$(corps "$BASE/qui-decide$CB")" "pages.dev" \
  && avert "une page contient encore « pages.dev »" \
  || ok "plus aucune mention de l'hébergeur dans les pages"

titre "Fraîcheur et détection de version"
V=$(corps "$BASE/_app/version.json")
contient "$V" "version" && ok "version.json servi : $V" \
  || ko "version.json absent — les onglets ouverts ne verront pas les mises à jour"
GEN=$(corps "$BASE/data/stats.json" | python3 -c "import json,sys;print(json.load(sys.stdin).get('generated_at','?'))" 2>/dev/null)
ok "snapshot publié le $GEN"

titre "Étanchéité de ce qui est servi"
# Un seul téléchargement : le fichier fait près d'un mégaoctet.
ENT=$(corps "$BASE/data/entities.json")
[ -n "$ENT" ] && ok "entities.json récupéré ($(printf %s "$ENT" | wc -c | tr -d ' ') o)" \
              || ko "entities.json vide ou injoignable"
for m in "sk-ant-" "/Users/" "X-Admin-Key" "personnes_citees" "date_naissance"; do
  if contient "$ENT" "$m"; then ko "fuite : « $m » dans entities.json"
  else ok "aucune trace de « $m »"; fi
done
for niv in probable hypothesis unverified; do
  n=$(printf %s "$ENT" | grep -o "\"confidence\":\"$niv\"" | wc -l | tr -d ' ')
  [ "$n" = "0" ] && ok "aucune entité « $niv » publiée" || ko "$n entités « $niv » publiées"
done

titre "Dépôt"
c=$(code "https://github.com/$DEPOT")
[ "$c" = "200" ] && ok "https://github.com/$DEPOT accessible sans compte" \
                 || ko "dépôt → HTTP $c (privé ?)"
contient "$(corps "$BASE/repliquer$CB")" "github.com/$DEPOT" \
  && ok "/repliquer renvoie bien au dépôt" \
  || avert "/repliquer ne cite pas github.com/$DEPOT"

titre "Résultat"
[ "$ERR" = "0" ] && printf "\033[32m✓ %s anomalie bloquante\033[0m" "$ERR" \
                 || printf "\033[31m✗ %s anomalie(s) bloquante(s)\033[0m" "$ERR"
printf ", %s avertissement(s)\n\n" "$AVERT"
exit $([ "$ERR" = "0" ] && echo 0 || echo 1)
