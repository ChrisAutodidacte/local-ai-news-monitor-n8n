# Veille Auto Niveau 1 — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Chaîne complète de veille newsletters : collecte Gmail → file d'attente Postgres → analyse Ollama séquentielle la nuit → email de synthèse à 7h.

**Architecture :** 4 workflows n8n (Maître planifié, Sub Collecte sans Ollama, Analyseur dépilant la file un article à la fois, Rapport du Matin) autour d'une nouvelle table `articles_veille` qui sert de file d'attente avec statuts.

**Tech Stack :** n8n (Docker), Postgres (base partagée avec n8n), Ollama `qwen2.5:1.5b`, Gmail OAuth2 (credential existant `Gmail Bot`), credential Postgres existant (`Postgres account`), credential Ollama existant (`Ollama account`).

**Particularité :** les livrables sont des fichiers JSON de workflows n8n (dans `worklows/`) et un fichier SQL. Les « tests » sont des exécutions manuelles dans n8n par Chris — chaque tâche se termine par une procédure de vérification précise au lieu d'un test automatisé.

---

### Task 1 : Table `articles_veille`

**Files:**
- Create: `sql/01_articles_veille.sql`

- [ ] **Step 1 : Écrire le fichier SQL**

```sql
CREATE TABLE IF NOT EXISTS articles_veille (
  id              SERIAL PRIMARY KEY,
  source_id       INT REFERENCES sources_veille(id),
  source_nom      TEXT,
  profil_analyse  TEXT,
  email_id        TEXT,
  url_source      TEXT NOT NULL DEFAULT 'aucune',
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

CREATE INDEX IF NOT EXISTS idx_articles_veille_statut ON articles_veille(statut);
```

Note : `url_source` est `NOT NULL DEFAULT 'aucune'` parce qu'en Postgres deux NULL ne violent
pas une contrainte UNIQUE — sans ça, l'anti-doublon ne marcherait pas pour les articles sans URL.

- [ ] **Step 2 : Exécuter dans n8n** — workflow temporaire (ou nœud dans un workflow existant) : nœud Postgres « Execute Query » avec le SQL ci-dessus, credential `Postgres account`.

- [ ] **Step 3 : Vérifier**

```sql
SELECT column_name FROM information_schema.columns WHERE table_name='articles_veille';
```
Attendu : les 20 colonnes listées.

---

### Task 2 : Sub Collecte Newsletter (réécriture du JSON)

**Files:**
- Create: `worklows/Sub Collecte Newsletter.json` (nouveau fichier — on n'écrase pas l'ancien `Sub veille newsletter.json`, il servira de référence puis sera archivé)

Chaîne unique, nœuds dans l'ordre (tous les credentials = ceux de l'ancien sub) :

- [ ] **Step 1 : Construire le squelette du workflow**

1. **Execute Workflow Trigger** (`inputSource: passthrough`) — reçoit `{id, nom, type_source, profil_analyse, config}` du Maître.
2. **Gmail — Get Many** : `getAll`, limit 5, filtres `labelIds: ["Label_5"]`, `readStatus: unread`, `sender: ={{ $json.config.sender }}`.
3. **Code « score theme email »** : code existant repris avec défauts défensifs (Step 2).
4. **If « score suffisant »** : `={{ $json.shouldFetch }}` is true.
   - Branche false → **Gmail Mark as Read** (`messageId: ={{ $json.gmailId }}`) → fin.
   - Branche true → suite.
5. **Loop Over Items** (batch de 1) sur les emails retenus.
6. Dans la boucle : **Gmail Get** (message complet, `simple: false`) → **Code « recup url base article »** (existant, inchangé) → **HTTP Request** (page newsletter, `url: ={{ $json.url }}`) → **HTML Extract** (`.entry-content` → `contenu_propre`) → **Code « search source externe »** (existant, inchangé).
7. **If « URL externe trouvée »** : `={{ $json.sources_externes[0] }}` notEmpty.
   - true → **HTTP Request1** (article externe : en-têtes navigateur, `responseFormat: text`, `retryOnFail: true`, `onError: continueRegularOutput`) → **HTML1 Extract** (`article, [role="main"], main, .post-content, .entry-content, #content` → `texte_source`) → **Code « verif contenu article source »** (existant, inchangé) → **If « contenu valide »** (`validation.is_valid` true) :
     - valide → **Code « préparer insert (article externe) »** (Step 3, variante A)
     - invalide → **Code « préparer insert (newsletter seule) »** (Step 3, variante C)
   - false → **Code « préparer insert (lecture directe) »** (Step 3, variante B)
8. Les trois variantes convergent vers : **Postgres « Insert article »** (Step 4) → **Gmail Mark as Read** (`messageId: ={{ $('recup url base article').item.json.email_id }}`) → retour au **Loop Over Items**.

Tous les nœuds de scraping/extraction : `onError: continueRegularOutput` pour qu'un email illisible finisse en `newsletter_seule` au lieu de casser la boucle.

- [ ] **Step 2 : Code de scoring avec défauts défensifs** (remplace l'accès direct à `config.priorites`/`config.ignore`)

```javascript
const triggerData = $('Execute Workflow Trigger').first().json;
const config = triggerData.config || {};
const prioritesSource = Array.isArray(config.priorites) ? config.priorites : [];
const exclusionsSource = Array.isArray(config.ignore) ? config.ignore : [];

function analyzeText(text) {
  if (exclusionsSource.some(k => text.includes(k.toLowerCase()))) {
    return { category: 'exclu', priority: 'aucune', score: 0 };
  }
  if (prioritesSource.some(k => text.includes(k.toLowerCase()))) {
    return { category: 'prioritaire', priority: 'important', score: 5 };
  }
  return { category: 'standard', priority: 'secondaire', score: 2 };
}

const results = [];
for (const item of $input.all()) {
  const text = ((item.json.Subject || '') + ' ' + (item.json.snippet || '')).toLowerCase();
  const { category, priority, score } = analyzeText(text);
  results.push({
    gmailId: item.json.id,
    threadId: item.json.threadId,
    text, score,
    shouldFetch: score >= 3,
    priority, category,
    profil: triggerData.profil_analyse
  });
}
return results;
```

- [ ] **Step 3 : Les trois codes « préparer insert »** — même structure, seuls `texte_brut`, `url_source` et `origine_texte` changent.

Variante A (article externe valide) :
```javascript
const triggerData = $('Execute Workflow Trigger').first().json;
const emailInfo = $('recup url base article').item.json;
const out = [];
for (const item of $input.all()) {
  out.push({ json: {
    source_id: triggerData.id,
    source_nom: triggerData.nom,
    profil_analyse: triggerData.profil_analyse,
    email_id: emailInfo.email_id,
    url_source: $('search source externe').item.json.sources_externes[0] || 'aucune',
    titre_brut: emailInfo.titre,
    texte_brut: item.json.texte_source_propre || '',
    origine_texte: 'article_externe'
  }});
}
return out;
```

Variante B (lecture directe) : identique sauf
```javascript
    url_source: emailInfo.url || 'aucune',
    texte_brut: item.json.texte_propre || '',
    origine_texte: 'lecture_directe'
```

Variante C (newsletter seule, article distant illisible) : identique sauf
```javascript
    url_source: $('search source externe').item.json.sources_externes[0] || 'aucune',
    texte_brut: $('search source externe').item.json.texte_propre || '',
    origine_texte: 'newsletter_seule'
```

- [ ] **Step 4 : Nœud Postgres « Insert article »** — Execute Query :

```sql
INSERT INTO articles_veille
  (source_id, source_nom, profil_analyse, email_id, url_source, titre_brut, texte_brut, origine_texte)
VALUES
  ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT ON CONSTRAINT uniq_article_veille DO NOTHING;
```
Query parameters (option « Query Parameters ») :
`{{ $json.source_id }}, {{ $json.source_nom }}, {{ $json.profil_analyse }}, {{ $json.email_id }}, {{ $json.url_source }}, {{ $json.titre_brut }}, {{ $json.texte_brut }}, {{ $json.origine_texte }}`

- [ ] **Step 5 : Vérifier** — importer dans n8n, exécuter le Maître manuellement (1 source active, 1-2 emails non lus de test) :
  - lignes présentes dans `articles_veille` avec `statut='a_analyser'`, `texte_brut` propre, bon `origine_texte` ;
  - emails marqués lus ;
  - relancer le Maître : aucune nouvelle ligne (anti-doublon OK).

---

### Task 3 : Maître de la Veille (retouche)

**Files:**
- Modify: `worklows/Maitre de la Veille.json`

- [ ] **Step 1 :** Ajouter un **Schedule Trigger** (cron `0 1 * * *`) connecté au nœud `Execute a SQL query`, en gardant le trigger manuel existant en parallèle.
- [ ] **Step 2 :** Repointer le nœud `Call 'Sub veille newsletter'` vers le nouveau workflow **Sub Collecte Newsletter** (dans n8n : sélectionner le nouveau sub dans la liste). Garder `mode: each` + `waitForSubWorkflow: true`.
- [ ] **Step 3 :** Vérifier que les inputs passés au sub incluent bien `id, nom, profil_analyse, config` (mode passthrough : connecter la sortie du Switch telle quelle).
- [ ] **Step 4 : Vérifier** — exécution manuelle du Maître : le sub est appelé une fois par source email active, les autres types rebouclent sans erreur.

---

### Task 4 : Analyseur Veille Ollama (nouveau workflow)

**Files:**
- Create: `worklows/Analyseur Veille Ollama.json`

- [ ] **Step 1 : Construire le workflow**

1. **Schedule Trigger** (cron `30 1 * * *`) + **Manual Trigger** en parallèle.
2. **Postgres « Articles à analyser »** :
```sql
SELECT id, titre_brut, texte_brut, profil_analyse, origine_texte
FROM articles_veille
WHERE statut = 'a_analyser'
ORDER BY id
LIMIT 20;
```
3. **Loop Over Items** (batch de 1).
4. **Ollama « Analyse article »** : modèle `qwen2.5:1.5b`, options `temperature: 0.1, num_thread: 4, format: json`, `onError: continueErrorOutput`. Prompt (repris de l'existant, unifié) :

```
Tu es un assistant expert en vulgarisation de textes professionnels, administratifs et juridiques.
Ta mission est de lire l'article ci-dessous et d'en extraire les informations clés en te limitant STRICTEMENT aux catégories fournies.

Rédige ton propre article en reprenant ce qui est dit dans le texte fourni !! Ne cite pas l'article d'origine !
Ecris toujours ton texte en Français !! Si le texte d'origine est en Anglais, traduis-le en Français !!

Voici les listes de choix autorisées :
- THEMES AUTORISÉS : Finances, Administratif, Légal, Facturation, Ressources humaines, Stratégie, Salaires, Autre.
- PUBLICS CIBLES AUTORISÉS : Commerce, Indépendant, Boutique, TPE, Toutes entreprises.

Utilise exactement cette structure JSON :
{
  "theme_principal": "Choisis deux thèmes maximum pertinents dans la liste",
  "public_cible": "Choisis un seul public cible dans la liste",
  "titre_article": "Rédige un titre court de cet article",
  "resume_court": "Rédige une seule phrase résumant de quoi parle l'article",
  "resume_long": "Rédige un résumé détaillé de l'article en 3 ou 4 paragraphes clairs, style professionnel, vulgarisé et directement actionnable pour un chef d'entreprise.",
  "mots_cles": ["mot-clé 1", "mot-clé 2", "mot-clé 3"]
}

Voici l'article à analyser :
"""
{{ $json.texte_brut }}
"""

Fournis ta réponse UNIQUEMENT sous la forme d'un objet JSON valide, sans aucun texte avant ou après, sans balises Markdown. Commence par { et termine par }.
```

5. **Code « parser réponse »** (`onError: continueErrorOutput`) :
```javascript
const article = $('Loop Over Items').item.json;
const out = [];
for (const item of $input.all()) {
  let raw = item.json.content || item.json.message?.content || '';
  let clean = raw.replace(/```json/ig, '').replace(/```/g, '').trim().replace(/\\'/g, "'");
  const parsed = JSON.parse(clean); // si ça lève, la sortie erreur du nœud prend le relais
  out.push({ json: {
    article_id: article.id,
    theme_principal: String(parsed.theme_principal || 'Autre'),
    public_cible: String(parsed.public_cible || 'Toutes entreprises'),
    titre_article: String(parsed.titre_article || article.titre_brut || 'Sans titre'),
    resume_court: String(parsed.resume_court || ''),
    resume_long: String(parsed.resume_long || ''),
    mots_cles: JSON.stringify(parsed.mots_cles || [])
  }});
}
return out;
```
6. **Postgres « Update succès »** :
```sql
UPDATE articles_veille SET
  statut = 'analyse',
  theme_principal = $2, public_cible = $3, titre_article = $4,
  resume_court = $5, resume_long = $6, mots_cles = $7::jsonb,
  date_analyse = now()
WHERE id = $1;
```
(paramètres : `article_id, theme_principal, public_cible, titre_article, resume_court, resume_long, mots_cles`) → retour au Loop.
7. **Branches erreur** (sorties error d'Ollama ET du parseur) → **Code « préparer erreur »** :
```javascript
const article = $('Loop Over Items').item.json;
return [{ json: { article_id: article.id, erreur_detail: ($json.error?.message || 'Echec analyse Ollama ou parsing JSON').slice(0, 500) } }];
```
→ **Postgres « Update erreur »** :
```sql
UPDATE articles_veille SET statut = 'erreur', erreur_detail = $2, date_analyse = now() WHERE id = $1;
```
→ retour au Loop. La boucle continue toujours.

- [ ] **Step 2 : Vérifier** — avec les articles collectés en Task 2 :
  - exécution manuelle : chaque article passe en `statut='analyse'` avec résumé FR rempli ;
  - insérer un article piège (`texte_brut=''` ou texte de 3 mots) : il finit en `statut='erreur'` et les suivants sont quand même traités ;
  - relancer : « Articles à analyser » renvoie 0 ligne (rien n'est retraité).

---

### Task 5 : Rapport Veille du Matin (nouveau workflow)

**Files:**
- Create: `worklows/Rapport Veille du Matin.json`

- [ ] **Step 1 : Construire le workflow**

1. **Schedule Trigger** (cron `0 7 * * *`) + Manual Trigger.
2. **Postgres « Articles du jour »** :
```sql
SELECT a.*, s.config->>'priorites' IS NOT NULL AS source_prioritaire
FROM articles_veille a
LEFT JOIN sources_veille s ON s.id = a.source_id
WHERE a.statut = 'analyse' AND a.date_analyse > now() - interval '24 hours'
ORDER BY a.theme_principal, a.date_analyse;
```
3. **Postgres « Compteurs »** :
```sql
SELECT
  count(*) FILTER (WHERE statut='analyse')    AS nb_analyses,
  count(*) FILTER (WHERE statut='erreur')     AS nb_erreurs,
  count(*) FILTER (WHERE statut='a_analyser') AS nb_en_attente
FROM articles_veille
WHERE date_collecte > now() - interval '24 hours';
```
4. **Merge** (append) puis **Code « construire email »** :
```javascript
const items = $('Articles du jour').all().map(i => i.json);
const stats = $('Compteurs').first().json;

const dateStr = new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
let html = `<h2>📰 Veille du ${dateStr}</h2>`;

if (items.length === 0) {
  html += `<p>RAS cette nuit. (${stats.nb_erreurs} en erreur, ${stats.nb_en_attente} en attente)</p>`;
} else {
  const prioritaires = items.filter(a => a.priority === 'important' || a.category === 'prioritaire');
  if (prioritaires.length) {
    html += `<h3>⭐ À retenir</h3><ul>` + prioritaires.map(a =>
      `<li><b>${a.titre_article}</b> — ${a.resume_court}</li>`).join('') + `</ul>`;
  }
  const parTheme = {};
  for (const a of items) (parTheme[a.theme_principal || 'Autre'] ??= []).push(a);
  for (const [theme, arts] of Object.entries(parTheme)) {
    html += `<h3>${theme}</h3>`;
    for (const a of arts) {
      const lien = (a.url_source && a.url_source !== 'aucune')
        ? ` <a href="${a.url_source}">[source]</a>` : '';
      html += `<p><b>${a.titre_article}</b>${lien}<br>${a.resume_court}</p>`;
    }
  }
}
html += `<hr><small>${stats.nb_analyses} analysés · ${stats.nb_erreurs} en erreur · ${stats.nb_en_attente} en attente</small>`;

const sujet = items.length === 0
  ? `Veille ${dateStr} — RAS`
  : `Veille ${dateStr} — ${items.length} article(s)`;
return [{ json: { sujet, html } }];
```
5. **Gmail Send** : to `your-email@example.com`, subject `={{ $json.sujet }}`, message `={{ $json.html }}`, type HTML, credential `Gmail Bot`.

- [ ] **Step 2 : Vérifier**
  - exécution manuelle avec des articles analysés en base : email reçu, groupé par thème, liens cliquables, compteurs cohérents ;
  - vider la fenêtre 24h (ou tester avant toute analyse) : email « RAS » reçu.

---

### Task 6 : Mise en service et nuit de test

- [ ] **Step 1 :** Activer les 4 workflows dans n8n (toggle Actif). Désactiver l'ancien `Sub veille newsletter` (il est actuellement actif).
- [ ] **Step 2 :** Laisser tourner une nuit complète avec la source TPE ACTU.
- [ ] **Step 3 :** Le matin : vérifier l'email de 7h, puis en base :
```sql
SELECT statut, count(*) FROM articles_veille
WHERE date_collecte > now() - interval '24 hours' GROUP BY statut;
```
- [ ] **Step 4 :** Exporter les JSON finaux depuis n8n vers le dossier `worklows/` (pour garder la copie locale à jour) et archiver l'ancien `Sub veille newsletter.json` dans `worklows/archive/`.

---

## Auto-revue effectuée

- Couverture spec : table (T1), sub collecte (T2), maître (T3), analyseur (T4), rapport (T5), tests/mise en service (T6). ✔
- Cohérence des noms : `articles_veille`, statuts `a_analyser/analyse/erreur`, `origine_texte` aux trois valeurs de la spec, nœud `recup url base article` référencé à l'identique dans les codes. ✔
- `url_source` NOT NULL DEFAULT 'aucune' ajouté par rapport à la spec (contrainte UNIQUE inopérante avec NULL) — amendement technique documenté en Task 1.
