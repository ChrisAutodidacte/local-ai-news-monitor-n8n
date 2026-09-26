-- =============================================================================
--  Database Schema — Local AI News Monitor & Newsletter (n8n + Ollama)
-- =============================================================================
--  This script initializes all tables required for automated news monitoring,
--  AI summarization, and the Flask administrative UI.
--
--  Mounted inside /docker-entrypoint-initdb.d/: PostgreSQL executes it
--  automatically upon FIRST container launch (when data volume is empty).
-- =============================================================================

-- 1. Monitoring Sources (emails, search queries, scraping) ---------------------
CREATE TABLE IF NOT EXISTS sources_veille (
  id              SERIAL PRIMARY KEY,
  nom             TEXT NOT NULL,
  type_source     TEXT NOT NULL,                 -- email | search | web_scraping
  profil_analyse  TEXT,                          -- technical | editorial | business | general
  actif           BOOLEAN NOT NULL DEFAULT true,
  config          JSONB NOT NULL DEFAULT '{}',
  theme           TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- 2. Articles collected and analyzed by Ollama --------------------------------
CREATE TABLE IF NOT EXISTS articles_veille (
  id              SERIAL PRIMARY KEY,
  source_id       INT REFERENCES sources_veille(id),
  source_nom      TEXT,
  profil_analyse  TEXT,
  email_id        TEXT,
  url_source      TEXT NOT NULL DEFAULT 'none',
  titre_brut      TEXT,
  texte_brut      TEXT,
  origine_texte   TEXT,    -- external_article | direct_read | newsletter_only
  statut          TEXT DEFAULT 'a_analyser',   -- a_analyser | analyse | erreur
  theme_principal TEXT,
  public_cible    TEXT,
  titre_article   TEXT,
  resume_court    TEXT,
  resume_long     TEXT,
  mots_cles       JSONB,
  erreur_detail   TEXT,
  date_collecte   TIMESTAMPTZ DEFAULT now(),
  date_analyse    TIMESTAMPTZ,
  CONSTRAINT uniq_article_veille UNIQUE (email_id, url_source)
);
CREATE INDEX IF NOT EXISTS idx_articles_veille_statut ON articles_veille(statut);

-- 3. Topics available for newsletter subscription ----------------------------
CREATE TABLE IF NOT EXISTS newsletter_themes (
  id    SERIAL PRIMARY KEY,
  nom   TEXT NOT NULL UNIQUE,
  ordre INT DEFAULT 0
);

-- 4. Newsletter Subscribers ---------------------------------------------------
CREATE TABLE IF NOT EXISTS newsletter_abonnes (
  id                SERIAL PRIMARY KEY,
  prenom            TEXT NOT NULL,
  email             TEXT NOT NULL UNIQUE,
  themes            TEXT[] NOT NULL DEFAULT '{}',
  periodicite       TEXT NOT NULL DEFAULT 'daily',  -- daily | weekly | monthly
  actif             BOOLEAN NOT NULL DEFAULT true,
  date_inscription  TIMESTAMPTZ DEFAULT now(),
  date_modification TIMESTAMPTZ DEFAULT now()
);

-- 5. Dispatch History (deduplication subscriber <-> article) ------------------
CREATE TABLE IF NOT EXISTS newsletter_envois (
  id          SERIAL PRIMARY KEY,
  abonne_id   INT NOT NULL REFERENCES newsletter_abonnes(id),
  article_id  INT NOT NULL REFERENCES articles_veille(id),
  date_envoi  TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT uniq_envoi UNIQUE (abonne_id, article_id)
);
CREATE INDEX IF NOT EXISTS idx_envois_abonne  ON newsletter_envois(abonne_id);
CREATE INDEX IF NOT EXISTS idx_envois_article ON newsletter_envois(article_id);

-- 6. Outbox Queue for Newsletters ---------------------------------------------
CREATE TABLE IF NOT EXISTS newsletter_queue (
  id            SERIAL PRIMARY KEY,
  abonne_id     INT NOT NULL REFERENCES newsletter_abonnes(id),
  sujet         TEXT NOT NULL,
  html          TEXT NOT NULL,
  statut        TEXT NOT NULL DEFAULT 'a_envoyer',  -- a_envoyer | envoye | erreur
  date_creation TIMESTAMPTZ DEFAULT now(),
  date_envoi    TIMESTAMPTZ,
  erreur_detail TEXT
);

-- 7. Natural language email commands (subscribe, unsubscribe, preferences) ---
CREATE TABLE IF NOT EXISTS newsletter_emails_commandes (
  id                  SERIAL PRIMARY KEY,
  email_expediteur    TEXT NOT NULL,
  sujet_original      TEXT,
  corps_original      TEXT NOT NULL,
  statut              TEXT NOT NULL DEFAULT 'recu',   -- recu | en_traitement | a_envoyer | traite | erreur
  action_detectee     TEXT,    -- subscribe | unsubscribe | update | suggestion | unknown
  reponse_texte       TEXT,
  erreur_detail       TEXT,
  date_reception      TIMESTAMPTZ DEFAULT now(),
  date_traitement     TIMESTAMPTZ,
  date_envoi_reponse  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_commandes_statut ON newsletter_emails_commandes(statut);

-- 8. Topic suggestions submitted by subscribers -------------------------------
CREATE TABLE IF NOT EXISTS newsletter_suggestions_themes (
  id              SERIAL PRIMARY KEY,
  theme_suggere   TEXT NOT NULL,
  demandeur_email TEXT,
  statut          TEXT DEFAULT 'en_attente',   -- en_attente | accepte | refuse
  date_suggestion TIMESTAMPTZ DEFAULT now()
);

-- 9. Initial Default Topics (manageable from Flask admin) ----------------------
INSERT INTO newsletter_themes (nom, ordre) VALUES
  ('Technology', 1),
  ('Artificial Intelligence', 2),
  ('Business & Strategy', 3),
  ('General', 4)
ON CONFLICT (nom) DO NOTHING;
