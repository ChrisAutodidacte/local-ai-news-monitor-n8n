# Spec — Système Newsletter Abonnés
**Date : 17 juin 2026**
**Statut : validé en session de brainstorming**

> **Comment utiliser ce document** : chaque phase est autonome. Tu peux ouvrir n8n ou l'admin et copier-coller les codes directement. Les noms de workflows et de nœuds sont ceux qui existent déjà dans ton installation.

---

## Contexte et stack existante

- **n8n** sur `localhost`
- **PostgreSQL** `localhost:5432` — base `n8n_db`, user `veille`, password `changeme`
- **Ollama** en local — modèle `qwen2.5:1.5b` (credential `ollamaApi` id `<votre-credential-id>`)
- **Gmail OAuth** — credential `gmailOAuth2` id `<votre-credential-id>`, compte `your-email@example.com`
- **Adresse dédiée newsletter** — déjà créée, à connecter à n8n via un second compte Gmail OAuth
- **Interface admin Flask** sur `localhost:8090` — fichiers dans `~/n8n/admin/`
- **Credential PostgreSQL n8n** — id `<votre-credential-id>`, nom `Postgres account`

### Thèmes Ollama existants (prédéfinis dans le prompt `Analyseur Veille Ollama`)
Les seules valeurs possibles pour `articles_veille.theme_principal` sont :
`Finances` · `Administratif` · `Légal` · `Facturation` · `Ressources humaines` · `Stratégie` · `Salaires` · `Autre`

Ces valeurs sont définies dans le nœud **`Ollama Analyse article`** du workflow **`Analyseur Veille Ollama`**. Si tu veux ajouter un thème, c'est là qu'il faut l'ajouter (dans la liste `THEMES AUTORISÉS` du prompt).

---

## Décisions d'architecture

| Sujet | Décision |
|---|---|
| Déduplication | Table `newsletter_envois` — un article ne peut jamais être envoyé deux fois au même abonné |
| Envoi email | Gmail OAuth existant, nœud d'envoi isolé dans `Sub-Send-Email` pour pouvoir switcher vers Brevo/Mailgun |
| Thèmes abonnés | Champ `theme` ajouté dans `sources_veille` — valeurs issues de la liste Ollama ci-dessus |
| Commandes abonnement | Langage naturel vers adresse dédiée, Ollama interprète |
| Réponse Ollama | Toujours accuser réception, demander clarification si ambigu |
| Suggestions thèmes | Loggées dans `newsletter_suggestions_themes`, admin décide |
| Phase 4 | 3 workflows séparés : Lecteur → Processeur Ollama → Expéditeur |

---

## Phases de développement

- **Phase 1** — Transformer `Rapport Veille du Matin` en tableau de bord admin
- **Phase 2** — Migration BDD + champ `theme` dans les sources + pages admin abonnés
- **Phase 3** — Workflows dispatch newsletter personnalisée (avec template HTML intégré)
- **Phase 4** — Gestion autonome des abonnements par Ollama

---

## PHASE 1 — Transformer `Rapport Veille du Matin` en tableau de bord admin

### Principe

Le rapport du matin ne sert plus à envoyer des articles à lire — tu t'abonneras toi-même à la newsletter comme n'importe quel abonné. Il devient un **tableau de bord de supervision** envoyé chaque matin à `your-email@example.com` pour suivre la santé du système.

### Ce qu'on modifie

**Workflow** : `Rapport Veille du Matin`
**Nœud à modifier** : `Articles du jour` → remplacer la requête par les stats admin
**Nœud à modifier** : `Construire email` → remplacer le code par le tableau de bord

### Nouvelle requête SQL — nœud `Articles du jour` (renommer en `Stats admin`)

```sql
SELECT
  -- Articles
  COUNT(*) FILTER (WHERE av.statut = 'analyse'    AND av.date_collecte > now() - interval '24h') AS articles_analyses,
  COUNT(*) FILTER (WHERE av.statut = 'erreur'     AND av.date_collecte > now() - interval '24h') AS articles_erreurs,
  COUNT(*) FILTER (WHERE av.statut = 'a_analyser' AND av.date_collecte > now() - interval '24h') AS articles_en_attente,
  COUNT(*) FILTER (WHERE av.date_collecte > now() - interval '24h')                               AS articles_total,
  -- Abonnés
  (SELECT COUNT(*) FROM newsletter_abonnes WHERE actif = true)                                    AS abonnes_actifs,
  (SELECT COUNT(*) FROM newsletter_abonnes WHERE date_inscription > now() - interval '24h')       AS nouveaux_abonnes,
  (SELECT COUNT(*) FROM newsletter_abonnes WHERE actif = false AND date_modification > now() - interval '24h') AS desabonnements,
  -- Newsletter
  (SELECT COUNT(*) FROM newsletter_queue WHERE statut = 'envoye' AND date_envoi > now() - interval '24h')     AS newsletters_envoyees,
  (SELECT COUNT(*) FROM newsletter_queue WHERE statut = 'erreur' AND date_creation > now() - interval '24h')  AS newsletters_erreurs,
  -- Commandes email
  (SELECT COUNT(*) FROM newsletter_emails_commandes WHERE statut = 'traite' AND date_reception > now() - interval '24h') AS commandes_traitees,
  (SELECT COUNT(*) FROM newsletter_emails_commandes WHERE statut = 'erreur' AND date_reception > now() - interval '24h') AS commandes_erreurs
FROM articles_veille av;
```

> Supprimer le nœud `Compteurs` devenu inutile — tout est dans cette requête unique.

### Nouveau code — nœud `Construire email`

```javascript
const s = $('Stats admin').first().json;

const dateStr = new Date().toLocaleDateString('fr-FR', {
  weekday: 'long', day: 'numeric', month: 'long'
});

const HEADER = '#1a1a2e';
const ACCENT = '#457b9d';
const VERT   = '#2d6a4f';
const ROUGE  = '#c1121f';
const GRIS   = '#f8f9fa';

function ligne(label, valeur, couleur) {
  return `<tr>
    <td style="padding:8px 12px;font-size:14px;color:#444;border-bottom:1px solid #eee;">${label}</td>
    <td style="padding:8px 12px;font-size:16px;font-weight:bold;color:${couleur || '#222'};text-align:right;border-bottom:1px solid #eee;">${valeur}</td>
  </tr>`;
}

function section(titre, lignes) {
  return `
  <p style="margin:20px 0 6px 0;font-size:13px;font-weight:bold;color:${ACCENT};text-transform:uppercase;letter-spacing:1px;">${titre}</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;background:#fff;">
    ${lignes}
  </table>`;
}

const html = `<!DOCTYPE html><html><body style="margin:0;padding:0;background:${GRIS};font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 16px;">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

  <tr><td style="background:${HEADER};border-radius:10px 10px 0 0;padding:24px 28px;">
    <p style="margin:0;font-size:12px;color:#aaaacc;text-transform:uppercase;letter-spacing:2px;">Tableau de bord admin</p>
    <p style="margin:6px 0 0 0;font-size:22px;font-weight:bold;color:#fff;">🛠 Veille — ${dateStr}</p>
  </td></tr>

  <tr><td style="background:${GRIS};padding:16px 28px;">
    ${section('Articles (dernières 24h)',
      ligne('Collectés au total',  s.articles_total,      ACCENT) +
      ligne('Analysés avec succès',s.articles_analyses,   VERT)   +
      ligne('En attente d\'analyse',s.articles_en_attente,'#888') +
      ligne('En erreur',           s.articles_erreurs,    s.articles_erreurs > 0 ? ROUGE : '#888')
    )}
    ${section('Abonnés newsletter',
      ligne('Abonnés actifs',      s.abonnes_actifs,      ACCENT) +
      ligne('Nouveaux aujourd\'hui',s.nouveaux_abonnes,   s.nouveaux_abonnes > 0 ? VERT : '#888') +
      ligne('Désabonnements',      s.desabonnements,      s.desabonnements > 0 ? ROUGE : '#888')
    )}
    ${section('Envois newsletter (dernières 24h)',
      ligne('Newsletters envoyées', s.newsletters_envoyees, VERT) +
      ligne('Erreurs d\'envoi',     s.newsletters_erreurs,  s.newsletters_erreurs > 0 ? ROUGE : '#888')
    )}
    ${section('Commandes email bot (dernières 24h)',
      ligne('Commandes traitées', s.commandes_traitees, VERT) +
      ligne('Erreurs Ollama',     s.commandes_erreurs,  s.commandes_erreurs > 0 ? ROUGE : '#888')
    )}
  </td></tr>

  <tr><td style="background:${HEADER};border-radius:0 0 10px 10px;padding:14px 28px;">
    <p style="margin:0;font-size:11px;color:#666688;">Admin : http://localhost:8090 &nbsp;·&nbsp; n8n : http://localhost:5678</p>
  </td></tr>

</table></td></tr></table>
</body></html>`;

const alertes = [];
if (s.articles_erreurs > 0)      alertes.push(`${s.articles_erreurs} erreurs articles`);
if (s.newsletters_erreurs > 0)   alertes.push(`${s.newsletters_erreurs} erreurs envoi`);
if (s.commandes_erreurs > 0)     alertes.push(`${s.commandes_erreurs} erreurs Ollama`);

const sujet = alertes.length > 0
  ? `⚠️ Veille ${dateStr} — ${alertes.join(', ')}`
  : `✅ Veille ${dateStr} — ${s.articles_analyses} articles · ${s.abonnes_actifs} abonnés`;

return [{ json: { sujet, html } }];
```

---

## PHASE 2 — Migration BDD + admin

### 2.1 — SQL à exécuter dans PostgreSQL

**Tu peux tout copier-coller en une seule fois** dans un nœud Postgres n8n (opération `Execute Query`). PostgreSQL exécute les instructions séquentiellement dans l'ordre du script. Pas besoin de les faire une par une.

**Procédure dans n8n :**
1. Créer un nouveau workflow temporaire
2. Ajouter un nœud `Manual Trigger` → connecter à un nœud `Postgres`
3. Dans le nœud Postgres : opération `Execute Query`, credential `Postgres account`
4. Coller tout le bloc SQL ci-dessous dans le champ Query
5. Cliquer `Execute node` — vérifier qu'il n'y a pas d'erreur rouge
6. Supprimer le workflow temporaire une fois fait

Exécuter dans cet ordre (via psql, DBeaver, ou le nœud Execute Query de n8n) :

```sql
-- 1. Ajouter le champ theme dans sources_veille
ALTER TABLE sources_veille ADD COLUMN theme TEXT;

-- 2. Initialiser les thèmes sur les sources existantes
--    Les valeurs doivent correspondre aux THEMES AUTORISÉS du prompt Ollama :
--    Finances | Administratif | Légal | Facturation | Ressources humaines | Stratégie | Salaires | Autre

UPDATE sources_veille SET theme = 'Administratif'       WHERE nom ILIKE '%TPE%' OR nom ILIKE '%actu%';
-- Ajoute ici une ligne UPDATE par source, avec le thème qui correspond

-- Fallback : sources sans thème encore affecté
UPDATE sources_veille SET theme = 'Administratif'       WHERE theme IS NULL AND profil_analyse = 'administratif';
UPDATE sources_veille SET theme = 'Stratégie'           WHERE theme IS NULL AND profil_analyse = 'editorial';
UPDATE sources_veille SET theme = 'Autre'               WHERE theme IS NULL AND profil_analyse = 'technique';
UPDATE sources_veille SET theme = 'Autre'               WHERE theme IS NULL AND profil_analyse = 'general';

-- 3. Vérification
SELECT id, nom, type_source, profil_analyse, theme FROM sources_veille ORDER BY theme, nom;

-- 4. Tables newsletter
CREATE TABLE newsletter_abonnes (
  id                SERIAL PRIMARY KEY,
  prenom            TEXT NOT NULL,
  email             TEXT NOT NULL UNIQUE,
  themes            TEXT[] NOT NULL DEFAULT '{}',
  periodicite       TEXT NOT NULL DEFAULT 'quotidien',  -- quotidien | hebdomadaire | mensuel
  actif             BOOLEAN NOT NULL DEFAULT true,
  date_inscription  TIMESTAMPTZ DEFAULT now(),
  date_modification TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE newsletter_envois (
  id          SERIAL PRIMARY KEY,
  abonne_id   INT NOT NULL REFERENCES newsletter_abonnes(id),
  article_id  INT NOT NULL REFERENCES articles_veille(id),
  date_envoi  TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT uniq_envoi UNIQUE (abonne_id, article_id)
);
CREATE INDEX idx_envois_abonne  ON newsletter_envois(abonne_id);
CREATE INDEX idx_envois_article ON newsletter_envois(article_id);

CREATE TABLE newsletter_queue (
  id            SERIAL PRIMARY KEY,
  abonne_id     INT NOT NULL REFERENCES newsletter_abonnes(id),
  sujet         TEXT NOT NULL,
  html          TEXT NOT NULL,
  statut        TEXT NOT NULL DEFAULT 'a_envoyer',  -- a_envoyer | envoye | erreur
  date_creation TIMESTAMPTZ DEFAULT now(),
  date_envoi    TIMESTAMPTZ,
  erreur_detail TEXT
);

CREATE TABLE newsletter_emails_commandes (
  id                  SERIAL PRIMARY KEY,
  email_expediteur    TEXT NOT NULL,
  sujet_original      TEXT,
  corps_original      TEXT NOT NULL,
  statut              TEXT NOT NULL DEFAULT 'recu',  -- recu | en_traitement | a_envoyer | traite | erreur
  action_detectee     TEXT,   -- inscription | desinscription | modification | suggestion | incompris
  reponse_texte       TEXT,
  erreur_detail       TEXT,
  date_reception      TIMESTAMPTZ DEFAULT now(),
  date_traitement     TIMESTAMPTZ,
  date_envoi_reponse  TIMESTAMPTZ
);
CREATE INDEX idx_commandes_statut ON newsletter_emails_commandes(statut);

CREATE TABLE newsletter_suggestions_themes (
  id              SERIAL PRIMARY KEY,
  theme_suggere   TEXT NOT NULL,
  demandeur_email TEXT,
  statut          TEXT DEFAULT 'en_attente',  -- en_attente | accepte | refuse
  date_suggestion TIMESTAMPTZ DEFAULT now()
);
```

---

### 2.2 — Modifications dans l'admin Flask (`~/n8n/admin/`)

#### Procédure de déploiement depuis Windows

Les fichiers de l'admin sont sur ton poste Windows dans `<votre-dossier-local>\admin\`, et leur version en production est sur le serveur Linux dans `~/n8n/admin/`.

**Étapes à chaque modification :**

1. **Modifier les fichiers localement** sur Windows (dans ce dossier de projet)
2. **Transférer vers le serveur** via SCP depuis un terminal PowerShell :
   ```powershell
   # Transférer un fichier modifié (exemple main.py)
   scp "<votre-dossier-local>\admin\main.py" chris@localhost:~/n8n/admin/main.py

   # Transférer un nouveau template
   scp "<votre-dossier-local>\admin\templates\abonnes.html" chris@localhost:~/n8n/admin/templates/abonnes.html
   ```
3. **Redémarrer le container admin** pour prendre en compte les changements :
   ```powershell
   ssh chris@localhost "docker restart veille_admin"
   ```
4. **Vérifier** en ouvrant `http://localhost:8090` dans le navigateur

> Si tu n'as pas encore de clé SSH configurée, la commande demandera le mot de passe à chaque fois. Pour l'éviter, configurer une clé SSH une fois pour toutes (`ssh-keygen` puis `ssh-copy-id chris@localhost`).

**Alternative sans ligne de commande** : utiliser **WinSCP** (logiciel gratuit) pour glisser-déposer les fichiers visuellement vers le serveur, puis redémarrer le container depuis n8n avec un nœud `Execute Command` ou depuis un terminal SSH.

#### Fichier `main.py` — 3 modifications

**Modification 1** : dans `_config_from_form()`, la fonction ne touche pas au champ `theme` car il est une colonne directe (pas dans `config` JSONB). Il faut l'ajouter dans les routes `source_new` et `source_edit`.

Remplacer dans `source_new` (route POST) :
```python
# AVANT
cur.execute(
    "INSERT INTO sources_veille (nom, type_source, profil_analyse, actif, config) "
    "VALUES (%s, %s, %s, %s, %s)",
    (request.form['nom'], request.form['type_source'],
     request.form['profil_analyse'], 'actif' in request.form,
     json.dumps(_config_from_form(request.form)))
)

# APRÈS
cur.execute(
    "INSERT INTO sources_veille (nom, type_source, profil_analyse, actif, config, theme) "
    "VALUES (%s, %s, %s, %s, %s, %s)",
    (request.form['nom'], request.form['type_source'],
     request.form['profil_analyse'], 'actif' in request.form,
     json.dumps(_config_from_form(request.form)),
     request.form.get('theme') or None)
)
```

Remplacer dans `source_edit` (route POST) :
```python
# AVANT
cur.execute(
    "UPDATE sources_veille SET nom=%s, type_source=%s, profil_analyse=%s, actif=%s, config=%s WHERE id=%s",
    (request.form['nom'], request.form['type_source'],
     request.form['profil_analyse'], 'actif' in request.form,
     json.dumps(_config_from_form(request.form)), sid)
)

# APRÈS
cur.execute(
    "UPDATE sources_veille SET nom=%s, type_source=%s, profil_analyse=%s, actif=%s, config=%s, theme=%s WHERE id=%s",
    (request.form['nom'], request.form['type_source'],
     request.form['profil_analyse'], 'actif' in request.form,
     json.dumps(_config_from_form(request.form)),
     request.form.get('theme') or None, sid)
)
```

**Modification 2** : remplacer la constante statique par une fonction qui interroge la BDD. Dans `main.py`, ajouter cette fonction après `get_db()` :
```python
def get_themes_newsletter():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT DISTINCT theme FROM sources_veille WHERE actif = true AND theme IS NOT NULL ORDER BY theme")
    themes = [r['theme'] for r in cur.fetchall()]
    cur.close(); conn.close()
    return themes
```

Puis dans chaque route qui utilise les thèmes (`abonne_new`, `abonne_edit`), remplacer `themes=THEMES_NEWSLETTER` par `themes=get_themes_newsletter()`.

**Modification 3** : ajouter les routes abonnés à la fin de `main.py` (avant `if __name__ == '__main__'`) :

```python
# ── Abonnés newsletter ─────────────────────────────────────────────────────────

@app.route('/abonnes')
def abonnes():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_abonnes ORDER BY date_inscription DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return render_template('abonnes.html', abonnes=rows)

@app.route('/abonnes/new', methods=['GET', 'POST'])
def abonne_new():
    if request.method == 'POST':
        try:
            themes = request.form.getlist('themes')
            conn = get_db(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO newsletter_abonnes (prenom, email, themes, periodicite, actif) VALUES (%s,%s,%s,%s,%s)",
                (request.form['prenom'], request.form['email'],
                 themes, request.form['periodicite'], 'actif' in request.form)
            )
            conn.commit(); cur.close(); conn.close()
            flash('Abonné ajouté.', 'success')
            return redirect(url_for('abonnes'))
        except Exception as e:
            flash(f'Erreur : {e}', 'danger')
    return render_template('abonne_form.html', abonne=None,
                           themes=THEMES_NEWSLETTER, periodicites=['quotidien','hebdomadaire','mensuel'])

@app.route('/abonnes/<int:aid>/edit', methods=['GET', 'POST'])
def abonne_edit(aid):
    conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        try:
            themes = request.form.getlist('themes')
            cur.execute(
                "UPDATE newsletter_abonnes SET prenom=%s, email=%s, themes=%s, periodicite=%s, actif=%s, date_modification=now() WHERE id=%s",
                (request.form['prenom'], request.form['email'],
                 themes, request.form['periodicite'], 'actif' in request.form, aid)
            )
            conn.commit(); flash('Abonné mis à jour.', 'success')
            cur.close(); conn.close()
            return redirect(url_for('abonnes'))
        except Exception as e:
            flash(f'Erreur : {e}', 'danger')
    cur.execute("SELECT * FROM newsletter_abonnes WHERE id=%s", (aid,))
    abonne = cur.fetchone()
    cur.close(); conn.close()
    return render_template('abonne_form.html', abonne=abonne,
                           themes=THEMES_NEWSLETTER, periodicites=['quotidien','hebdomadaire','mensuel'])

@app.route('/abonnes/<int:aid>/toggle', methods=['POST'])
def abonne_toggle(aid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE newsletter_abonnes SET actif = NOT actif WHERE id=%s RETURNING actif", (aid,))
    result = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify({'actif': result['actif']})

@app.route('/abonnes/<int:aid>/delete', methods=['POST'])
def abonne_delete(aid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM newsletter_abonnes WHERE id=%s", (aid,))
    conn.commit(); cur.close(); conn.close()
    flash('Abonné supprimé.', 'success')
    return redirect(url_for('abonnes'))

@app.route('/abonnes/<int:aid>/envois')
def abonne_envois(aid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_abonnes WHERE id=%s", (aid,))
    abonne = cur.fetchone()
    cur.execute("""
        SELECT a.titre_article, a.theme_principal, a.url_source, e.date_envoi
        FROM newsletter_envois e
        JOIN articles_veille a ON a.id = e.article_id
        WHERE e.abonne_id = %s
        ORDER BY e.date_envoi DESC
    """, (aid,))
    envois = cur.fetchall()
    cur.close(); conn.close()
    return render_template('abonne_envois.html', abonne=abonne, envois=envois)

@app.route('/suggestions-themes')
def suggestions_themes():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_suggestions_themes ORDER BY date_suggestion DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return render_template('suggestions_themes.html', suggestions=rows)

@app.route('/suggestions-themes/<int:sid>/statut', methods=['POST'])
def suggestion_statut(sid):
    nouveau = request.form.get('statut')
    if nouveau in ('accepte', 'refuse', 'en_attente'):
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE newsletter_suggestions_themes SET statut=%s WHERE id=%s", (nouveau, sid))
        conn.commit(); cur.close(); conn.close()
    return redirect(url_for('suggestions_themes'))
```

---

#### Fichier `templates/source_form.html` — ajout du champ theme

Ajouter ce bloc juste **avant** le `<hr>` qui précède les champs mots-clés prioritaires (ligne ~103) :

```html
<div class="mb-3">
  <label class="form-label fw-semibold">Thème newsletter</label>
  <select name="theme" class="form-select">
    <option value="">-- Aucun (source non proposée aux abonnés) --</option>
    <option value="Administratif"      {{ 'selected' if source and source.theme == 'Administratif' }}>Administratif</option>
    <option value="Facturation"        {{ 'selected' if source and source.theme == 'Facturation' }}>Facturation</option>
    <option value="Finances"           {{ 'selected' if source and source.theme == 'Finances' }}>Finances</option>
    <option value="Légal"              {{ 'selected' if source and source.theme == 'Légal' }}>Légal</option>
    <option value="Ressources humaines"{{ 'selected' if source and source.theme == 'Ressources humaines' }}>Ressources humaines</option>
    <option value="Salaires"           {{ 'selected' if source and source.theme == 'Salaires' }}>Salaires</option>
    <option value="Stratégie"          {{ 'selected' if source and source.theme == 'Stratégie' }}>Stratégie</option>
    <option value="Autre"              {{ 'selected' if source and source.theme == 'Autre' }}>Autre</option>
  </select>
  <div class="form-text">Thème affiché aux abonnés de la newsletter pour cette source.</div>
</div>
```

---

#### Nouveaux fichiers templates à créer dans `templates/`

**`templates/abonnes.html`**
```html
{% extends 'base.html' %}
{% block title %}Abonnés newsletter — Veille Admin{% endblock %}
{% block content %}
<div class="d-flex align-items-center mb-4 gap-3">
  <h4 class="mb-0">Abonnés newsletter</h4>
  <a href="/abonnes/new" class="btn btn-primary btn-sm ms-auto"><i class="bi bi-plus-lg"></i> Ajouter</a>
</div>
<table class="table table-hover">
  <thead><tr><th>Prénom</th><th>Email</th><th>Thèmes</th><th>Périodicité</th><th>Actif</th><th>Inscrit le</th><th></th></tr></thead>
  <tbody>
  {% for a in abonnes %}
  <tr>
    <td>{{ a.prenom }}</td>
    <td>{{ a.email }}</td>
    <td>{% for t in a.themes %}<span class="badge bg-info text-dark me-1">{{ t }}</span>{% endfor %}</td>
    <td>{{ a.periodicite }}</td>
    <td>
      <button class="btn btn-sm {{ 'btn-success' if a.actif else 'btn-secondary' }} toggle-abonne" data-id="{{ a.id }}">
        {{ 'Actif' if a.actif else 'Inactif' }}
      </button>
    </td>
    <td>{{ a.date_inscription.strftime('%d/%m/%Y') if a.date_inscription }}</td>
    <td>
      <a href="/abonnes/{{ a.id }}/edit" class="btn btn-sm btn-outline-secondary">Modifier</a>
      <a href="/abonnes/{{ a.id }}/envois" class="btn btn-sm btn-outline-info">Historique</a>
      <form method="post" action="/abonnes/{{ a.id }}/delete" class="d-inline"
            onsubmit="return confirm('Supprimer {{ a.prenom }} ?')">
        <button class="btn btn-sm btn-outline-danger">Supprimer</button>
      </form>
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
{% block scripts %}
<script>
document.querySelectorAll('.toggle-abonne').forEach(btn => {
  btn.addEventListener('click', () => {
    fetch(`/abonnes/${btn.dataset.id}/toggle`, {method:'POST'})
      .then(r => r.json()).then(d => location.reload());
  });
});
</script>
{% endblock %}
```

**`templates/abonne_form.html`**
```html
{% extends 'base.html' %}
{% block title %}{{ 'Modifier' if abonne else 'Nouvel' }} abonné — Veille Admin{% endblock %}
{% block content %}
<div class="d-flex align-items-center mb-4 gap-3">
  <a href="/abonnes" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i></a>
  <h4 class="mb-0">{{ 'Modifier' if abonne else 'Nouvel' }} abonné</h4>
</div>
<div class="card p-4" style="max-width:600px">
  <form method="post">
    <div class="row g-3 mb-3">
      <div class="col-md-5">
        <label class="form-label fw-semibold">Prénom</label>
        <input type="text" name="prenom" class="form-control" value="{{ abonne.prenom if abonne else '' }}" required>
      </div>
      <div class="col-md-7">
        <label class="form-label fw-semibold">Email</label>
        <input type="email" name="email" class="form-control" value="{{ abonne.email if abonne else '' }}" required>
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold">Thèmes souhaités</label>
      <div class="d-flex flex-wrap gap-2">
        {% for t in themes %}
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="themes" value="{{ t }}" id="theme_{{ loop.index }}"
                 {{ 'checked' if abonne and t in abonne.themes }}>
          <label class="form-check-label" for="theme_{{ loop.index }}">{{ t }}</label>
        </div>
        {% endfor %}
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold">Périodicité</label>
      <select name="periodicite" class="form-select">
        {% for p in periodicites %}
        <option value="{{ p }}" {{ 'selected' if abonne and abonne.periodicite == p }}>{{ p|capitalize }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="mb-4">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" name="actif" id="actif"
               {{ 'checked' if not abonne or abonne.actif }}>
        <label class="form-check-label" for="actif">Abonné actif</label>
      </div>
    </div>
    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> {{ 'Enregistrer' if abonne else 'Créer' }}</button>
      <a href="/abonnes" class="btn btn-outline-secondary">Annuler</a>
    </div>
  </form>
</div>
{% endblock %}
```

**`templates/abonne_envois.html`**
```html
{% extends 'base.html' %}
{% block title %}Historique — {{ abonne.prenom }}{% endblock %}
{% block content %}
<div class="d-flex align-items-center mb-4 gap-3">
  <a href="/abonnes" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i></a>
  <h4 class="mb-0">Articles envoyés à {{ abonne.prenom }}</h4>
</div>
{% if not envois %}
  <p class="text-muted">Aucun article envoyé pour l'instant.</p>
{% else %}
<table class="table table-hover">
  <thead><tr><th>Date envoi</th><th>Thème</th><th>Titre</th><th>Lien</th></tr></thead>
  <tbody>
  {% for e in envois %}
  <tr>
    <td>{{ e.date_envoi.strftime('%d/%m/%Y %H:%M') if e.date_envoi }}</td>
    <td><span class="badge bg-info text-dark">{{ e.theme_principal }}</span></td>
    <td>{{ e.titre_article }}</td>
    <td>{% if e.url_source and e.url_source != 'aucune' %}<a href="{{ e.url_source }}" target="_blank">→</a>{% endif %}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

**`templates/suggestions_themes.html`**
```html
{% extends 'base.html' %}
{% block title %}Suggestions de thèmes{% endblock %}
{% block content %}
<h4 class="mb-4">Suggestions de thèmes des abonnés</h4>
{% if not suggestions %}
  <p class="text-muted">Aucune suggestion pour l'instant.</p>
{% else %}
<table class="table table-hover">
  <thead><tr><th>Thème suggéré</th><th>Demandeur</th><th>Date</th><th>Statut</th><th>Action</th></tr></thead>
  <tbody>
  {% for s in suggestions %}
  <tr>
    <td><strong>{{ s.theme_suggere }}</strong></td>
    <td>{{ s.demandeur_email or '—' }}</td>
    <td>{{ s.date_suggestion.strftime('%d/%m/%Y') if s.date_suggestion }}</td>
    <td><span class="badge {{ 'bg-warning text-dark' if s.statut == 'en_attente' else ('bg-success' if s.statut == 'accepte' else 'bg-secondary') }}">{{ s.statut }}</span></td>
    <td>
      {% if s.statut == 'en_attente' %}
      <form method="post" action="/suggestions-themes/{{ s.id }}/statut" class="d-inline">
        <input type="hidden" name="statut" value="accepte">
        <button class="btn btn-sm btn-success">Accepter</button>
      </form>
      <form method="post" action="/suggestions-themes/{{ s.id }}/statut" class="d-inline">
        <input type="hidden" name="statut" value="refuse">
        <button class="btn btn-sm btn-outline-danger">Refuser</button>
      </form>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

---

#### Fichier `templates/base.html` — ajouter les liens de navigation

Dans le menu de navigation (chercher les liens `/sources` et `/articles`), ajouter :
```html
<a href="/abonnes" class="...">Abonnés</a>
<a href="/suggestions-themes" class="...">Suggestions</a>
```

---

## PHASE 3 — Workflows dispatch personnalisé

### Workflow 1 : `WF-Newsletter-Builder`

**Créer un nouveau workflow dans n8n.** Déclencheur : Schedule à 6h00 chaque matin.

**Nœud 1 — `Schedule Trigger (6h)`**
Type : Schedule Trigger — heure : 6h00

**Nœud 2 — `Abonnés actifs`** (Postgres)
```sql
SELECT id, prenom, email, themes, periodicite
FROM newsletter_abonnes
WHERE actif = true;
```

**Nœud 3 — `Filtre périodicité`** (Code)
```javascript
const items = $input.all();
const dow = new Date().getDay(); // 0=dim, 1=lun
const day = new Date().getDate();

return items.filter(item => {
  const p = item.json.periodicite;
  if (p === 'quotidien')     return true;
  if (p === 'hebdomadaire')  return dow === 1;   // lundi
  if (p === 'mensuel')       return day === 1;   // 1er du mois
  return false;
});
```

**Nœud 4 — `Articles éligibles`** (Postgres — en boucle sur chaque abonné)
```sql
SELECT a.id, a.titre_article, a.resume_court, a.theme_principal,
       a.url_source, a.mots_cles, a.date_analyse
FROM articles_veille a
JOIN sources_veille s ON s.id = a.source_id
WHERE s.theme = ANY($1::text[])
  AND a.statut = 'analyse'
  AND a.id NOT IN (
    SELECT article_id FROM newsletter_envois WHERE abonne_id = $2
  )
ORDER BY a.date_analyse DESC
LIMIT 30;
```
Paramètres : `[$json.themes, $json.id]`

**Nœud 5 — `Si aucun article → skip`** (IF)
Condition : `{{ $items.length }} > 0`

**Nœud 6 — `Construire HTML abonné`** (Code)
Même logique que le nœud Phase 1 mais en utilisant `$('Articles éligibles').all()` et en ajoutant le prénom de l'abonné dans le header. Copier le code de la Phase 1 et adapter :
- Remplacer `$('Articles du jour').all()` par `$('Articles éligibles').all()`
- Remplacer `$('Compteurs').first().json` par un objet stats calculé depuis les articles
- Ajouter dans le header : `Bonjour ${abonne.prenom},`
- Adapter le footer avec la périodicité réelle de l'abonné

**Nœud 7 — `Insérer dans queue`** (Postgres)
```sql
INSERT INTO newsletter_queue (abonne_id, sujet, html)
VALUES ($1, $2, $3);
```
Paramètres : `[$('Abonnés actifs').item.json.id, $json.sujet, $json.html]`

**Nœud 8 — `Tracer envois`** (Postgres — pour chaque article inclus)
```sql
INSERT INTO newsletter_envois (abonne_id, article_id)
SELECT $1, unnest($2::int[])
ON CONFLICT DO NOTHING;
```
Paramètres : `[abonne_id, tableau des ids articles inclus]`

---

### Workflow 2 : `WF-Newsletter-Sender`

**Créer un nouveau workflow.** Déclencheur : Schedule à 6h15 (juste après le Builder).

**Nœud 1 — `Schedule Trigger (6h15)`**

**Nœud 2 — `Emails à envoyer`** (Postgres)
```sql
SELECT q.id, q.sujet, q.html, a.email, a.prenom
FROM newsletter_queue q
JOIN newsletter_abonnes a ON a.id = q.abonne_id
WHERE q.statut = 'a_envoyer'
ORDER BY q.date_creation;
```

**Nœud 3 — `Envoyer email`** (sous-workflow `Sub-Send-Email`)
Appel avec : `{ to: $json.email, subject: $json.sujet, html: $json.html }`

**Nœud 4 — `Marquer envoyé`** (Postgres)
```sql
UPDATE newsletter_queue SET statut = 'envoye', date_envoi = now() WHERE id = $1;
```

---

### Sous-workflow : `Sub-Send-Email`

**Créer un nouveau workflow** nommé exactement `Sub-Send-Email`.

**Nœud 1 — `When called by another workflow`** (Execute Workflow Trigger)
Paramètres attendus : `to`, `subject`, `html`

**Nœud 2 — `Gmail Send`** (Gmail)
- Send To : `={{ $json.to }}`
- Subject : `={{ $json.subject }}`
- Message : `={{ $json.html }}`
- Credential : `Gmail Bot` (id `<votre-credential-id>`)
- Options → Append Attribution : false

> Pour switcher vers Brevo/Mailgun : remplacer uniquement le nœud 2 de ce sous-workflow.

---

## PHASE 4 — Gestion autonome des abonnements par Ollama

### Workflow A : `WF-Newsletter-Lecteur`

**Déclencheur** : Schedule toutes les 15 minutes.

**Nœud 1 — `Schedule Trigger (15 min)`**

**Nœud 2 — `Lire emails non lus`** (Gmail — compte adresse dédiée `bot@example.com`)
- Operation : Get Many Messages
- Filters → Read Status : Unread
- Credential : nouveau compte Gmail OAuth pour l'adresse dédiée

**Nœud 3 — `Filtre mots-clés`** (Code)
```javascript
const motsCles = ['abonnement','newsletter','inscription','désabonner',
                  'desinscription','subscribe','thème','theme','préférence'];
return $input.all().filter(item => {
  const txt = ((item.json.subject || '') + ' ' + (item.json.snippet || '') + ' ' + (item.json.text || '')).toLowerCase();
  return motsCles.some(m => txt.includes(m));
});
```

**Nœud 4 — `Enregistrer en BDD`** (Postgres)
```sql
INSERT INTO newsletter_emails_commandes (email_expediteur, sujet_original, corps_original)
VALUES ($1, $2, $3)
ON CONFLICT DO NOTHING;
```
Paramètres : `[$json.from.value[0].address, $json.subject, $json.text]`

**Nœud 5 — `Marquer comme lu`** (Gmail)
- Operation : Mark as Read
- Message ID : `={{ $json.id }}`

---

### Workflow B : `WF-Newsletter-Processeur`

**Déclencheur** : Schedule toutes les 30 minutes.

**Nœud 1 — `Schedule Trigger (30 min)`**

**Nœud 2 — `Emails à traiter`** (Postgres)
```sql
SELECT * FROM newsletter_emails_commandes WHERE statut = 'recu' LIMIT 10;
```

**Nœud 3 — `Marquer en traitement`** (Postgres)
```sql
UPDATE newsletter_emails_commandes SET statut = 'en_traitement' WHERE id = $1;
```

**Nœud 4 — `Thèmes disponibles`** (Postgres)
```sql
SELECT DISTINCT theme FROM sources_veille
WHERE actif = true AND theme IS NOT NULL ORDER BY theme;
```

**Nœud 5 — `État abonné existant`** (Postgres)
```sql
SELECT prenom, themes, periodicite FROM newsletter_abonnes
WHERE email = $1;
```

**Nœud 6 — `Ollama Interprétation`** (Ollama)
- Model : `qwen2.5:1.5b`
- Format : `json`
- Credential : `ollamaApi` (id `<votre-credential-id>`)
- Prompt :

```
Tu es l'assistant automatique de gestion d'abonnements de la newsletter "Veille TPE".
Tu reçois un email et tu dois déterminer ce que l'expéditeur souhaite faire.

Email reçu de : {{ $('Emails à traiter').item.json.email_expediteur }}
---
{{ $('Emails à traiter').item.json.corps_original }}
---

Thèmes disponibles : {{ $('Thèmes disponibles').all().map(i => i.json.theme).join(', ') }}

État actuel de cet abonné : {{ $('État abonné existant').all().length > 0 ? JSON.stringify($('État abonné existant').first().json) : "non inscrit" }}

Détermine :
1. L'action demandée parmi : inscription | desinscription | modification | suggestion_theme | incompris
2. Si inscription ou modification : les thèmes choisis (utilise EXACTEMENT les noms de la liste) et la périodicité (quotidien | hebdomadaire | mensuel)
3. Un texte de réponse en français, ton amical et professionnel, qui :
   - Précise que tu es un assistant automatisé
   - Confirme ce qui a été fait (si action claire)
   - Pour suggestion_theme : indique "votre demande est transmise à l'administrateur"
   - Pour incompris : explique ce que tu n'as pas compris et donne ces 4 exemples :
     * "Je souhaite m'abonner aux thèmes Finances et Légal, en hebdomadaire"
     * "Je veux me désabonner de la newsletter"
     * "Ajoute le thème Ressources humaines à mes préférences"
     * "Je voudrais recevoir la newsletter tous les mois"

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après :
{
  "action": "...",
  "themes": [],
  "periodicite": "...",
  "reponse_texte": "..."
}
```

**Nœud 7 — `Exécuter action BDD`** (Code + Postgres selon action)
```javascript
const result = JSON.parse($('Ollama Interprétation').first().json.response);
const email = $('Emails à traiter').item.json.email_expediteur;
const cmdId = $('Emails à traiter').item.json.id;
// Retourne l'action et les données pour les nœuds suivants
return [{ json: { ...result, email_expediteur: email, commande_id: cmdId } }];
```

Brancher ensuite un Switch sur `action` :
- `inscription` → INSERT dans `newsletter_abonnes`
- `desinscription` → UPDATE `newsletter_abonnes` SET actif = false WHERE email = ...
- `modification` → UPDATE `newsletter_abonnes` SET themes = ..., periodicite = ... WHERE email = ...
- `suggestion_theme` → INSERT dans `newsletter_suggestions_themes`
- `incompris` → rien

**Nœud 8 — `Préparer réponse`** (Postgres)
```sql
UPDATE newsletter_emails_commandes
SET statut = 'a_envoyer',
    action_detectee = $2,
    reponse_texte = $3,
    date_traitement = now()
WHERE id = $1;
```

---

### Workflow C : `WF-Newsletter-Repondeur`

**Déclencheur** : Schedule toutes les 30 minutes (décalé : ex. à H+10 min).

**Nœud 1 — `Schedule Trigger (30 min décalé)`**

**Nœud 2 — `Réponses à envoyer`** (Postgres)
```sql
SELECT * FROM newsletter_emails_commandes WHERE statut = 'a_envoyer';
```

**Nœud 3 — `Envoyer réponse`** (sous-workflow `Sub-Send-Email`)
```json
{
  "to": "={{ $json.email_expediteur }}",
  "subject": "={{ 'Re: ' + ($json.sujet_original || 'Votre demande newsletter') }}",
  "html": "={{ '<p>' + $json.reponse_texte.replace(/\n/g, '</p><p>') + '</p>' }}"
}
```

**Nœud 4 — `Marquer traité`** (Postgres)
```sql
UPDATE newsletter_emails_commandes
SET statut = 'traite', date_envoi_reponse = now()
WHERE id = $1;
```

---

## Modification du workflow existant `Analyseur Veille Ollama`

Le prompt du nœud `Ollama Analyse article` contient actuellement une liste `THEMES AUTORISÉS` en dur. Il faut la rendre dynamique pour qu'elle vienne de `sources_veille.theme`.

### Modification à apporter dans le workflow `Analyseur Veille Ollama`

**Étape 1** — Ajouter un nœud Postgres **avant** la boucle `Loop Over Items`, nommé `Thèmes actifs` :
```sql
SELECT DISTINCT theme
FROM sources_veille
WHERE actif = true AND theme IS NOT NULL
ORDER BY theme;
```

**Étape 2** — Ajouter un nœud Code après `Thèmes actifs`, nommé `Préparer liste thèmes`, qui construit la liste en chaîne et la stocke pour la boucle :
```javascript
const themes = $('Thèmes actifs').all().map(i => i.json.theme).join(', ');
// On mémorise dans une variable globale accessible dans la boucle
return [{ json: { themes_liste: themes } }];
```

**Étape 3** — Dans le nœud `Ollama Analyse article`, remplacer la ligne :
```
- THEMES AUTORISÉS : Finances, Administratif, Légal, Facturation, Ressources humaines, Stratégie, Salaires, Autre.
```
Par :
```
- THEMES AUTORISÉS : {{ $('Préparer liste thèmes').first().json.themes_liste }}
```

> **Important** : dans n8n, les nœuds avant la boucle `Loop Over Items` sont accessibles depuis l'intérieur de la boucle via leur nom. La référence `$('Préparer liste thèmes').first().json.themes_liste` fonctionne à l'intérieur du loop.

### Résultat

Désormais, ajouter ou modifier un thème dans `sources_veille.theme` via l'admin suffit. Aucun workflow n'a de thème en dur.

---

## Points d'attention

1. **Thèmes cohérents** : les thèmes dans `sources_veille.theme` sont la source de vérité unique. Ils alimentent dynamiquement le prompt Ollama (analyse articles), le formulaire abonné (admin), et le prompt Ollama de gestion des abonnements (Phase 4). Ne jamais mettre de liste de thèmes en dur dans un workflow ou dans le code.

2. **Limite Gmail** : 500 emails/jour. Largement suffisant pour démarrer.

3. **Ollama JSON** : l'option `format: json` est déjà utilisée dans le workflow existant — l'appliquer aussi au nœud `Ollama Interprétation` du WF-B.

4. **Idempotence WF-B** : le UPDATE statut → `en_traitement` en début de traitement évite le double traitement si le workflow se déclenche en parallèle.

5. **Adresse dédiée newsletter** : nécessite un second credential Gmail OAuth dans n8n (compte différent de `your-email@example.com`). À configurer avant la Phase 4.
