-- ============================================================
-- Vigie Civique — schéma SQLite
-- Une base par instance ; la commune est déclarée dans config/instance.json
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------
-- ENTITÉS — table centrale : personnes, entreprises, associations,
--            services, lieux, propriétés
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL CHECK(type IN (
                    'person','business','association',
                    'service','place','property')),
    name        TEXT NOT NULL,
    short_name  TEXT,
    lat         REAL,
    lng         REAL,
    address     TEXT,
    -- AUCUN défaut : une entité dont on ignore la commune vaut NULL, et le
    -- classement de périmètre la traitera comme telle. Le schéma a porté
    -- `DEFAULT 'Lasalle'` jusqu'au 12/08/2026 — une entité sans commune
    -- naissait donc lasalloise, et comme le tag n'est jamais écrasé, la
    -- corriger après coup ne faisait rien. Trois incidents en sont sortis.
    commune     TEXT,
    confidence  TEXT DEFAULT 'verified'
                     CHECK(confidence IN ('verified','confirmed','probable','hypothesis')),
    -- Renseignées par le géocodeur et par scripts/classer_perimetre.py. Elles
    -- manquaient au schéma publié alors que le script de publication les
    -- interroge : sur une base neuve, la publication échouait sans que rien
    -- n'indique laquelle des deux moitiés était en retard sur l'autre.
    geocode_source TEXT,
    perimetre   TEXT CHECK(perimetre IN ('C1','C2','C3','lien','hors')),
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    -- Nom normalisé (minuscules, sans accents, séparateurs unifiés) : sert à
    -- retrouver une entité malgré une variante d'écriture. Renseignée par
    -- `db.upsert_entity`. Une colonne GÉNÉRÉE a été essayée le 12/08/2026 puis
    -- abandonnée — l'expression SQL de dépliage des accents fait déborder le
    -- parseur de SQLite et rendait la base illisible (cf. nom_normalise.py).
    name_norm   TEXT,

    -- ── Colonnes que le CODE utilisait sans que le SCHÉMA les déclare ───────
    -- Elles existaient dans la base historique et n'avaient jamais été
    -- reportées ici. Toute instance créée par le moteur naissait donc sans
    -- elles, et la file de revue de l'atelier — sa page principale — échouait
    -- sur « no such column: validation_status ». Constaté le 20/08/2026 sur
    -- Lasalle-v3, Saillans et Brassac-v2 : les trois. Seule l'instance dont la
    -- base venait de la production fonctionnait, ce qui masquait le défaut.
    validation_status TEXT DEFAULT 'unverified',
    responsible       TEXT,
    -- Coordonnées projetées (Lambert-93) et qualité du géocodage.
    x_l93             REAL,
    y_l93             REAL,
    geocode_score     REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_name_type
    ON entities(type, name);

-- NON UNIQUE, volontairement. Un unique sur (type, name_norm) confondrait des
-- entités homonymes légitimes : « CENTRE COMMUNAL D'ACTION SOCIALE (CCAS) »
-- porte le même nom dans deux communes voisines (deux SIREN distincts)
-- (263000994). C'est `db.upsert_entity` qui arbitre, en exigeant la même
-- commune avant de réutiliser une fiche.
CREATE INDEX IF NOT EXISTS idx_entities_name_norm
    ON entities(type, name_norm);

-- Trigger updated_at automatique sur entities
CREATE TRIGGER IF NOT EXISTS entities_updated_at
    AFTER UPDATE ON entities
BEGIN
    UPDATE entities SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- ----------------------------------------------------------------
-- PERSONNES (extends entities where type='person')
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persons (
    entity_id   INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    firstname   TEXT,
    lastname    TEXT,
    birth_year  INTEGER,
    birth_month INTEGER,
    gender      TEXT
);

CREATE INDEX IF NOT EXISTS idx_persons_name
    ON persons(lastname, firstname);

-- ----------------------------------------------------------------
-- ENTREPRISES (extends entities where type='business')
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS businesses (
    entity_id       INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    siren           TEXT UNIQUE,
    -- Réponse brute de Pappers et date de récupération (collecteur facultatif).
    pappers_fetched_at TEXT,
    pappers_raw        TEXT,
    siret_siege     TEXT,
    naf_code        TEXT,
    naf_label       TEXT,
    legal_form_code TEXT,
    legal_form      TEXT,
    status          TEXT,   -- 'A' actif, 'F' fermé
    capital         INTEGER,
    employees_range TEXT,
    creation_date   TEXT,
    closing_date    TEXT,
    raw_data        TEXT    -- JSON blob source
);

CREATE INDEX IF NOT EXISTS idx_businesses_siren  ON businesses(siren);
CREATE INDEX IF NOT EXISTS idx_businesses_naf    ON businesses(naf_code);
CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);

-- ----------------------------------------------------------------
-- ASSOCIATIONS (extends entities where type='association')
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS associations (
    entity_id        INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    rna_id           TEXT UNIQUE,
    -- Une association peut être immatriculée au répertoire des entreprises.
    siren            TEXT,
    waldec_id        TEXT,
    object           TEXT,
    status           TEXT,
    creation_date    TEXT,
    dissolution_date TEXT,
    raw_data         TEXT    -- JSON blob source
);

CREATE INDEX IF NOT EXISTS idx_associations_rna ON associations(rna_id);

-- ----------------------------------------------------------------
-- SERVICES PUBLICS (extends entities where type='service')
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS services (
    entity_id       INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    category        TEXT,   -- 'santé','éducation','transport','admin','culture','sécurité'
    finess_id       TEXT,
    operator        TEXT,
    opening_hours   TEXT
);

-- ----------------------------------------------------------------
-- LIEUX / POIs (extends entities where type='place')
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS places (
    entity_id       INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    osm_id          INTEGER,
    osm_category    TEXT,   -- amenity, tourism, shop, historic...
    osm_value       TEXT,   -- restaurant, hotel, school...
    tags            TEXT    -- JSON blob des tags OSM
);

CREATE INDEX IF NOT EXISTS idx_places_osm ON places(osm_id);

-- ----------------------------------------------------------------
-- TRANSACTIONS IMMOBILIÈRES (DVF)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dvf_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    insee           TEXT,   -- code commune : les sections cadastrales se répètent
    date            TEXT,
    cadastre_ref    TEXT,   -- ex: "AD0180"
    section         TEXT,
    numero          TEXT,
    lieu_dit        TEXT,
    nature_mutation TEXT,   -- Vente, Echange, Adjudication...
    nature_bien     TEXT,   -- terrain nu, maison, appartement...
    surface_terrain REAL,
    surface_bati    REAL,
    price           INTEGER,
    price_per_m2    REAL,
    lat             REAL,
    lng             REAL,
    year            INTEGER GENERATED ALWAYS AS (CAST(substr(date,1,4) AS INTEGER)) VIRTUAL
);

CREATE INDEX IF NOT EXISTS idx_dvf_date     ON dvf_transactions(date);
CREATE INDEX IF NOT EXISTS idx_dvf_cadastre ON dvf_transactions(cadastre_ref);
CREATE INDEX IF NOT EXISTS idx_dvf_year     ON dvf_transactions(year);
-- Clé naturelle anti-doublon : rend les ré-imports idempotents (INSERT OR IGNORE).
-- Une mutation = plusieurs lignes (parcelles/cultures) distinguées par cadastre+nature+surfaces.
-- `insee` fait partie de la clé depuis le 11/08/2026 : les références cadastrales
-- (0A0002, AC0394…) se répètent d'une commune à l'autre, et sans le code commune
-- deux mutations de communes différentes s'écrasaient silencieusement.
-- Les COALESCE sont indispensables : SQLite considère deux NULL comme distincts,
-- donc un terrain nu (surface_bati NULL) échappait entièrement à la contrainte
-- et se réinsérait à chaque collecte — 293 doublons sur 632 lignes constatés le
-- 11/08/2026, même cause que les 8 exemplaires de la cession AD180.
CREATE UNIQUE INDEX IF NOT EXISTS ux_dvf_dedup
    ON dvf_transactions(insee, date, cadastre_ref, nature_bien,
                        COALESCE(surface_terrain, -1),
                        COALESCE(surface_bati, -1),
                        COALESCE(price, -1));

-- ----------------------------------------------------------------
-- COMPÉTENCES INTERCOMMUNALES (périmètre C2)
-- Ce que l'EPCI exerce à la place de la commune. Sans cette table, on ne sait
-- pas quelles décisions ont quitté le conseil municipal — c'est la définition
-- opérationnelle du périmètre C2. Source : BANATIC (collectors/banatic.py).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS epci_competences (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    epci_siren            TEXT NOT NULL,
    code                  TEXT NOT NULL,   -- nomenclature BANATIC, ex "1510"
    libelle               TEXT,
    categorie             TEXT,
    obligatoire           INTEGER,         -- 1 = compétence obligatoire
    interet_communautaire INTEGER,
    source                TEXT,
    collected_at          TEXT DEFAULT (datetime('now')),
    UNIQUE (epci_siren, code)
);

-- ----------------------------------------------------------------
-- RELATIONS — graphe entre entités
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_id           INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    -- dirigeant | associé | gérant | président | trésorier | secrétaire | membre
    -- élu_cm | élu_cc | candidat
    -- locataire_commune | bailleur_commune | subventionné | prestataire
    -- proche_présumé | époux_présumé | enfant_présumé | famille_présumé
    -- même_adresse | même_lieu_dit
    since           TEXT,
    until           TEXT,
    source          TEXT,   -- sirene | rna | cm | dvf | press | profile | manual
    confidence      TEXT DEFAULT 'verified'
                         CHECK(confidence IN ('verified','confirmed','probable','hypothesis')),
    metadata        TEXT,   -- JSON
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(from_id, to_id, relation_type, source)
);

CREATE INDEX IF NOT EXISTS idx_rel_from   ON relations(from_id);
CREATE INDEX IF NOT EXISTS idx_rel_to     ON relations(to_id);
CREATE INDEX IF NOT EXISTS idx_rel_type   ON relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source);

-- ----------------------------------------------------------------
-- ÉVÉNEMENTS — délibérations, transactions, articles, arrêtés
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    -- deliberation | transaction | article | arrete | registration | dissolution
    date        TEXT,
    title       TEXT,
    content     TEXT,
    source      TEXT,
    source_url  TEXT,
    metadata    TEXT,   -- JSON (montant, vote_pour, vote_contre, vote_abstention...)
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_type_date ON events(type, date);

-- Liens événement ↔ entité
CREATE TABLE IF NOT EXISTS event_entities (
    event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    role        TEXT,   -- sujet | mentionné | votant | déportant | acheteur | vendeur | bénéficiaire
    PRIMARY KEY (event_id, entity_id, role)
);

CREATE INDEX IF NOT EXISTS idx_ee_entity ON event_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_ee_event  ON event_entities(event_id);

-- ----------------------------------------------------------------
-- FLUX FINANCIERS — subventions, baux, marchés
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_flows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT,   -- subvention | bail | marché | aide_facade | fonds_concours
    year        INTEGER,
    amount      INTEGER,
    from_id     INTEGER REFERENCES entities(id),  -- commune ou État
    to_id       INTEGER REFERENCES entities(id),  -- bénéficiaire
    event_id    INTEGER REFERENCES events(id),
    description TEXT,
    source      TEXT,
    confidence  TEXT DEFAULT 'verified',
    -- Colonnes attendues par build_public_snapshot.py :
    --   perimetre  'detail' (par défaut) ou 'agregat' — un agrégat OFGL englobe
    --              des flux détaillés, les additionner double le total ;
    --   statut     'realise' (par défaut) ou 'demande' — une subvention
    --              sollicitée n'est pas une subvention obtenue ;
    --   type_norm  type ramené à une famille, pour les regroupements publics.
    perimetre   TEXT DEFAULT 'detail' CHECK(perimetre IN ('detail','agregat')),
    statut      TEXT DEFAULT 'realise' CHECK(statut IN ('realise','demande')),
    type_norm   TEXT
);

CREATE INDEX IF NOT EXISTS idx_flows_year    ON financial_flows(year);
CREATE INDEX IF NOT EXISTS idx_flows_to      ON financial_flows(to_id);
CREATE INDEX IF NOT EXISTS idx_flows_type    ON financial_flows(type);

-- ----------------------------------------------------------------
-- ANNOTATIONS — revue des données importées (délibs / flux / marchés)
-- Couche d'annotation séparée : ne jamais écraser les données sources.
-- object_type ∈ (deliberation, flow, marche) ; object_id = id dans sa table.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS annotations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type   TEXT    NOT NULL,           -- deliberation | flow | marche
    object_id     INTEGER NOT NULL,
    review_status TEXT    NOT NULL DEFAULT 'pending',  -- pending | validated | rejected
    confidence    TEXT,                        -- verified | confirmed | probable | hypothesis
    note          TEXT,
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    -- Corrections de champs posées dans l'atelier, en JSON. `charger_revue()`
    -- les lit derrière un garde (`if "corrections" in colonnes`) : sans la
    -- colonne, corriger un chiffre dans l'atelier ne laissait aucune trace, en
    -- silence. Le garde reste, il protège les bases anciennes.
    corrections   TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(object_type, object_id)
);
CREATE INDEX IF NOT EXISTS idx_annotations_obj ON annotations(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_annotations_status ON annotations(object_type, review_status);

-- ----------------------------------------------------------------
-- COLLECTOR_RUNS — journal de la loop de collecte auto-pilotée
-- (fraîcheur des sources : scripts/collect_loop.py)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collector_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collector    TEXT NOT NULL,
    started_at   TEXT DEFAULT (datetime('now')),
    finished_at  TEXT,
    status       TEXT,              -- ok | empty | error | timeout
    items_before INTEGER,
    items_after  INTEGER,
    items_added  INTEGER,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_collector_runs ON collector_runs(collector, finished_at DESC);

-- ----------------------------------------------------------------
-- FEED DE MONITORING — nouvelles données détectées
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feed_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT,
    type            TEXT,
    title           TEXT NOT NULL,
    content         TEXT,
    url             TEXT,
    is_alert        INTEGER DEFAULT 0,
    alert_level     TEXT DEFAULT 'info',  -- info | warning | critical
    entity_ids      TEXT,   -- JSON array
    published_at    TEXT,
    detected_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feed_alert     ON feed_items(is_alert, alert_level);
CREATE INDEX IF NOT EXISTS idx_feed_published ON feed_items(published_at DESC);

-- ----------------------------------------------------------------
-- FTS — recherche plein texte sur les entités
-- ----------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    short_name,
    address,
    content='entities',
    content_rowid='id'
);

-- Triggers FTS sync
CREATE TRIGGER IF NOT EXISTS entities_fts_insert
    AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, short_name, address)
    VALUES (new.id, new.name, new.short_name, new.address);
END;

CREATE TRIGGER IF NOT EXISTS entities_fts_update
    AFTER UPDATE ON entities BEGIN
    UPDATE entities_fts
    SET name=new.name, short_name=new.short_name, address=new.address
    WHERE rowid=new.id;
END;

CREATE TRIGGER IF NOT EXISTS entities_fts_delete
    AFTER DELETE ON entities BEGIN
    DELETE FROM entities_fts WHERE rowid=old.id;
END;

-- ----------------------------------------------------------------
-- FTS — recherche plein texte sur les événements et CR PDF
-- ----------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title,
    content,
    source,
    metadata,
    content='events',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS events_fts_insert
    AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, content, source, metadata)
    VALUES (new.id, new.title, new.content, new.source, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_update
    AFTER UPDATE ON events BEGIN
    UPDATE events_fts
    SET title=new.title,
        content=new.content,
        source=new.source,
        metadata=new.metadata
    WHERE rowid=new.id;
END;

CREATE TRIGGER IF NOT EXISTS events_fts_delete
    AFTER DELETE ON events BEGIN
    DELETE FROM events_fts WHERE rowid=old.id;
END;

-- ----------------------------------------------------------------
-- ARCHIVE BRUTE — conservation de toute source récupérée (re-parsable)
-- ----------------------------------------------------------------
-- Chaque page/PDF/JSON scrapé est conservé tel quel sur disque (data/raw/<source>/)
-- et indexé ici. Dédup par sha256 : une source inchangée n'est pas redupliquée,
-- seul last_seen est mis à jour. Permet de re-parser même si la source disparaît
-- (un site de mairie ne garde souvent que le dernier compte rendu en ligne).
CREATE TABLE IF NOT EXISTS raw_documents (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,                       -- domaine du site officiel | prefecture-NN | boamp | ...
    url         TEXT,                                -- URL d'origine (NULL si PDF déposé)
    doc_type    TEXT,                                -- html | pdf | json | csv | txt
    sha256      TEXT NOT NULL UNIQUE,                -- empreinte du contenu (dédup)
    byte_size   INTEGER,
    local_path  TEXT NOT NULL,                       -- chemin relatif sous data/raw/
    http_status INTEGER,
    title       TEXT,
    fetched_at  TEXT DEFAULT (datetime('now')),      -- 1ère capture
    last_seen   TEXT DEFAULT (datetime('now')),      -- dernière fois re-rencontré identique
    metadata    TEXT,
    parse_status   TEXT DEFAULT 'pending',           -- pending | ok | failed
    parsed_at      TEXT,                             -- dernier reparse (scripts/reparse.py)
    parser         TEXT,                             -- nom du handler de parse
    parser_version TEXT                              -- version du handler (re-parse si bump)
);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_documents(source);
CREATE INDEX IF NOT EXISTS idx_raw_url    ON raw_documents(url);

-- ----------------------------------------------------------------
-- VUES UTILES
-- ----------------------------------------------------------------

-- Vue : entités géolocalisées (pour la carte)
CREATE VIEW IF NOT EXISTS v_geo_entities AS
SELECT
    e.id, e.type, e.name, e.short_name,
    e.lat, e.lng, e.address, e.confidence,
    b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
    a.rna_id, a.object AS asso_object,
    p.osm_category, p.osm_value,
    s.category AS service_category
FROM entities e
LEFT JOIN businesses   b ON b.entity_id = e.id
LEFT JOIN associations a ON a.entity_id = e.id
LEFT JOIN places       p ON p.entity_id = e.id
LEFT JOIN services     s ON s.entity_id = e.id
WHERE e.lat IS NOT NULL AND e.lng IS NOT NULL;

-- Vue : graphe de relations avec noms
CREATE VIEW IF NOT EXISTS v_relations AS
SELECT
    r.id, r.relation_type, r.since, r.until,
    r.source, r.confidence,
    f.id AS from_id, f.type AS from_type, f.name AS from_name,
    t.id AS to_id, t.type AS to_type, t.name AS to_name
FROM relations r
JOIN entities f ON f.id = r.from_id
JOIN entities t ON t.id = r.to_id;

-- Vue : flux financiers annuels par bénéficiaire
CREATE VIEW IF NOT EXISTS v_flows_summary AS
SELECT
    ff.type, ff.year, ff.amount,
    e_to.name AS beneficiary,
    e_to.type AS beneficiary_type,
    ff.description, ff.source
FROM financial_flows ff
JOIN entities e_to ON e_to.id = ff.to_id
ORDER BY ff.year DESC, ff.amount DESC;

-- ----------------------------------------------------------------
-- CANDIDATS DE RELATIONS — liens détectés automatiquement,
-- en attente de validation manuelle avant insertion dans relations
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relation_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_id           INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    -- famille_présumé | même_adresse | même_lieu_dit | doublon_probable | même_personne_probable
    confidence      TEXT NOT NULL CHECK(confidence IN ('probable','hypothesis')),
    signal          TEXT NOT NULL,
    -- maiden_name | same_full_name | same_address | toponym | entity_duplicate
    -- same_surname | subsidy_entity_match
    signal_detail   TEXT,           -- description lisible du signal détecté
    score           INTEGER NOT NULL DEFAULT 0,  -- 0-100 (confiance algorithmique)
    review_status   TEXT DEFAULT 'pending'
                         CHECK(review_status IN ('pending','accepted','rejected','ignored')),
    reviewed_at     TEXT,
    review_note     TEXT,
    locked_by       TEXT,           -- claim queue : email/id du valideur en cours
    locked_at       TEXT,           -- timestamp du claim (expiration côté API : 10 min)
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(from_id, to_id, relation_type, signal)
);

CREATE INDEX IF NOT EXISTS idx_cand_status ON relation_candidates(review_status);
CREATE INDEX IF NOT EXISTS idx_cand_score  ON relation_candidates(score DESC);
CREATE INDEX IF NOT EXISTS idx_cand_from   ON relation_candidates(from_id);
CREATE INDEX IF NOT EXISTS idx_cand_to     ON relation_candidates(to_id);

-- ----------------------------------------------------------------
-- MARCHÉS PUBLICS — table structurée (DECP + BOAMP + CC CAC)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marches_publics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    acheteur_id     INTEGER REFERENCES entities(id),
    acheteur_siren  TEXT NOT NULL,
    acheteur_nom    TEXT NOT NULL,
    titulaire_id    INTEGER REFERENCES entities(id),
    titulaire_siren TEXT,
    titulaire_nom   TEXT,
    objet           TEXT NOT NULL,
    nature          TEXT,
    procedure       TEXT,
    montant         REAL,
    cpv             TEXT,
    cpv_label       TEXT,
    date_notif      TEXT,
    date_pub        TEXT,
    duree_mois      INTEGER,
    lieu_exec       TEXT,
    source          TEXT NOT NULL,
    source_url      TEXT,
    raw_id          TEXT,
    event_id        INTEGER REFERENCES events(id),
    -- `probable` quand l'acheteur n'a pas pu être établi : le BOAMP laisse le
    -- nom de l'acheteur en saisie libre, et une correspondance approximative ne
    -- suffit pas à affirmer qui a passé un marché. Ces lignes restent en base
    -- et attendent un arbitrage dans l'atelier ; le snapshot ne publie que
    -- `verified` et `confirmed`.
    confidence      TEXT DEFAULT 'verified'
                    CHECK(confidence IN ('verified','confirmed','probable','hypothesis')),
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(raw_id)
);

CREATE INDEX IF NOT EXISTS idx_mp_acheteur ON marches_publics(acheteur_siren);
CREATE INDEX IF NOT EXISTS idx_mp_titulaire ON marches_publics(titulaire_siren);
CREATE INDEX IF NOT EXISTS idx_mp_date ON marches_publics(date_notif DESC);
CREATE INDEX IF NOT EXISTS idx_mp_montant ON marches_publics(montant DESC);

-- ----------------------------------------------------------------
-- APPROBATIONS DE PROJETS — plans de financement votés
-- La commune approuve un projet et sa participation à une opération portée
-- par un syndicat (électrification, éclairage public). Aucune entreprise n'est
-- retenue : ce n'est pas un marché, mais c'est de l'argent public engagé.
-- Table distincte, précisément pour ne pas gonfler les marchés attribués.
CREATE TABLE IF NOT EXISTS approbations_projets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       INTEGER REFERENCES events(id),
    date           TEXT,
    objet          TEXT NOT NULL,
    montant_ht     REAL,
    montant_ttc    REAL,
    maitre_ouvrage TEXT,
    citation       TEXT,
    source         TEXT,
    source_url     TEXT,
    raw_id         TEXT UNIQUE,
    confidence     TEXT DEFAULT 'verified',
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_approb_date ON approbations_projets(date DESC);

-- ----------------------------------------------------------------
-- BUDGETS ANNEXES — régies et budgets annexes municipaux
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budget_annexe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    year            INTEGER NOT NULL,
    section         TEXT NOT NULL CHECK(section IN ('fonctionnement','investissement','dette')),
    sens            TEXT NOT NULL CHECK(sens IN ('depense','recette','solde')),
    compte          TEXT,
    libelle         TEXT NOT NULL,
    montant         REAL NOT NULL,
    source          TEXT NOT NULL,
    source_event_id INTEGER REFERENCES events(id),
    confidence      TEXT DEFAULT 'verified' CHECK(confidence IN ('verified','probable','hypothesis')),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_budget_annexe_entity_year ON budget_annexe(entity_id, year);
CREATE INDEX IF NOT EXISTS idx_budget_annexe_year        ON budget_annexe(year);

-- ----------------------------------------------------------------
-- SITES WEB ENTITÉS — catalogue des URLs avec statut de validation
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_websites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'candidate'
                         CHECK(status IN ('candidate','validated','broken','rejected')),
    score           REAL,
    found_by        TEXT NOT NULL DEFAULT 'manual',
    last_check      TEXT,
    http_status     INTEGER,
    last_scraped    TEXT,
    locked_by       TEXT,           -- claim queue : email/id du valideur en cours
    locked_at       TEXT,           -- timestamp du claim (expiration côté API : 10 min)
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(entity_id, url)
);

CREATE INDEX IF NOT EXISTS idx_entity_websites_entity ON entity_websites(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_websites_status ON entity_websites(status);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id    INTEGER REFERENCES entities(id),
    url          TEXT NOT NULL,
    started_at   TEXT DEFAULT (datetime('now')),
    finished_at  TEXT,
    http_status  INTEGER,
    content_hash TEXT,
    items_found  INTEGER DEFAULT 0,
    source       TEXT DEFAULT 'web_scraper'
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_entity ON scrape_runs(entity_id);

-- Notes par entité (IA, Gemma 4, manuel)
CREATE TABLE IF NOT EXISTS entity_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    date        TEXT,
    note        TEXT NOT NULL,
    source      TEXT DEFAULT 'manual',   -- 'manual'|'gemma'|'web_scraper'|'pappers'
    confidence  TEXT DEFAULT 'unverified'
                     CHECK(confidence IN ('unverified','verified','confirmed','probable','hypothesis')),
    updated_at  TEXT DEFAULT (datetime('now')),
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_notes_entity ON entity_notes(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_notes_confidence ON entity_notes(confidence);

CREATE TRIGGER IF NOT EXISTS entity_notes_updated_at
    AFTER UPDATE ON entity_notes
BEGIN
    UPDATE entity_notes SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Embeddings pour RAG (Sprint G)
CREATE TABLE IF NOT EXISTS embeddings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT    NOT NULL,
    source_id    INTEGER NOT NULL,
    entity_id    INTEGER REFERENCES entities(id),
    chunk_text   TEXT    NOT NULL,
    vector       BLOB    NOT NULL,
    created_at   TEXT    DEFAULT (datetime('now')),
    UNIQUE(source_table, source_id)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_entity ON embeddings(entity_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_table, source_id);

-- Vue : stats globales
CREATE VIEW IF NOT EXISTS v_stats AS
SELECT
    (SELECT COUNT(*) FROM entities WHERE type='person')      AS persons,
    (SELECT COUNT(*) FROM entities WHERE type='business')    AS businesses,
    (SELECT COUNT(*) FROM entities WHERE type='association') AS associations,
    (SELECT COUNT(*) FROM entities WHERE type='service')     AS services,
    (SELECT COUNT(*) FROM entities WHERE type='place')       AS places,
    (SELECT COUNT(*) FROM relations)                          AS relations,
    (SELECT COUNT(*) FROM events)                             AS events,
    (SELECT COUNT(*) FROM dvf_transactions)                   AS dvf_transactions,
    (SELECT COUNT(*) FROM financial_flows)                    AS financial_flows,
    (SELECT COUNT(*) FROM entities WHERE lat IS NOT NULL)     AS geolocated;

-- ================================================================
-- VUES D'ANALYSE CROISÉE (Sprint F)
-- ================================================================

-- Personnes avec ≥2 rôles publics distincts
DROP VIEW IF EXISTS v_mandats_croises;
CREATE VIEW v_mandats_croises AS
SELECT
    p.id            AS person_id,
    p.name          AS person_name,
    pr.firstname,
    pr.lastname,
    COUNT(DISTINCT r.relation_type)                 AS nb_roles,
    GROUP_CONCAT(DISTINCT r.relation_type)          AS roles,
    COUNT(DISTINCT CASE WHEN r.relation_type IN ('élu_cm','élu_cc','candidat','adjoint')
                        THEN r.id END)              AS nb_mandats_elus,
    COUNT(DISTINCT CASE WHEN r.relation_type IN ('dirigeant','gérant','président','associé')
                        THEN r.id END)              AS nb_mandats_prives
FROM entities p
JOIN persons pr ON pr.entity_id = p.id
JOIN relations r ON (r.from_id = p.id OR r.to_id = p.id)
WHERE p.type = 'person'
  AND r.relation_type IN (
      'élu_cm','élu_cc','candidat','adjoint',
      'dirigeant','gérant','président','associé',
      'agent_communal','membre_commission','responsable'
  )
GROUP BY p.id
HAVING nb_roles >= 2
ORDER BY nb_roles DESC, nb_mandats_elus DESC;

-- Conflits potentiels : élu CM/CC qui dirige/gère une entité ayant flux financiers avec la commune
-- Précision chronologique : date exacte via events.date quand event_id renseigné, sinon année seule
DROP VIEW IF EXISTS v_conflits_potentiels;
CREATE VIEW v_conflits_potentiels AS
SELECT DISTINCT
    p.id             AS person_id,
    p.name           AS person_name,
    r1.relation_type AS role_elu,
    r1.since         AS mandat_debut,
    r1.until         AS mandat_fin,
    e2.id            AS entite_id,
    e2.name          AS entite_nom,
    e2.type          AS entite_type,
    r2.relation_type AS role_entite,
    r2.since         AS role_entite_debut,
    ff.id            AS flux_id,
    ff.type          AS flux_type,
    ff.amount        AS flux_montant,
    ff.year          AS flux_annee,
    ev.date          AS flux_date,
    ff.source        AS flux_source,
    CASE
        WHEN ff.id IS NULL THEN 'lien_sans_flux'
        WHEN r1.since IS NULL AND r1.until IS NULL THEN 'dates_manquantes'
        -- Date exacte disponible via l'événement : comparaison jour/mois/an
        WHEN ev.date IS NOT NULL AND r1.until IS NOT NULL AND ev.date > r1.until THEN 'hors_mandat'
        WHEN ev.date IS NOT NULL AND r1.since IS NOT NULL AND ev.date < r1.since THEN 'anterieur_mandat'
        WHEN ev.date IS NOT NULL THEN 'contemporain'
        -- Seulement l'année : hors_mandat / anterieur_mandat clairs
        WHEN r1.until IS NOT NULL AND CAST(SUBSTR(r1.until,1,4) AS INTEGER) < ff.year THEN 'hors_mandat'
        WHEN r1.since IS NOT NULL AND CAST(SUBSTR(r1.since,1,4) AS INTEGER) > ff.year THEN 'anterieur_mandat'
        -- Année de flux = année de début ou fin de mandat : ambiguïté, impossible sans date exacte
        WHEN (r1.until IS NOT NULL AND CAST(SUBSTR(r1.until,1,4) AS INTEGER) = ff.year)
          OR (r1.since IS NOT NULL AND CAST(SUBSTR(r1.since,1,4) AS INTEGER) = ff.year)
             THEN 'chevauchement_annee'
        ELSE 'contemporain'
    END              AS chronologie
FROM entities p
JOIN relations r1 ON (r1.from_id = p.id OR r1.to_id = p.id)
    AND r1.relation_type IN ('élu_cm','élu_cc','adjoint','maire','candidat')
JOIN relations r2 ON (r2.from_id = p.id OR r2.to_id = p.id)
    AND r2.relation_type IN ('dirigeant','gérant','président','associé')
JOIN entities e2 ON e2.id = CASE WHEN r2.from_id = p.id THEN r2.to_id ELSE r2.from_id END
    AND e2.type IN ('business','association')
LEFT JOIN financial_flows ff ON (ff.to_id = e2.id OR ff.from_id = e2.id)
    AND ff.type IN ('subvention','subvention_demandee','marche_public','marché',
                    'DETR_demande','DSIL_demande','Fonds_Vert_demande','subvention_region')
LEFT JOIN events ev ON ev.id = ff.event_id
WHERE p.type = 'person'
ORDER BY
    CASE chronologie
        WHEN 'contemporain'      THEN 0
        WHEN 'chevauchement_annee' THEN 1
        WHEN 'lien_sans_flux'    THEN 2
        WHEN 'dates_manquantes'  THEN 3
        ELSE 4
    END,
    ff.amount DESC NULLS LAST,
    p.name;

-- Subventions par bénéficiaire (totaux consolidés)
DROP VIEW IF EXISTS v_subventions_beneficiaires;
CREATE VIEW v_subventions_beneficiaires AS
SELECT
    e.id            AS entity_id,
    e.name          AS entity_name,
    e.type          AS entity_type,
    ff.type         AS flux_type,
    COUNT(*)        AS nb_flux,
    SUM(ff.amount)  AS total_montant,
    MIN(ff.year)    AS annee_debut,
    MAX(ff.year)    AS annee_fin,
    GROUP_CONCAT(DISTINCT ff.source) AS sources
FROM financial_flows ff
JOIN entities e ON e.id = ff.to_id
WHERE ff.type IN ('subvention','subvention_demandee','subvention_region',
                  'DETR_demande','DSIL_demande','Fonds_Vert_demande','FPIC')
GROUP BY e.id, ff.type
ORDER BY total_montant DESC NULLS LAST;

-- Marchés par titulaire
DROP VIEW IF EXISTS v_marches_attributaires;
CREATE VIEW v_marches_attributaires AS
SELECT
    mp.titulaire_nom,
    mp.titulaire_siren,
    et.id           AS entity_id,
    et.name         AS entity_name,
    COUNT(*)        AS nb_marches,
    SUM(mp.montant) AS total_montant,
    MIN(mp.date_notif) AS premier_marche,
    MAX(mp.date_notif) AS dernier_marche,
    GROUP_CONCAT(DISTINCT mp.nature)         AS types_marches
FROM marches_publics mp
LEFT JOIN entities et ON et.id = mp.titulaire_id
GROUP BY mp.titulaire_nom, mp.titulaire_siren
ORDER BY total_montant DESC NULLS LAST;

-- Adresses partagées (≥3 entités non-personnes à la même adresse hors adresse vague)
DROP VIEW IF EXISTS v_adresses_partagees;
CREATE VIEW v_adresses_partagees AS
SELECT
    e.address,
    COUNT(*)                            AS nb_entites,
    SUM(CASE WHEN e.type='business'    THEN 1 ELSE 0 END) AS nb_biz,
    SUM(CASE WHEN e.type='association' THEN 1 ELSE 0 END) AS nb_asso,
    GROUP_CONCAT(e.id)                  AS entity_ids,
    GROUP_CONCAT(e.name, ' | ')         AS entity_names
FROM entities e
WHERE e.address IS NOT NULL
  -- Adresses non exploitables : le remplissage par défaut de la source
  -- (« [ND] […] ») et une adresse réduite au code postal et à la commune,
  -- qui ne localise rien.
  AND e.address NOT LIKE '%[ND]%'
  AND e.address NOT GLOB '[0-9][0-9][0-9][0-9][0-9] *'
  AND e.address != ''
  AND e.type IN ('business','association','service')
GROUP BY e.address
HAVING nb_entites >= 3
ORDER BY nb_entites DESC;

-- Familles potentielles (≥2 personnes avec même nom de famille)
DROP VIEW IF EXISTS v_familles_potentielles;
CREATE VIEW v_familles_potentielles AS
SELECT
    pr.lastname,
    COUNT(*)                            AS nb_personnes,
    GROUP_CONCAT(e.id)                  AS person_ids,
    GROUP_CONCAT(e.name, ' | ')         AS person_names
FROM persons pr
JOIN entities e ON e.id = pr.entity_id
WHERE pr.lastname IS NOT NULL AND pr.lastname != ''
GROUP BY pr.lastname
HAVING nb_personnes >= 2
ORDER BY nb_personnes DESC, pr.lastname;

-- ================================================================
-- TABLES CRÉÉES PAR SCRIPTS DE MIGRATION (réalignées ici — session 22)
-- Objectif : schema.sql doit reconstruire une DB structurellement complète.
-- ================================================================

-- ----------------------------------------------------------------
-- Auth atelier (scripts/migrate_sprint1.py)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'validator'
                        CHECK(role IN ('admin','validator','contributor')),
    totp_secret     TEXT,
    failed_attempts INTEGER DEFAULT 0,
    locked_until    TEXT,
    last_login      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    revoked_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id),
    entity_id   INTEGER REFERENCES entities(id),
    table_name  TEXT,
    action      TEXT NOT NULL,
    field       TEXT,
    old_value   TEXT,
    new_value   TEXT,
    ip_hash     TEXT,
    at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_user   ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_at     ON audit_log(at DESC);

CREATE TABLE IF NOT EXISTS atelier_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),
    body        TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_comments_entity ON atelier_comments(entity_id);

-- ----------------------------------------------------------------
-- Alertes publiques (atelier)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT,
    severity    TEXT DEFAULT 'info',
    lat         REAL,
    lng         REAL,
    starts_at   TEXT,
    expires_at  TEXT,
    created_by  INTEGER REFERENCES users(id),
    published   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------
-- Contacts entités (site web / tél / email — atelier)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type       TEXT NOT NULL CHECK(type IN ('website','phone','email','other')),
    value      TEXT NOT NULL,
    label      TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_contacts_entity ON contacts(entity_id);

-- ----------------------------------------------------------------
-- Enrichissement web/social (collectors/url_finder.py, enrich loop)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_enrichment (
    entity_id     INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    last_checked  TEXT,
    web_done      INTEGER DEFAULT 0,
    social_done   INTEGER DEFAULT 0,
    sites_found   INTEGER DEFAULT 0,
    socials_found INTEGER DEFAULT 0,
    error         TEXT
);

-- ----------------------------------------------------------------
-- BUDGET VOTÉ — les chiffres tels que le conseil les a votés, relevés dans les
-- procès-verbaux. À distinguer des agrégats DGFiP/OFGL, qui sont l'exécution
-- constatée après coup : les deux diffèrent, et le site les affiche côte à côte.
--
-- Cette table manquait au schéma alors que le script de publication produit
-- `budget_vote.json` et que le site en a une page. Une instance créée par le
-- moteur ne l'avait donc pas, et la page naissait vide sans rien dire.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budget_vote (
    id              INTEGER PRIMARY KEY,
    year            INTEGER NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'principal',  -- 'principal' ou budget annexe
    agregat         TEXT NOT NULL,
    value           REAL,
    unit            TEXT NOT NULL DEFAULT 'EUR',        -- EUR | pct | annees
    approx          INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    source          TEXT,
    source_event_id INTEGER,
    source_url      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(year, scope, agregat)
);

-- ----------------------------------------------------------------
-- Finances — budget DGFiP / OFGL / dotations DGCL
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budget_annuel (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL,
    categorie   TEXT NOT NULL,
    compte      TEXT NOT NULL,
    libelle     TEXT,
    montant     REAL,
    source      TEXT DEFAULT 'dgfip',
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(year, compte, categorie)
);

CREATE TABLE IF NOT EXISTS budget_indicators (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    agregat TEXT NOT NULL,
    year    INTEGER NOT NULL,
    value   REAL,
    source  TEXT DEFAULT 'OFGL',
    entity_id INTEGER REFERENCES entities(id),
    UNIQUE(agregat, year)
);

CREATE TABLE IF NOT EXISTS ofgl_agregats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    year                INTEGER NOT NULL,
    agregat             TEXT NOT NULL,
    montant             REAL,
    euros_par_habitant  REAL,
    population          INTEGER,
    tranche_population  TEXT,
    rural               TEXT,
    source              TEXT DEFAULT 'ofgl',
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(year, agregat)
);

CREATE TABLE IF NOT EXISTS dotations_etat (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL,
    insee       TEXT NOT NULL,
    commune     TEXT,
    composante  TEXT NOT NULL,
    montant     REAL,
    source      TEXT DEFAULT 'DGCL',
    raw_label   TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(year, insee, composante)
);

-- ----------------------------------------------------------------
-- INSEE Melodi (collectors/insee_social.py)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insee_indicateurs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    insee       TEXT NOT NULL,
    commune     TEXT,
    dataset     TEXT NOT NULL,
    indicateur  TEXT NOT NULL,
    libelle     TEXT,
    annee       TEXT NOT NULL,
    valeur      REAL,
    dims        TEXT,
    source      TEXT DEFAULT 'insee-melodi',
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(insee, dataset, indicateur, annee)
);

-- ----------------------------------------------------------------
-- Risques & ICPE (collectors/georisques.py)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS icpe_installations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code_aiot      TEXT UNIQUE,
    raison_sociale TEXT,
    insee          TEXT,
    commune        TEXT,
    adresse        TEXT,
    regime         TEXT,
    seveso         TEXT,
    etat_activite  TEXT,
    lat            REAL,
    lng            REAL,
    raw_data       TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS risques_gaspar (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    insee      TEXT NOT NULL,
    commune    TEXT,
    num_risque TEXT NOT NULL,
    libelle    TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(insee, num_risque)
);

-- ----------------------------------------------------------------
-- RAA préfecture du Gard (collectors/raa_gard.py)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raa_scans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL UNIQUE,
    filename   TEXT,
    date_doc   TEXT,
    pages      INTEGER,
    mentions   INTEGER DEFAULT 0,
    scanned_at TEXT DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------
-- Vue : score d'influence (relations + flux + événements)
-- ----------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_influence_score AS
SELECT
  e.id,
  e.type,
  e.name,
  COUNT(DISTINCT r.id) as nb_relations,
  COALESCE(SUM(DISTINCT ABS(f.amount)), 0) as total_flux,
  COUNT(DISTINCT ee.event_id) as nb_events,
  COUNT(DISTINCT r.id) + CAST(COALESCE(SUM(DISTINCT ABS(f.amount)),0)/10000 AS INT) + COUNT(DISTINCT ee.event_id)*3 as score_influence
FROM entities e
LEFT JOIN relations r ON (r.from_id=e.id OR r.to_id=e.id)
LEFT JOIN financial_flows f ON (f.from_id=e.id OR f.to_id=e.id)
LEFT JOIN event_entities ee ON ee.entity_id=e.id
GROUP BY e.id;
