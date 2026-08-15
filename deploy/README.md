# Mettre en ligne

Le dispositif a deux moitiés, et une seule est faite pour être publique.

| | **Site public** | **Atelier** |
|---|---|---|
| Ce qu'il sert | le snapshot filtré : ce qui a été jugé publiable | la base de travail entière, non filtrée |
| Qui y accède | tout le monde | les personnes qui tiennent l'instance |
| Où il tourne | un hébergeur de fichiers statiques | un serveur, ou nulle part |
| Ce qu'il coûte | quelques euros par an, souvent rien | un serveur, un domaine, du TLS, de la vigilance |
| Obligatoire ? | c'est l'objet du dispositif | **non** |

La base de collecte, elle, ne quitte jamais la machine sur laquelle elle est
construite. Aucune des deux moitiés ne la sert.

---

## 1. Le site public

Il est **statique** : pas de backend, pas de base en ligne, pas de clé d'API.
Les données sont figées au build, chaque page lit le snapshot dans son
`+page.server.js`. Un hébergeur de fichiers suffit, et rien ne peut fuiter par
une requête qu'on n'avait pas prévue — il n'y a pas de requête.

```bash
./deploy/publier-site.sh
```

Trois étapes, dans cet ordre, et chacune peut refuser :

1. **le snapshot** — s'arrête si `entities.perimetre` n'a jamais été renseignée.
   Sans ce classement, le site publierait l'intercommunalité entière à la place
   de la commune. Le message dit quoi lancer ;
2. **les invariants** (`scripts/verify_snapshot.py`) — un contrôle écrit comme
   un adversaire, qui n'importe pas le builder et attaque le répertoire publié :
   confidences privées, relations hors liste, coordonnées de personnes, secrets,
   chemins locaux, et part de la commune dans ce qui est publié. **Une violation
   interrompt la publication** ;
3. **le build** — `npm run build` échoue si une page est livrée sans son
   contenu (`public/scripts/verifier_build.mjs`).

Le résultat est dans `public/build/` : un site statique ordinaire, à téléverser
où vous voulez. Le script sait pousser vers Cloudflare Pages, qui a l'avantage
d'un palier gratuit et d'un déploiement par téléversement direct :

```bash
npx wrangler login                                    # une fois
CF_PROJECT=vigie-civique-macommune ./deploy/publier-site.sh --deployer
```

Pour Netlify, GitHub Pages, ou un `rsync` vers un hébergeur classique : rien à
changer avant la dernière étape, le dossier `build/` se dépose tel quel.

> **Pourquoi pas l'intégration git de l'hébergeur ?** Parce que `static/data/`
> n'est pas versionné — et ne doit pas l'être. L'hébergeur ne verrait qu'un site
> sans données. Le téléversement direct est ce qui permet de garder le dépôt
> propre.

### Mise à jour

Recollecter, puis republier :

```bash
python3 -m collectors.run_all      # le dernier step reclasse le périmètre
./deploy/publier-site.sh --deployer
```

Une fois par mois suffit pour la plupart des sources ; `/couverture` affiche la
fraîcheur réelle de chacune, telle que `collector_runs` l'enregistre.

---

## 2. L'atelier, et pourquoi vous n'en avez peut-être pas besoin

L'atelier est l'interface d'édition : corriger un nom, valider un site web
trouvé automatiquement, annoter une délibération, rejeter une piste. Il parle à
une API FastAPI qui lit et écrit **la base de travail**.

Cette base contient ce que le site public écarte : des personnes physiques sans
rôle civique, des pistes non établies, des liens de famille, des adresses. Le
filtre de publication existe précisément pour que rien de tout cela ne sorte.
**Mettre l'atelier en ligne, c'est mettre en ligne ce que le filtre retient.**

D'où trois options, par ordre de prudence :

**a) Ne pas le déployer du tout.** Lancez-le en local, sur la machine qui porte
la base, le temps d'une session de travail :

```bash
uvicorn api:app --port 8765          # dans un terminal
cd dashboard && npm run dev          # dans un autre
```

Rien n'est exposé, il n'y a ni secret à gérer ni serveur à tenir. C'est le mode
par défaut, et il convient tant qu'une seule personne tient l'instance.

**b) Le déployer derrière un accès restreint** — VPN, réseau local, ou
authentification HTTP en amont de nginx. À plusieurs sur un même réseau.

**c) Le déployer sur l'internet public**, avec TLS et comptes nommés. C'est
utile quand plusieurs personnes contribuent depuis des lieux différents. C'est
aussi ce qui demande le plus de rigueur, et ce n'est pas une décision technique :
c'est une décision sur qui a accès à des données qu'on a choisi de ne pas
publier.

### Si vous choisissez (c)

Prérequis : un serveur, Python 3.11+, node, nginx, certbot, un sous-domaine.

```bash
# a) Code et environnement — le venv se crée SUR LE SERVEUR
sudo mkdir -p /opt/vigie && sudo chown vigie: /opt/vigie
git clone <votre dépôt> /opt/vigie && cd /opt/vigie
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# b) Configuration de l'instance et secrets
#    config/instance.json n'est pas versionné : le recopier, ou réamorcer.
cp deploy/env.exemple .env && chmod 600 .env
#    → remplir JWT_SECRET, ALLOWED_ORIGINS ; ADMIN_KEY seulement si un script
#      appelle l'API sans session humaine.

# c) La base : la copier depuis la machine de collecte (scp). Ne pas la versionner.

# d) Libellés et front de l'atelier
python3 scripts/generer_libelles.py            # écrit les deux instance.js
cd dashboard && npm install && npm run build   # → dist/

# e) Service
sudo cp deploy/atelier.service /etc/systemd/system/vigie-atelier.service
sudo systemctl daemon-reload && sudo systemctl enable --now vigie-atelier

# f) nginx et TLS
sudo cp deploy/nginx-atelier.conf /etc/nginx/sites-available/vigie-atelier
sudo ln -s /etc/nginx/sites-available/vigie-atelier /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d atelier.example.org

# g) Un compte
python3 scripts/create_user.py add --email vous@exemple.org --role admin
```

Ce que le dispositif fait déjà pour vous, et qu'il ne faut pas défaire :

- **l'API refuse par défaut.** Toute route `/api/` sans jeton valide répond 401.
  Ce n'est pas une liste de routes protégées, c'est l'inverse : une liste de
  routes ouvertes, qui tient en une ligne (`/api/auth/`) ;
- **`ALLOWED_ORIGINS` n'a pas de valeur permissive par défaut.** Sans lui, seuls
  les ports de développement local sont acceptés — l'atelier en ligne ne
  fonctionne pas tant qu'on ne l'a pas renseigné. Une page cassée vaut mieux
  qu'une API ouverte ;
- **l'API n'écoute que sur `127.0.0.1`.** nginx termine le TLS et proxifie ;
- **les secrets sont dans `.env`, pas dans l'unité systemd**, qui est lisible
  par tous les comptes de la machine.

Ce que le dispositif ne fait PAS pour vous :

- **les sauvegardes de la base.** Un serveur qui porte la seule copie d'une base
  de collecte est un accident en attente ;
- **la journalisation des accès** au-delà de celle de nginx ;
- **la mise à jour du serveur.** Un atelier en ligne est une machine à tenir.

---

## 3. Ce qu'il faut avoir réglé avant la première publication

- **Les mentions légales.** `config/instance.json`, clé `editeur` : nom,
  statut, courriel, hébergeur. `scripts/generer_libelles.py` liste ce qui
  manque à chaque exécution, et la page `/mentions-legales` affiche ce qu'il
  trouve. En France, un site public sans éditeur identifiable n'est pas en règle.
- **Les règles de publication** (`config/publication_rules.json`) relues, y
  compris la note de licence : elle est copiée depuis l'exemple et décrit le jeu
  de données de l'instance d'origine tant que personne ne l'a réécrite.
- **Un canal de rectification.** Le dispositif documente des personnes au titre
  d'une fonction ; il leur doit une adresse où écrire, et une correction
  appliquée puis signalée comme telle.
