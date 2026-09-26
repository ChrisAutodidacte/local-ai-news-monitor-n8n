# Spécification — Veille Auto Niveau 1 (Newsletters)

**Date :** 2026-06-11
**Statut :** validé par Chris (architecture Option C — file d'attente Postgres)

## Contexte

Serveur Linux personnel (4-8 Go RAM, pas de GPU) hébergeant Docker, n8n, Ollama et Postgres.
Objectif : système de veille automatisé qui analyse les newsletters reçues par Gmail pendant la nuit
et envoie un email de synthèse chaque matin à 7h à your-email@example.com.

Contraintes clés :
- **Un seul appel Ollama à la fois** (petit serveur, modèle `qwen2.5:1.5b`, 1 à 3 min par analyse).
- Reprise sur erreur : un article raté ne doit pas bloquer la nuit ni perdre les suivants.
- Extensible aux niveaux 2 (surveillance de sites) et 3 (recherche proactive) sans refonte.
- Convention de nommage : toute table de ce projet contient le mot **« veille »** (pour ne pas
  les mélanger avec les tables de l'assistant existant dans la même base que n8n).

## Architecture — 4 workflows, 1 nouvelle table

```
[Maître de la Veille]  (cron ~1h00)
   └── SELECT sources_veille actives → Switch par type_source
        └── type 'email' → [Sub Collecte Newsletter] (mode each, waitForSubWorkflow)
                              └── INSERT articles bruts dans articles_veille (statut='a_analyser')

[Analyseur Veille Ollama]  (cron ~1h30)
   └── dépile articles_veille statut='a_analyser' UN par UN → Ollama → UPDATE (statut='analyse')

[Rapport Veille du Matin]  (cron 7h00)
   └── SELECT articles analysés des dernières 24h → email HTML synthèse
```

Principe central : **séparation collecte / analyse**. Les workflows de collecte n'appellent
jamais Ollama ; seul l'Analyseur le fait, en boucle séquentielle (batch de 1). La sérialisation
est garantie par construction. Les niveaux 2 et 3 seront de simples collecteurs supplémentaires
alimentant la même table.

## Tables

### `sources_veille` (existante, inchangée)

Colonnes : `id` (int), `nom` (varchar), `type_source` (varchar : email | search | web_scraping),
`profil_analyse` (varchar), `actif` (bool), `config` (jsonb), `created_at` (timestamp).

Clés attendues dans `config` pour `type_source='email'` :
- `sender` : filtre expéditeur Gmail
- `priorites` : tableau de mots-clés prioritaires (score 5)
- `ignore` : tableau de mots-clés d'exclusion (score 0)

Le code du scoring applique des valeurs par défaut (`[]`) si `priorites` ou `ignore` manquent :
une source mal configurée ne fait pas planter la collecte.

### `articles_veille` (nouvelle)

```sql
CREATE TABLE IF NOT EXISTS articles_veille (
  id              SERIAL PRIMARY KEY,
  source_id       INT REFERENCES sources_veille(id),
  source_nom      TEXT,
  profil_analyse  TEXT,
  email_id        TEXT,
  url_source      TEXT,
  titre_brut      TEXT,
  texte_brut      TEXT,
  origine_texte   TEXT,   -- 'article_externe' | 'lecture_directe' | 'newsletter_seule'
  statut          TEXT DEFAULT 'a_analyser',  -- a_analyser | analyse | erreur
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
```

Anti-doublon : insertion en `ON CONFLICT DO NOTHING` — un article déjà collecté n'est jamais
retraité, même si l'email reste non lu ou si la collecte est relancée.

## Workflow 1 — Maître de la Veille (retravail léger)

- Remplacer le trigger manuel par un **Schedule Trigger** (cron, ~1h00 du matin). Garder un
  trigger manuel en parallèle pour les tests.
- Le reste est conservé : SELECT sources actives → Loop → Switch (email / search / web_scraping)
  → appel du Sub Collecte Newsletter en mode `each` avec `waitForSubWorkflow: true`.
- Les sorties `search` et `web_scraping` du Switch rebouclent sur le Loop (comme aujourd'hui)
  en attendant les niveaux 2-3.

## Workflow 2 — Sub Collecte Newsletter (retravail majeur)

Réconciliation des deux chaînes actuellement déconnectées en **une seule chaîne** partant du
`Execute Workflow Trigger` :

1. **Gmail Get Many** — filtre : non lus, label veille, `sender` = `config.sender` (plus de
   « TPE ACTU » en dur ; suppression du nœud Gmail dupliqué et de la chaîne du trigger manuel).
2. **Scoring** (code existant conservé) — mots-clés `priorites`/`ignore` de `config`, avec
   défauts `[]`. Emails sous le seuil : marqués lus, fin.
3. **Loop Over Items** (par email) :
   a. Mark as read différé (voir point 6) ; Get message complet.
   b. **Extraction titre + URL** de l'article (code `recup url base article` conservé).
   c. **Scraping** de la page newsletter → nettoyage (`search source externe` conservé).
   d. Si URL externe trouvée → scraping de l'article source (avec les en-têtes navigateur et
      `retryOnFail` actuels) → validation anti-cookies / longueur minimale (code conservé).
   e. **Décision du texte à stocker** (les 3 chemins actuels sont conservés mais ne choisissent
      plus un prompt Ollama — ils choisissent le `texte_brut` et son `origine_texte`) :
      - article externe valide → `origine_texte='article_externe'`
      - pas d'URL externe → texte de la page newsletter → `'lecture_directe'`
      - article externe illisible → texte de la newsletter → `'newsletter_seule'`
   f. **INSERT dans `articles_veille`** (`statut='a_analyser'`, `ON CONFLICT DO NOTHING`)
      avec `source_id`, `source_nom`, `profil_analyse` venant du trigger.
4. **Suppression des 3 nœuds Ollama** et de leurs codes de parsing JSON, ainsi que du nœud
   « Rassemblement Final » (devenu inutile : tout part en base).
5. Gestion d'erreur : chaque étape de scraping en `onError: continueRegularOutput` — un email
   au contenu illisible part en `'newsletter_seule'` plutôt que d'interrompre la boucle.
6. **Mark as read seulement après insertion réussie** (ou après décision d'écarter l'email) :
   un email dont la collecte a planté reste non lu et sera repris la nuit suivante.

## Workflow 3 — Analyseur Veille Ollama (nouveau)

1. **Schedule Trigger** (cron ~1h30) + trigger manuel pour tests.
2. **SELECT** : `WHERE statut='a_analyser' ORDER BY id LIMIT 20` — plafond de sécurité :
   au pire 20 × 3 min = 1h de charge Ollama par nuit.
3. **Loop Over Items, batch de 1** — garantit un seul appel Ollama à la fois :
   a. Appel Ollama `qwen2.5:1.5b` (température 0.1, `format: json`, `num_thread: 4`) avec le
      prompt unique existant (vulgarisation FR, thèmes/publics imposés, sortie JSON stricte),
      injectant `texte_brut` et adaptable selon `profil_analyse`.
   b. Parsing JSON défensif (nettoyage ```json, apostrophes échappées — code existant repris).
   c. Succès → `UPDATE articles_veille SET statut='analyse', theme_principal=…, …,
      date_analyse=now() WHERE id=…`.
   d. Échec (Ollama ou parsing) → `UPDATE … SET statut='erreur', erreur_detail=…` et la boucle
      **continue** avec l'article suivant (`onError: continueRegularOutput`).
4. Anti-chevauchement : un seul workflow Analyseur, requête qui ignore les statuts ≠
   'a_analyser', cron espacé pour éviter toute exécution concurrente.

## Workflow 4 — Rapport Veille du Matin (nouveau)

1. **Schedule Trigger** cron 7h00.
2. **SELECT** des articles `statut='analyse'` avec `date_analyse > now() - interval '24 hours'`,
   triés par thème. Plus un comptage des écartés/erreurs sur la même période.
3. **Nœud Code** : construction d'un email HTML simple :
   - Section « À retenir » (articles dont la source était prioritaire),
   - Groupes par `theme_principal` : titre + résumé court + lien `url_source`,
   - Pied de page : « X articles analysés, Y écartés, Z en erreur ».
4. **Gmail Send** → your-email@example.com.
5. S'il n'y a aucun article : email court « RAS cette nuit (X écartés) » — preuve de vie du
   système.
6. Aucun appel Ollama dans ce workflow : tout est déjà en base, l'envoi prend quelques secondes.

## Hors périmètre (phases suivantes)

- Niveau 2 (surveillance de sites) et niveau 3 (recherche proactive) : nouveaux collecteurs
  alimentant `articles_veille`, branchés sur les sorties libres du Switch du Maître.
- Scoring « idées de contenu » (pertinence Chris Autodidacte, vidéo/newsletter/tuto possibles) :
  colonnes à ajouter plus tard à `articles_veille`.
- Test du modèle `qwen2.5:3b` en remplacement du 1.5b si la qualité des résumés est jugée
  insuffisante (à évaluer après une semaine de rapports).
- Tableau de bord de consultation des articles.

## Tests / validation

- Collecte : exécution manuelle du Maître avec 1 source active → vérifier les lignes
  `articles_veille` (texte propre, bon `origine_texte`, pas de doublons en relançant).
- Analyse : exécution manuelle de l'Analyseur → vérifier statuts, champs remplis, et qu'un
  article volontairement corrompu passe en `erreur` sans bloquer les suivants.
- Rapport : exécution manuelle → email reçu, lisible, liens cliquables ; cas « 0 article ».
- Nuit complète en conditions réelles avant d'ajouter d'autres sources.
