import json
import os
import psycopg2
import psycopg2.extras
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
# Secret key read from environment. See .env.example.
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'change-me-in-production')

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'postgres'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'user': os.getenv('DB_USER', 'monitor'),
    'password': os.getenv('DB_PASSWORD', 'changeme'),
    'dbname': os.getenv('DB_NAME', 'n8n_db'),
}

PROFILS = ['technical', 'editorial', 'business', 'general']
TYPES_SOURCE = ['email', 'search', 'web_scraping']


def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)


def get_themes_newsletter():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT nom FROM newsletter_themes ORDER BY ordre, nom")
    themes = [r['nom'] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return themes


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT statut, COUNT(*) as nb FROM articles_veille GROUP BY statut")
    stats_articles = {r['statut'] or 'unknown': r['nb'] for r in cur.fetchall()}

    cur.execute("SELECT type_source, COUNT(*) as nb FROM sources_veille WHERE actif GROUP BY type_source")
    stats_sources = {r['type_source']: r['nb'] for r in cur.fetchall()}

    cur.execute("""
        SELECT titre_article, titre_brut, source_nom, statut, date_collecte, url_source, origine_texte
        FROM articles_veille ORDER BY date_collecte DESC LIMIT 8
    """)
    derniers = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('dashboard.html',
                           stats_articles=stats_articles,
                           stats_sources=stats_sources,
                           derniers=derniers)


# ── Sources ────────────────────────────────────────────────────────────────────

@app.route('/sources')
def sources():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources_veille ORDER BY type_source, nom")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('sources.html', sources=rows)


@app.route('/sources/new', methods=['GET', 'POST'])
def source_new():
    if request.method == 'POST':
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sources_veille (nom, type_source, profil_analyse, actif, config, theme) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (request.form['nom'], request.form['type_source'],
                 request.form['profil_analyse'], 'actif' in request.form,
                 json.dumps(_config_from_form(request.form)),
                 request.form.get('theme') or None)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('Source added successfully.', 'success')
            return redirect(url_for('sources'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    return render_template('source_form.html', source=None, profils=PROFILS, types=TYPES_SOURCE, themes_newsletter=get_themes_newsletter())


@app.route('/sources/<int:sid>/edit', methods=['GET', 'POST'])
def source_edit(sid):
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        try:
            cur.execute(
                "UPDATE sources_veille SET nom=%s, type_source=%s, profil_analyse=%s, actif=%s, config=%s, theme=%s WHERE id=%s",
                (request.form['nom'], request.form['type_source'],
                 request.form['profil_analyse'], 'actif' in request.form,
                 json.dumps(_config_from_form(request.form)),
                 request.form.get('theme') or None, sid)
            )
            conn.commit()
            flash('Source updated successfully.', 'success')
            cur.close()
            conn.close()
            return redirect(url_for('sources'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    cur.execute("SELECT * FROM sources_veille WHERE id=%s", (sid,))
    source = cur.fetchone()
    cur.close()
    conn.close()
    if not source:
        flash('Source not found.', 'danger')
        return redirect(url_for('sources'))
    return render_template('source_form.html', source=source, profils=PROFILS, types=TYPES_SOURCE, themes_newsletter=get_themes_newsletter())


@app.route('/sources/<int:sid>/toggle', methods=['POST'])
def source_toggle(sid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE sources_veille SET actif = NOT actif WHERE id=%s RETURNING actif", (sid,))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'actif': result['actif']})


@app.route('/sources/<int:sid>/delete', methods=['POST'])
def source_delete(sid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM sources_veille WHERE id=%s", (sid,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Source deleted.', 'success')
    return redirect(url_for('sources'))


# ── Articles ───────────────────────────────────────────────────────────────────

@app.route('/articles')
def articles():
    statut    = request.args.get('statut', '')
    source_id = request.args.get('source_id', '')
    search    = request.args.get('search', '')
    page      = max(1, int(request.args.get('page', 1)))
    per_page  = 25

    where, params = [], []
    if statut:
        where.append("statut = %s")
        params.append(statut)
    if source_id:
        where.append("source_id = %s")
        params.append(int(source_id))
    if search:
        where.append("(titre_article ILIKE %s OR titre_brut ILIKE %s OR resume_court ILIKE %s)")
        params += [f'%{search}%'] * 3

    clause = ('WHERE ' + ' AND '.join(where)) if where else ''

    conn = get_db()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) as nb FROM articles_veille {clause}", params)
    total = cur.fetchone()['nb']

    cur.execute(f"""
        SELECT id, titre_article, titre_brut, source_nom, statut,
               date_collecte, url_source, theme_principal, resume_court, origine_texte
        FROM articles_veille {clause}
        ORDER BY date_collecte DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, (page - 1) * per_page])
    rows = cur.fetchall()

    cur.execute("SELECT id, nom FROM sources_veille ORDER BY nom")
    src_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('articles.html',
                           articles=rows, sources=src_list,
                           statut=statut, source_id=source_id, search=search,
                           page=page, total=total,
                           total_pages=(total + per_page - 1) // per_page)


@app.route('/articles/<int:aid>')
def article_detail(aid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM articles_veille WHERE id=%s", (aid,))
    article = cur.fetchone()
    cur.close()
    conn.close()
    if not article:
        flash('Article not found.', 'danger')
        return redirect(url_for('articles'))
    return render_template('article_detail.html', article=article)


@app.route('/articles/<int:aid>/statut', methods=['POST'])
def article_set_statut(aid):
    nouveau = request.form.get('statut')
    if nouveau in ('a_analyser', 'analyse', 'erreur'):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE articles_veille SET statut=%s WHERE id=%s", (nouveau, aid))
        conn.commit()
        cur.close()
        conn.close()
        flash('Article status updated.', 'success')
    return redirect(url_for('article_detail', aid=aid))


# ── Newsletter Topics ─────────────────────────────────────────────────────────

@app.route('/themes')
def themes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_themes ORDER BY ordre, nom")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('themes.html', themes=rows)


@app.route('/themes/new', methods=['POST'])
def theme_new():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO newsletter_themes (nom, ordre) VALUES (%s, %s)",
                    (request.form['nom'].strip(), int(request.form.get('ordre') or 0)))
        conn.commit()
        cur.close()
        conn.close()
        flash('Topic added successfully.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('themes'))


@app.route('/themes/<int:tid>/edit', methods=['POST'])
def theme_edit(tid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE newsletter_themes SET nom=%s, ordre=%s WHERE id=%s",
                    (request.form['nom'].strip(), int(request.form.get('ordre') or 0), tid))
        conn.commit()
        cur.close()
        conn.close()
        flash('Topic updated successfully.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('themes'))


@app.route('/themes/<int:tid>/delete', methods=['POST'])
def theme_delete(tid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM newsletter_themes WHERE id=%s", (tid,))
        conn.commit()
        cur.close()
        conn.close()
        flash('Topic deleted.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('themes'))


# ── Newsletter Subscribers ────────────────────────────────────────────────────

@app.route('/subscribers')
@app.route('/abonnes')
def abonnes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_abonnes ORDER BY date_inscription DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('abonnes.html', abonnes=rows)


@app.route('/subscribers/new', methods=['GET', 'POST'])
@app.route('/abonnes/new', methods=['GET', 'POST'])
def abonne_new():
    if request.method == 'POST':
        try:
            themes = request.form.getlist('themes')
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO newsletter_abonnes (prenom, email, themes, periodicite, actif) VALUES (%s,%s,%s,%s,%s)",
                (request.form['prenom'], request.form['email'],
                 themes, request.form['periodicite'], 'actif' in request.form)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('Subscriber added successfully.', 'success')
            return redirect(url_for('abonnes'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    return render_template('abonne_form.html', abonne=None,
                           themes=get_themes_newsletter(),
                           periodicites=['daily', 'weekly', 'monthly'])


@app.route('/subscribers/<int:aid>/edit', methods=['GET', 'POST'])
@app.route('/abonnes/<int:aid>/edit', methods=['GET', 'POST'])
def abonne_edit(aid):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        try:
            themes = request.form.getlist('themes')
            cur.execute(
                "UPDATE newsletter_abonnes SET prenom=%s, email=%s, themes=%s, periodicite=%s, actif=%s, date_modification=now() WHERE id=%s",
                (request.form['prenom'], request.form['email'],
                 themes, request.form['periodicite'], 'actif' in request.form, aid)
            )
            conn.commit()
            flash('Subscriber updated successfully.', 'success')
            cur.close()
            conn.close()
            return redirect(url_for('abonnes'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    cur.execute("SELECT * FROM newsletter_abonnes WHERE id=%s", (aid,))
    abonne = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('abonne_form.html', abonne=abonne,
                           themes=get_themes_newsletter(),
                           periodicites=['daily', 'weekly', 'monthly'])


@app.route('/subscribers/<int:aid>/toggle', methods=['POST'])
@app.route('/abonnes/<int:aid>/toggle', methods=['POST'])
def abonne_toggle(aid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE newsletter_abonnes SET actif = NOT actif WHERE id=%s RETURNING actif", (aid,))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'actif': result['actif']})


@app.route('/subscribers/<int:aid>/delete', methods=['POST'])
@app.route('/abonnes/<int:aid>/delete', methods=['POST'])
def abonne_delete(aid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM newsletter_abonnes WHERE id=%s", (aid,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Subscriber deleted.', 'success')
    return redirect(url_for('abonnes'))


@app.route('/subscribers/<int:aid>/history')
@app.route('/abonnes/<int:aid>/envois')
def abonne_envois(aid):
    conn = get_db()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    return render_template('abonne_envois.html', abonne=abonne, envois=envois)


@app.route('/suggestions-themes')
def suggestions_themes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM newsletter_suggestions_themes ORDER BY date_suggestion DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('suggestions_themes.html', suggestions=rows)


@app.route('/suggestions-themes/<int:sid>/statut', methods=['POST'])
def suggestion_statut(sid):
    nouveau = request.form.get('statut')
    if nouveau in ('accepte', 'refuse', 'en_attente'):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE newsletter_suggestions_themes SET statut=%s WHERE id=%s", (nouveau, sid))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('suggestions_themes'))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _config_from_form(form):
    t = form.get('type_source')
    cfg = {}
    if t == 'search':
        cfg['search_query'] = form.get('search_query', '')
        cfg['max_results']  = int(form.get('max_results') or 5)
    elif t == 'web_scraping':
        cfg['url']       = form.get('url', '')
        cfg['motif_url'] = form.get('motif_url', '')
        if form.get('max'):
            cfg['max'] = int(form.get('max'))
    elif t == 'email':
        cfg['sender']      = form.get('sender', '')
        cfg['gmail_label'] = form.get('gmail_label', '')

    cfg['priorites'] = [p.strip() for p in form.get('priorites', '').split(',') if p.strip()]
    cfg['ignore']    = [i.strip() for i in form.get('ignore', '').split(',')    if i.strip()]
    return cfg


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8090, debug=False)
