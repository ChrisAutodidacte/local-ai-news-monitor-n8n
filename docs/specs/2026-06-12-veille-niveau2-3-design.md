# Spécification — Veille Auto Niveaux 2 & 3 (Recherche web + Surveillance de sites)

**Date :** 2026-06-12
**Statut :** validé par Chris (1 sous-workflow partagé, Brave Search API, filtre par motif d'URL)
**Pré-requis :** Niveau 1 en production (voir `2026-06-11-veille-niveau1-design.md`). Table
`articles_veille`, Analyseur Ollama et Rapport du Matin déjà opérationnels.

## Objectif

Ajouter deux collecteurs au système de veille existant, sans toucher à la chaîne d'analyse :

- **Niveau 3 — Recherche web (`type_source = 'search'`)** : interroge Brave Search avec une
  requête, récupère les articles récents jamais vus, les scrape et les met en file d'analyse.
- **Niveau 2 — Surveillance de site (`type_source = 'web_scraping'`)** : lit une page-liste de
  news/blog (ex. Anthropic, OpenAI), en extrait les liens d'articles jamais vus, les scrape et
  les met en file d'analyse.

Les deux alimentent la table `articles_veille` en `statut='a_analyser'`. L'**Analyseur Veille
Ollama** et le **Rapport Veille du Matin** existants les traitent ensuite **sans aucune
modification** : ils ne lisent que `texte_brut` / `statut` / `date_analyse`, indépendamment de la
provenance.

## Principe directeur

Réutilisation maximale de l'existant. **Rien n'est modifié** dans :
- `Sub Collecte Newsletter` (la prod newsletter qui fonctionne),
- `Analyseur Veille Ollama`,
- `Rapport Veille du Matin`.

Les deux nouveautés se branchent sur les sorties **Search** et **Web Scraping** du `Switch` du
**Maître de la Veille** (déjà câblées et actuellement vides). Le `Switch` route déjà chaque ligne
`sources_veille` active selon `type_source` (`email` / `search` / `web_scraping`).

## Architecture

```
[Maître de la Veille]  (cron ~1h00)
   └── SELECT sources_veille actives → Switch par type_source
        ├── 'email'        → Call 'Sub Collecte Newsletter'   (inchangé, prod)
        ├── 'search'       → Call 'Sub Collecte Web'  (NOUVEAU)  ┐ même nœud,
        └── 'web_scraping' → Call 'Sub Collecte Web'  (NOUVEAU)  ┘ deux sorties Switch

[Sub Collecte Web]  (NOUVEAU, partagé search + web_scraping)
   reçoit {id, nom, type_source, profil_analyse, config}
   → TÊTE selon type_source → liste normalisée [{url, titre}]
   → pré-filtre anti-doublon (URLs déjà en base écartées) + plafond config.max
   → pour chaque NOUVELLE url : scrape → valide → INSERT articles_veille (a_analyser)

[Analyseur Veille Ollama]  (inchangé)  → analyse la file, statut → 'analyse'
[Rapport Veille du Matin]  (inchangé)  → email 7h, articles web mêlés aux newsletters
```

Le `Sub Collecte Web` est appelé en `mode: each`, `waitForSubWorkflow: true` (comme le sub
newsletter), garantissant un traitement source par source.

## Décisions validées

| Sujet | Décision |
|---|---|
| Moteur de recherche | **Brave Search API** (offre gratuite ~2000 req/mois, JSON propre, rien à héberger) |
| Granularité search | **Une requête par source** (`config.query`) ; plusieurs sujets = plusieurs sources |
| Volume / fraîcheur search | **Top 5 résultats récents** (`freshness=pw`, la dernière semaine), ajustable par source |
| Type de page surveillée | **Page-liste de news/blog** → on extrait les nouveaux liens d'articles |
| Extraction des liens | **Filtre par motif d'URL** (`config.motif_url`, ex. `/news/`) — pas de sélecteur CSS |
| Structure n8n | **Un seul sous-workflow partagé** `Sub Collecte Web` (IF interne sur `type_source`) |

## Modifications de données

### Table `articles_veille` — aucun changement de schéma

Les colonnes existantes suffisent. Conventions pour les items web :

- `url_source` : l'URL de l'article scrapé (clé d'unicité ; `NOT NULL DEFAULT 'aucune'`).
- `email_id` : sentinelle **`'web'`** (constante). **Indispensable** : la contrainte
  `UNIQUE (email_id, url_source)` est inopérante quand `email_id` est NULL (en Postgres deux NULL
  ne s'égalent pas). Une sentinelle non-nulle rend l'anti-doublon par URL effectif pour les items
  web. Conséquence voulue : un même article trouvé par deux sources `search`/`web_scraping`
  différentes n'est inséré qu'une fois.
- `origine_texte` : deux **nouvelles valeurs** de marquage de provenance :
  - `'recherche_web'` pour les items issus de Brave (`type_source='search'`),
  - `'veille_site'` pour les items issus d'une page surveillée (`type_source='web_scraping'`).
  L'Analyseur et le Rapport ne branchent jamais sur `origine_texte` : ajout sans risque.
- `titre_brut` : titre fourni par la tête (titre Brave, ou texte du lien d'index, ou `<title>` de
  l'article) ; sert de repli, l'Analyseur régénère `titre_article` de toute façon.
- `profil_analyse`, `source_id`, `source_nom` : repris de la ligne source via le trigger.

### Table `sources_veille` — nouvelles lignes (créées par Chris, pas par le workflow)

Format de `config` (JSONB) par type :

**`type_source = 'search'`**
```json
{ "query": "réforme facturation électronique TPE 2026", "max": 5, "freshness": "pw" }
```
- `query` (obligatoire) : la requête envoyée à Brave.
- `max` (optionnel, défaut 5) : nombre de nouveaux résultats à traiter.
- `freshness` (optionnel, défaut `"pw"`) : fenêtre Brave (`pd`=jour, `pw`=semaine, `pm`=mois,
  `py`=an). Voir doc Brave.

**`type_source = 'web_scraping'`**
```json
{ "url": "https://www.anthropic.com/news", "motif_url": "/news/", "max": 5 }
```
- `url` (obligatoire) : la page-liste à lire.
- `motif_url` (obligatoire) : fragment que doit contenir le `href` d'un lien d'article pour être
  retenu (ex. `/news/`, `/index/`, `/blog/`).
- `max` (optionnel, défaut 5) : nombre de nouveaux articles à traiter.

Exemples de sources à insérer pour tester :
```sql
INSERT INTO sources_veille (nom, type_source, profil_analyse, actif, config) VALUES
('Brave - facturation électronique', 'search', 'reglementaire', true,
 '{"query":"réforme facturation électronique TPE 2026","max":5,"freshness":"pw"}'::jsonb),
('Anthropic News', 'web_scraping', 'tech_ia', true,
 '{"url":"https://www.anthropic.com/news","motif_url":"/news/","max":5}'::jsonb);
```
(`profil_analyse` est libre ; il est passé tel quel à l'Analyseur, qui applique son prompt unique.)

## Pré-requis Brave (à faire une fois par Chris, hors n8n puis dans n8n)

1. Créer un compte sur le dashboard Brave Search API et générer une **clé d'abonnement** (plan
   gratuit « Data for Search »).
2. Dans n8n : créer un credential **HTTP Header Auth** nommé `Brave Search` :
   - Name : `X-Subscription-Token`
   - Value : la clé.
3. Endpoint utilisé : `GET https://api.search.brave.com/res/v1/web/search`
   - Query params : `q=<query>`, `freshness=<pw|pd|pm|py>`, `count=10` (on demande 10, on garde
     les `max` premiers nouveaux après anti-doublon), `result_filter=web`.
   - Header `Accept: application/json` + l'auth header du credential.
   - Réponse : tableau `web.results[]`, chaque entrée a `.url`, `.title`, `.description`,
     `.page_age` (date). On exploite `.url` et `.title`.

## Workflow — `Sub Collecte Web` (NOUVEAU)

**Fichier :** `worklows/Sub Collecte Web.json`

Nœuds dans l'ordre. Tous les nœuds de scraping/extraction : `onError: continueRegularOutput`.

### 1. Execute Workflow Trigger
- `inputSource: passthrough`. Reçoit `{id, nom, type_source, profil_analyse, config}` du Maître.

### 2. IF « est une recherche ? »
- Condition : `={{ $json.type_source }}` **equals** `search`.
- `true` → **Tête Brave** (3a). `false` → **Tête Index** (3b).

### 3a. Tête Brave (branche `search`)

**Nœud HTTP « Brave Search »**
- Method `GET`, URL `https://api.search.brave.com/res/v1/web/search`.
- Authentication : credential **HTTP Header Auth** `Brave Search`.
- Query parameters :
  - `q` = `={{ $json.config.query }}`
  - `freshness` = `={{ $json.config.freshness || 'pw' }}`
  - `count` = `10`
  - `result_filter` = `web`
- Header `Accept: application/json`.
- `onError: continueRegularOutput` (une source en échec ne casse pas la nuit).

**Code « normaliser Brave »**
```javascript
const trigger = $('Execute Workflow Trigger').first().json;
const max = Number(trigger.config?.max) || 5;
const results = $json.web?.results || [];
const out = [];
for (const r of results.slice(0, max * 3)) { // marge avant anti-doublon
  if (!r.url) continue;
  out.push({ json: {
    url: r.url,
    titre: r.title || '',
    source_id: trigger.id,
    source_nom: trigger.nom,
    profil_analyse: trigger.profil_analyse,
    origine_texte: 'recherche_web',
    max
  }});
}
return out;
```

### 3b. Tête Index (branche `web_scraping`)

**Nœud HTTP « Lire index »**
- Method `GET`, URL `={{ $json.config.url }}`.
- Options → Response → `responseFormat: text`.
- En-têtes navigateur (réutiliser ceux du sub newsletter) :
  `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36`,
  `Accept: text/html,application/xhtml+xml`.
- `retryOnFail: true`, `onError: continueRegularOutput`.

**Nœud HTML « Extraire liens »** (`n8n-nodes-base.html`, operation `extractHtmlContent`)
- Source data : `={{ $json.data }}` (le HTML texte de la réponse précédente).
- Extraction value : selector `a`, attribute `href`, `returnArray: true`, key `hrefs`.

**Code « filtrer liens par motif »**
```javascript
const trigger = $('Execute Workflow Trigger').first().json;
const base = trigger.config?.url;
const motif = trigger.config?.motif_url || '';
const max = Number(trigger.config?.max) || 5;
const hrefs = $json.hrefs || [];

const seen = new Set();
const out = [];
for (const href of hrefs) {
  if (!href || !String(href).includes(motif)) continue;
  let abs;
  try { abs = new URL(href, base).href; } catch { continue; } // résout les liens relatifs
  abs = abs.split('#')[0]; // enlève l'ancre
  if (seen.has(abs)) continue;
  seen.add(abs);
  out.push({ json: {
    url: abs,
    titre: '',
    source_id: trigger.id,
    source_nom: trigger.nom,
    profil_analyse: trigger.profil_analyse,
    origine_texte: 'veille_site',
    max
  }});
}
return out;
```

### 4. Merge (append)
- Réunit les sorties des deux têtes (une seule sera peuplée selon la branche). `mode: append`.

### 5. Pré-filtre anti-doublon (évite de re-scraper les URLs déjà connues)

**Postgres « URLs déjà vues »** — Execute Query :
```sql
SELECT url_source FROM articles_veille
WHERE url_source = ANY($1);
```
- Query parameter `$1` : `={{ $json.url ... }}` — **passer le tableau de toutes les URLs
  candidates**. En pratique, faire précéder d'un **Code « collecter URLs »** qui agrège les items
  en un seul item portant `{ urls: [...] }`, puis passer `={{ $json.urls }}` en paramètre (type
  array). Voir note d'implémentation ci-dessous.

**Code « ne garder que les nouvelles + plafond »**
```javascript
// items candidats = sortie du Merge ; déjà-vus = sortie du SELECT
const dejaVus = new Set($('URLs déjà vues').all().map(i => i.json.url_source));
const candidats = $('Merge').all().map(i => i.json);
const max = candidats[0]?.max || 5;
const out = [];
for (const c of candidats) {
  if (dejaVus.has(c.url)) continue;
  out.push({ json: c });
  if (out.length >= max) break;
}
return out; // 0 à max items, chacun = un article jamais vu à scraper
```

> **Note d'implémentation (pré-filtre)** : le plus simple en n8n est un **Code « collecter URLs »**
> placé juste après le Merge qui renvoie un unique item `{ json: { urls: [...toutes les url...] } }`
> pour alimenter le SELECT, puis le **Code « ne garder que les nouvelles »** ci-dessus qui relit
> les candidats via `$('Merge').all()`. Si l'agrégation de tableau pose souci, repli acceptable :
> **supprimer le pré-filtre** et compter uniquement sur `ON CONFLICT DO NOTHING` à l'insertion —
> au prix d'un re-scraping inutile des URLs déjà connues chaque nuit (acceptable mais moins propre).

### 6. Loop Over Items (batch de 1) sur les nouvelles URLs

Dans la boucle :

**HTTP « Scraper article »**
- `GET` `={{ $json.url }}`, `responseFormat: text`, mêmes en-têtes navigateur qu'en 3b,
  `retryOnFail: true`, `onError: continueRegularOutput`.

**HTML « Extraire contenu »** (`extractHtmlContent`)
- Source `={{ $json.data }}`.
- Selector (repris du sub newsletter) :
  `article, [role="main"], main, .post-content, .entry-content, #content`,
  key `texte_source`, `returnValue: text`.

**Code « valider + préparer insert »**
```javascript
const trigger = $('Execute Workflow Trigger').first().json;
const meta = $('Loop Over Items').item.json; // url, titre, origine_texte, source_*, profil
const texte = ($json.texte_source || '').replace(/\s+/g, ' ').trim();

// Validation : longueur mini + pas un mur de cookies/erreur
const tropCourt = texte.length < 400;
const cookieWall = /(accepter les cookies|cookie policy|enable javascript|403 forbidden|access denied)/i.test(texte);
if (tropCourt || cookieWall) {
  return []; // article illisible → on l'ignore, pas de déchet en base
}

return [{ json: {
  source_id: meta.source_id,
  source_nom: meta.source_nom,
  profil_analyse: meta.profil_analyse,
  email_id: 'web',                 // sentinelle anti-doublon (voir spec)
  url_source: meta.url,
  titre_brut: meta.titre || '',
  texte_brut: texte,
  origine_texte: meta.origine_texte // 'recherche_web' ou 'veille_site'
}}];
```

**Postgres « Insert article web »** — Execute Query :
```sql
INSERT INTO articles_veille
  (source_id, source_nom, profil_analyse, email_id, url_source, titre_brut, texte_brut, origine_texte)
VALUES
  ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT ON CONSTRAINT uniq_article_veille DO NOTHING;
```
Query parameters :
`{{ $json.source_id }}, {{ $json.source_nom }}, {{ $json.profil_analyse }}, {{ $json.email_id }}, {{ $json.url_source }}, {{ $json.titre_brut }}, {{ $json.texte_brut }}, {{ $json.origine_texte }}`

→ retour au **Loop Over Items**.

### Gestion d'erreur (rappel)
- Chaque HTTP/HTML en `onError: continueRegularOutput` : un article illisible est ignoré (renvoi
  `[]` par le code de validation) sans interrompre la boucle ni la source suivante.
- Brave ou page d'index injoignable → la tête renvoie peu/pas d'items → la source se termine
  proprement, les autres sources continuent (le Maître est en `mode: each`).
- À la différence du flux newsletter, on **n'insère pas** d'item « illisible » : un résultat de
  recherche non scrappable n'a aucune valeur, autant ne pas charger Ollama avec.

## Workflow — `Maître de la Veille` (retouche minime)

**Fichier :** `worklows/Maitre de la Veille.json` (modifier)

- Connecter la sortie **Search** (output index 1) **et** la sortie **Web Scraping** (output index
  2) du nœud `Switch` au **même** nœud `Call 'Sub Collecte Web'`.
- Ce nœud `executeWorkflow` : `mode: each`, `options.waitForSubWorkflow: true`, `inputSource`
  passthrough (mêmes réglages que `Call 'Sub Collecte Newsletter'`), pointant sur le nouveau
  workflow `Sub Collecte Web`.
- Le nœud `Call 'Sub Collecte Newsletter'` (sortie Email) reste inchangé.
- Aucune modification du SELECT `Execute a SQL query` ni des triggers.

## Interaction avec l'Analyseur (rappel, non modifié)

- L'Analyseur dépile `WHERE statut='a_analyser' ORDER BY id LIMIT 20`. Les items web s'ajoutent à
  la file commune. Si une nuit dépasse 20 articles (newsletters + web), le surplus reste
  `a_analyser` et sera traité la nuit suivante : comportement de file voulu, aucune perte.
- Le Rapport de 7h groupe par `theme_principal` indépendamment de la provenance ; les articles web
  apparaissent donc naturellement, avec leur lien `url_source` cliquable.

## Plan de tests (exécutions manuelles dans n8n)

1. **Search** : insérer une source `search` de test, exécuter le Maître manuellement.
   - Vérifier les lignes `articles_veille` : `texte_brut` propre, `origine_texte='recherche_web'`,
     `email_id='web'`, `statut='a_analyser'`, `url_source` renseignée.
   - Relancer le Maître → **aucune** nouvelle ligne (pré-filtre + ON CONFLICT OK).
2. **Web scraping** : insérer une source `web_scraping` (ex. Anthropic News), exécuter le Maître.
   - Idem, `origine_texte='veille_site'`. Vérifier que les URLs retenues contiennent bien
     `motif_url` et sont absolues.
   - Relancer → aucune nouvelle ligne.
3. **Robustesse** : source `search` avec une requête sans résultat, et source `web_scraping` avec
   une `url` injoignable → la source se termine sans erreur bloquante, les autres passent.
4. **Bout-en-bout** : laisser tourner l'Analyseur puis le Rapport → les articles web figurent dans
   l'email de 7h, groupés par thème, liens cliquables, compteurs cohérents.
5. **Plafond** : vérifier qu'une source ne dépasse pas `config.max` insertions par exécution.

## Livrables

- `worklows/Sub Collecte Web.json` (nouveau).
- `worklows/Maitre de la Veille.json` (modifié : 2 connexions Switch → nouveau sub).
- Credential n8n `Brave Search` (HTTP Header Auth) — créé manuellement par Chris.
- Lignes `sources_veille` de test (`search` + `web_scraping`) — insérées par Chris.

## Hors périmètre

- Détection de changement d'une page de contenu unique (hash/diff).
- Lecture de flux RSS/Atom (repli envisageable plus tard si le scraping d'index devient fragile).
- Sélecteurs CSS par site pour l'extraction de liens (on s'en tient au filtre par motif d'URL).
- Scoring « idées de contenu » et tableau de bord : toujours en phases ultérieures (voir spec N1).
