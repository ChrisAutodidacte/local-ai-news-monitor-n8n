# Veille Auto Niveaux 2 & 3 — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Ajouter deux collecteurs de veille — recherche web (Brave) et surveillance de pages news/blog — qui alimentent la file `articles_veille` existante, sans modifier la chaîne d'analyse.

**Architecture :** Un seul nouveau sous-workflow n8n `Sub Collecte Web`, partagé par les types `search` et `web_scraping`, branché sur les sorties Search et Web Scraping du `Switch` du Maître. Têtes différentes (Brave API vs extraction de liens par motif d'URL), moitié arrière commune (scrape → valide → INSERT). Aucune modification de l'Analyseur, du Rapport ni du Sub Newsletter.

**Tech Stack :** n8n (Docker), Postgres (base partagée), Brave Search API (credential HTTP Header Auth), Ollama `qwen2.5:1.5b` (inchangé), credential `Postgres account` existant.

**Particularité (comme le plan Niveau 1) :** les livrables sont des fichiers JSON de workflows n8n (dossier `worklows/`). Il n'y a ni test automatisé ni dépôt git : les « tests » sont des **exécutions manuelles dans n8n** par Chris, et chaque tâche se termine par une procédure de vérification précise. Aucune étape `git commit`.

**Référence de format :** pour générer un JSON importable, **calquer la structure exacte** (versions de nœuds `typeVersion`, format des `parameters`, `connections`, `pinData`) sur le fichier existant `worklows/Sub Collecte Newsletter.json`. Lire ce fichier avant de générer le nouveau.

---

### Task 1 : Pré-requis Brave + sources de test

**Files:** aucun fichier du repo (actions manuelles dans n8n et Postgres). Cette tâche conditionne les suivantes.

- [ ] **Step 1 : Créer la clé Brave Search API**

Sur le dashboard Brave Search API, créer un compte et générer une clé d'abonnement (plan gratuit « Data for Search », ~2000 req/mois). Conserver la clé.

- [ ] **Step 2 : Créer le credential n8n `Brave Search`**

Dans n8n → Credentials → New → **Header Auth** (HTTP Header Auth) :
- Name : `X-Subscription-Token`
- Value : la clé de l'étape 1.
- Nommer le credential `Brave Search`.

- [ ] **Step 3 : Insérer deux sources de test** (nœud Postgres temporaire « Execute Query », credential `Postgres account`) :

```sql
INSERT INTO sources_veille (nom, type_source, profil_analyse, actif, config) VALUES
('Brave - facturation électronique', 'search', 'reglementaire', true,
 '{"query":"réforme facturation électronique TPE 2026","max":5,"freshness":"pw"}'::jsonb),
('Anthropic News', 'web_scraping', 'tech_ia', true,
 '{"url":"https://www.anthropic.com/news","motif_url":"/news/","max":5}'::jsonb);
```

- [ ] **Step 4 : Vérifier**

```sql
SELECT nom, type_source, config FROM sources_veille
WHERE type_source IN ('search','web_scraping') AND actif = true;
```
Attendu : les 2 lignes ci-dessus, `config` bien formé en JSONB.

---

### Task 2 : Sous-workflow `Sub Collecte Web` — squelette + têtes

**Files:**
- Create: `worklows/Sub Collecte Web.json`
- Read (référence de format) : `worklows/Sub Collecte Newsletter.json`

- [ ] **Step 1 : Lire le workflow de référence**

Ouvrir `worklows/Sub Collecte Newsletter.json` pour relever : les `typeVersion` des nœuds `Execute Workflow Trigger`, `httpRequest`, `html`, `postgres`, `if`, `merge`, `code`, `splitInBatches` (Loop Over Items), et le format exact des en-têtes navigateur du HTTP Request de scraping. Réutiliser ces mêmes versions et en-têtes.

- [ ] **Step 2 : Créer le nœud d'entrée**

**Execute Workflow Trigger** — `inputSource: passthrough`. Reçoit `{id, nom, type_source, profil_analyse, config}`.

- [ ] **Step 3 : Nœud IF « est une recherche ? »**

Type `n8n-nodes-base.if`. Condition unique :
- leftValue `={{ $json.type_source }}`, operator string **equals**, rightValue `search`.
- Sortie `true` → branche Tête Brave (Step 4). Sortie `false` → branche Tête Index (Step 5).

- [ ] **Step 4 : Tête Brave (branche true)**

4a. **HTTP Request « Brave Search »** :
- Method `GET`, URL `https://api.search.brave.com/res/v1/web/search`.
- Authentication : Generic Credential Type → **HTTP Header Auth** → credential `Brave Search`.
- Send Query Parameters = true :
  - `q` = `={{ $json.config.query }}`
  - `freshness` = `={{ $json.config.freshness || 'pw' }}`
  - `count` = `10`
  - `result_filter` = `web`
- Send Headers = true : `Accept` = `application/json`.
- `onError: continueRegularOutput`.

4b. **Code « normaliser Brave »** :
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

- [ ] **Step 5 : Tête Index (branche false)**

5a. **HTTP Request « Lire index »** :
- Method `GET`, URL `={{ $json.config.url }}`.
- Options → Response → Response Format : `text`.
- Send Headers = true (en-têtes navigateur repris du sub newsletter) :
  - `User-Agent` = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36`
  - `Accept` = `text/html,application/xhtml+xml`
- `retryOnFail: true`, `onError: continueRegularOutput`.

5b. **HTML « Extraire liens »** (`n8n-nodes-base.html`, operation `extractHtmlContent`) :
- Source Data : `JSON` → `={{ $json.data }}`.
- Extraction Values : 1 entrée → Key `hrefs`, CSS Selector `a`, Return Value `Attribute`, Attribute `href`, Return Array = true.

5c. **Code « filtrer liens par motif »** :
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

- [ ] **Step 6 : Nœud Merge** (`n8n-nodes-base.merge`, `mode: append`) — réunit les sorties des deux têtes (Code « normaliser Brave » et Code « filtrer liens par motif »). Une seule branche sera peuplée selon l'IF.

- [ ] **Step 7 : Vérifier les deux têtes séparément**

Importer le workflow partiel dans n8n. L'exécuter manuellement deux fois en simulant le trigger (onglet « Execute Workflow » avec données d'entrée collées) :
- Entrée `search` : `{"id":1,"nom":"test","type_source":"search","profil_analyse":"reglementaire","config":{"query":"aide TPE 2026","max":5,"freshness":"pw"}}` → la sortie du Merge contient des items `{url, titre, origine_texte:'recherche_web'}`.
- Entrée `web_scraping` : `{"id":2,"nom":"test","type_source":"web_scraping","profil_analyse":"tech_ia","config":{"url":"https://www.anthropic.com/news","motif_url":"/news/","max":5}}` → la sortie du Merge contient des items `{url, titre, origine_texte:'veille_site'}` avec des URLs absolues contenant `/news/`.

---

### Task 3 : `Sub Collecte Web` — pré-filtre anti-doublon

**Files:**
- Modify: `worklows/Sub Collecte Web.json`

- [ ] **Step 1 : Code « collecter URLs »** (après le Merge) — agrège tous les candidats en un item unique pour la requête SQL :
```javascript
const urls = $input.all().map(i => i.json.url);
return [{ json: { urls } }];
```

- [ ] **Step 2 : Postgres « URLs déjà vues »** — Execute Query (credential `Postgres account`) :
```sql
SELECT url_source FROM articles_veille
WHERE url_source = ANY($1);
```
Query parameter `$1` : `={{ $json.urls }}` (type array). Si la liste est vide, la requête renvoie 0 ligne.

- [ ] **Step 3 : Code « ne garder que les nouvelles + plafond »** :
```javascript
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

- [ ] **Step 4 : Vérifier le pré-filtre (et repli si besoin)**

Exécuter manuellement avec l'entrée `web_scraping` de Task 2. Vérifier que le Code « ne garder que les nouvelles » sort au plus `max` items.
- **Si le passage du tableau à `= ANY($1)` échoue** (erreur de type Postgres sur le paramètre array) : appliquer le **repli documenté dans la spec** — supprimer les 3 nœuds de cette tâche (collecter URLs / URLs déjà vues / ne garder que les nouvelles) et brancher le Merge directement sur le Loop de Task 4. L'anti-doublon repose alors uniquement sur `ON CONFLICT DO NOTHING` à l'insertion (au prix d'un re-scraping des URLs déjà connues). Noter ce choix dans le commit/log de la tâche.

---

### Task 4 : `Sub Collecte Web` — scraping, validation, insertion

**Files:**
- Modify: `worklows/Sub Collecte Web.json`

- [ ] **Step 1 : Loop Over Items** (`splitInBatches`, batch de 1) sur la sortie du Code « ne garder que les nouvelles » (ou du Merge si repli Task 3).

- [ ] **Step 2 : HTTP Request « Scraper article »** (dans la boucle) :
- Method `GET`, URL `={{ $json.url }}`, Response Format `text`.
- Mêmes en-têtes navigateur qu'en Task 2 Step 5a.
- `retryOnFail: true`, `onError: continueRegularOutput`.

- [ ] **Step 3 : HTML « Extraire contenu »** (`extractHtmlContent`) :
- Source Data `={{ $json.data }}`.
- 1 entrée → Key `texte_source`, CSS Selector `article, [role="main"], main, .post-content, .entry-content, #content`, Return Value `Text`.
- `onError: continueRegularOutput`.

- [ ] **Step 4 : Code « valider + préparer insert »** :
```javascript
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
  email_id: 'web',                  // sentinelle anti-doublon (voir spec)
  url_source: meta.url,
  titre_brut: meta.titre || '',
  texte_brut: texte,
  origine_texte: meta.origine_texte // 'recherche_web' ou 'veille_site'
}}];
```

- [ ] **Step 5 : Postgres « Insert article web »** — Execute Query (credential `Postgres account`) :
```sql
INSERT INTO articles_veille
  (source_id, source_nom, profil_analyse, email_id, url_source, titre_brut, texte_brut, origine_texte)
VALUES
  ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT ON CONSTRAINT uniq_article_veille DO NOTHING;
```
Query parameters :
`{{ $json.source_id }}, {{ $json.source_nom }}, {{ $json.profil_analyse }}, {{ $json.email_id }}, {{ $json.url_source }}, {{ $json.titre_brut }}, {{ $json.texte_brut }}, {{ $json.origine_texte }}`

→ connecter la sortie vers le **Loop Over Items** (retour de boucle).

- [ ] **Step 6 : Vérifier la chaîne complète du sub**

Exécuter le sub manuellement avec l'entrée `web_scraping` (Anthropic) de Task 2, puis avec l'entrée `search`. Vérifier en base :
```sql
SELECT origine_texte, email_id, statut, left(texte_brut, 60) AS extrait, url_source
FROM articles_veille
WHERE email_id = 'web'
ORDER BY date_collecte DESC LIMIT 20;
```
Attendu :
- lignes avec `statut='a_analyser'`, `email_id='web'`, `texte_brut` propre (>400 car.),
- `origine_texte='veille_site'` pour Anthropic, `'recherche_web'` pour la recherche,
- `url_source` = URL d'article réelle.

Relancer le sub à l'identique → **aucune** nouvelle ligne (anti-doublon OK).

---

### Task 5 : Brancher le Maître de la Veille

**Files:**
- Modify: `worklows/Maitre de la Veille.json`

- [ ] **Step 1 :** Dans n8n, ouvrir le workflow `Maître de la Veille`. Créer (ou réutiliser) un nœud `Execute Workflow` nommé `Call 'Sub Collecte Web'` pointant sur le workflow `Sub Collecte Web`, réglages identiques à `Call 'Sub Collecte Newsletter'` : `mode: each`, `options.waitForSubWorkflow: true`, `inputSource: passthrough`.

- [ ] **Step 2 :** Connecter la sortie **Search** (output index 1) du nœud `Switch` à `Call 'Sub Collecte Web'`.

- [ ] **Step 3 :** Connecter la sortie **Web Scraping** (output index 2) du nœud `Switch` au **même** nœud `Call 'Sub Collecte Web'`. (Deux connexions arrivent donc sur ce nœud.)

- [ ] **Step 4 :** Vérifier que la sortie **Email** (output index 0) reste connectée à `Call 'Sub Collecte Newsletter'` (inchangé).

- [ ] **Step 5 : Vérifier**

Exécuter le Maître manuellement. Attendu :
- les sources `search` et `web_scraping` actives déclenchent chacune `Sub Collecte Web` (une exécution par source, grâce à `mode: each`) ;
- la source email continue d'appeler `Sub Collecte Newsletter` ;
- en base, de nouvelles lignes `email_id='web'` apparaissent (sauf si déjà collectées) ;
- relancer → pas de doublon.

- [ ] **Step 6 :** Exporter le JSON à jour du `Maître de la Veille` depuis n8n vers `worklows/Maitre de la Veille.json`.

---

### Task 6 : Robustesse et bout-en-bout

**Files:** aucun (vérifications). Si un correctif s'impose, réexporter le JSON concerné dans `worklows/`.

- [ ] **Step 1 : Source en échec ne bloque pas la nuit**

Insérer temporairement une source `web_scraping` avec une `url` injoignable (ex. `https://exemple-inexistant-xyz.test`) et une source `search` avec une `query` absurde sans résultat. Exécuter le Maître. Attendu : ces sources se terminent sans erreur bloquante (`onError: continueRegularOutput`), les autres sources passent. Supprimer ensuite ces sources de test.

- [ ] **Step 2 : Article illisible ignoré**

Vérifier qu'un résultat scrappé trop court ou mur-de-cookies n'apparaît **pas** en base (le Code « valider + préparer insert » renvoie `[]`). Contrôle :
```sql
SELECT count(*) FROM articles_veille
WHERE email_id='web' AND length(texte_brut) < 400;
```
Attendu : `0`.

- [ ] **Step 3 : Bout-en-bout avec Analyseur + Rapport**

Laisser l'`Analyseur Veille Ollama` traiter la file (exécution manuelle), puis le `Rapport Veille du Matin`. Attendu :
- les articles web passent en `statut='analyse'` avec résumé FR ;
- l'email de 7h contient les articles web groupés par `theme_principal`, mêlés aux newsletters, avec lien `url_source` cliquable.

Contrôle file :
```sql
SELECT origine_texte, statut, count(*)
FROM articles_veille
WHERE date_collecte > now() - interval '24 hours'
GROUP BY origine_texte, statut ORDER BY origine_texte;
```

- [ ] **Step 4 : Plafond par source**

Vérifier qu'une source seule n'insère jamais plus de `config.max` articles par exécution (compter les insertions d'une exécution unique d'une source dans les logs n8n ou via les `date_collecte` rapprochées).

---

### Task 7 : Mise en service

- [ ] **Step 1 :** Activer le workflow `Sub Collecte Web` (toggle Actif) et confirmer que le `Maître de la Veille` reste actif.

- [ ] **Step 2 :** Régler/confirmer les sources `search` et `web_scraping` réellement voulues par Chris (remplacer les sources de test par les vraies : ses requêtes et ses pages news/blog à surveiller).

- [ ] **Step 3 :** Laisser tourner une nuit complète. Le matin, vérifier l'email de 7h puis :
```sql
SELECT origine_texte, statut, count(*) FROM articles_veille
WHERE date_collecte > now() - interval '24 hours'
GROUP BY origine_texte, statut;
```

- [ ] **Step 4 :** Exporter les JSON finaux (`Sub Collecte Web.json`, `Maitre de la Veille.json`) depuis n8n vers `worklows/` pour garder la copie locale à jour.

---

## Auto-revue effectuée

- **Couverture spec :** credential Brave + sources (T1), squelette + têtes search/web_scraping (T2), pré-filtre anti-doublon avec repli documenté (T3), scrape/valide/insert + sentinelle `email_id='web'` + `origine_texte` neufs (T4), branchement des 2 sorties Switch sur le sub partagé (T5), robustesse + bout-en-bout + plafond (T6), mise en service (T7). ✔
- **Cohérence des noms :** `Sub Collecte Web`, `origine_texte` ∈ {`recherche_web`, `veille_site`}, `email_id='web'`, nœuds référencés à l'identique dans les codes (`$('Execute Workflow Trigger')`, `$('Merge')`, `$('Loop Over Items')`, `$('URLs déjà vues')`). ✔
- **Pas de placeholder :** tous les codes JS et SQL sont fournis intégralement ; le seul point incertain (array → `= ANY($1)`) a un repli explicite en T3 Step 4. ✔
- **Spécificités projet :** aucun test automatisé ni git (vérifications manuelles n8n), aucune modification de l'Analyseur / Rapport / Sub Newsletter — conforme à la spec. ✔
