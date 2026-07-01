
"""
Wiki de Campanha de RPG - Aplicativo Flask completo em arquivo único
=====================================================================

COMO USAR:
1. Instale as dependências:
   pip install flask flask-login werkzeug

2. Rode o app:
   python app.py

3. Acesse no navegador:
   http://localhost:5000

4. Login de administrador padrão (TROQUE a senha depois de logar!):
   Usuário: admin
   Senha:   admin123

O banco de dados (wiki.db, SQLite) é criado automaticamente na primeira
execução, na mesma pasta do arquivo. Todo o conteúdo (tópicos, subtópicos,
textos) pode ser criado, editado e apagado direto pelo site, sem tocar
em código - só o admin logado consegue fazer isso. Qualquer visitante
pode navegar e ler.
"""

import os
import sqlite3
from datetime import datetime

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, g, abort
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "wiki.db")

app = Flask(__name__)
app.secret_key = os.environ.get("WIKI_SECRET_KEY", "troque-esta-chave-em-producao-por-favor")

# Em produção (Railway), o SQLite deve ficar em um disco persistente (Volume).
# Defina a variável de ambiente DATA_DIR apontando para o mount path do Volume
# (ex: /data). Se não for definida, usa a pasta do próprio app (padrão local).

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar essa área."
login_manager.login_message_category = "warning"


# ----------------------------------------------------------------------
# Banco de dados
# ----------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    first_run = not os.path.exists(DB_PATH)
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            position INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS subtopics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            position INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
        )
    """)
    db.commit()

    if first_run:
        # cria usuário admin padrão
        pw_hash = generate_password_hash("admin123")
        db.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            ("admin", pw_hash),
        )
        # tópicos de exemplo
        cur = db.execute(
            "INSERT INTO topics (title, description, position) VALUES (?, ?, ?)",
            ("Mundo e Geografia", "Reinos, cidades, mapas e locais importantes da campanha.", 0),
        )
        topic_id = cur.lastrowid
        db.execute(
            "INSERT INTO subtopics (topic_id, title, content, position) VALUES (?, ?, ?, ?)",
            (topic_id, "Capital do Reino", "Escreva aqui a história e detalhes da capital...", 0),
        )
        cur2 = db.execute(
            "INSERT INTO topics (title, description, position) VALUES (?, ?, ?)",
            ("Personagens", "NPCs, vilões, aliados e personagens dos jogadores.", 1),
        )
        topic_id2 = cur2.lastrowid
        db.execute(
            "INSERT INTO subtopics (topic_id, title, content, position) VALUES (?, ?, ?, ?)",
            (topic_id2, "NPCs importantes", "Liste aqui os NPCs marcantes da campanha...", 0),
        )
        db.execute(
            "INSERT INTO topics (title, description, position) VALUES (?, ?, ?)",
            ("Regras da Casa", "Regras específicas, homebrew e ajustes da mesa.", 2),
        )
        db.commit()
    db.close()


# ----------------------------------------------------------------------
# Login
# ----------------------------------------------------------------------

class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.is_admin = bool(row["is_admin"])


@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row) if row else None


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ----------------------------------------------------------------------
# Templates (tudo embutido em um arquivo só)
# ----------------------------------------------------------------------

BASE_HTML = """
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ site_title }}{% if page_title %} - {{ page_title }}{% endif %}</title>
<style>
  :root {
    --bg: #1a1512;
    --panel: #241c17;
    --panel2: #2e2420;
    --accent: #c0863c;
    --accent2: #8f5b2b;
    --text: #ecdfc9;
    --muted: #a89a86;
    --border: #4a3a2c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: "Georgia", "Segoe UI", serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  header {
    background: linear-gradient(180deg, #2c2119, #1a1512);
    border-bottom: 2px solid var(--accent2);
    padding: 18px 24px; display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 10px;
  }
  header h1 { margin: 0; font-size: 1.6em; letter-spacing: 1px; color: var(--accent); }
  header h1 a { color: var(--accent); }
  nav a { margin-left: 16px; color: var(--text); font-size: 0.95em; }
  nav a:first-child { margin-left: 0; }
  .container { max-width: 1000px; margin: 0 auto; padding: 24px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px 24px; margin-bottom: 20px;
  }
  .topic-card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 22px; margin-bottom: 16px;
    transition: border-color .2s;
  }
  .topic-card:hover { border-color: var(--accent2); }
  .topic-card h2 { margin: 0 0 6px 0; }
  .topic-card p.desc { color: var(--muted); margin: 4px 0 10px 0; }
  .sub-list { list-style: none; padding: 0; margin: 0; }
  .sub-list li { padding: 4px 0; border-top: 1px dashed var(--border); }
  .sub-list li:first-child { border-top: none; }
  .badge {
    display: inline-block; background: var(--accent2); color: #fff;
    border-radius: 6px; padding: 1px 8px; font-size: 0.75em; margin-left: 6px;
  }
  .btn {
    display: inline-block; background: var(--accent2); color: #fff !important;
    border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer;
    font-size: 0.9em; text-decoration: none !important;
  }
  .btn:hover { background: var(--accent); }
  .btn-danger { background: #7a2b2b; }
  .btn-danger:hover { background: #a13a3a; }
  .btn-secondary { background: #4a3a2c; }
  .actions { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
  form.inline { display: inline; }
  input[type=text], input[type=password], textarea, input[type=number] {
    width: 100%; padding: 10px; margin: 6px 0 14px 0; border-radius: 6px;
    border: 1px solid var(--border); background: var(--panel2); color: var(--text);
    font-family: inherit; font-size: 1em;
  }
  textarea { min-height: 220px; resize: vertical; }
  label { font-weight: bold; color: var(--accent); }
  .flash { padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; }
  .flash.success { background: #234a2b; }
  .flash.warning { background: #4a3f23; }
  .flash.error { background: #4a2323; }
  .content-body { white-space: pre-wrap; }
  .breadcrumb { color: var(--muted); margin-bottom: 14px; font-size: 0.9em; }
  footer { text-align: center; padding: 30px; color: var(--muted); font-size: 0.85em; }
</style>
</head>
<body>
<header>
  <h1><a href="{{ url_for('index') }}">📜 {{ site_title }}</a></h1>
  <nav>
    <a href="{{ url_for('index') }}">Início</a>
    {% if current_user.is_authenticated and current_user.is_admin %}
      <a href="{{ url_for('new_topic') }}">+ Novo Tópico</a>
      <a href="{{ url_for('change_password') }}">Trocar senha</a>
      <a href="{{ url_for('logout') }}">Sair ({{ current_user.username }})</a>
    {% else %}
      <a href="{{ url_for('login') }}">Login admin</a>
    {% endif %}
  </nav>
</header>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, msg in messages %}
      <div class="flash {{ category }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {{ body|safe }}
</div>
<footer>Wiki de Campanha &middot; feita com Flask</footer>
</body>
</html>
"""


def render_page(body_html, page_title=None, **kwargs):
    body = render_template_string(body_html, **kwargs)
    return render_template_string(
        BASE_HTML,
        body=body,
        page_title=page_title,
        site_title="Wiki de Ascensão",
    )


INDEX_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Bem-vindo(a) à Wiki!</h2>
  <p>Explore os tópicos da campanha abaixo. {% if current_user.is_authenticated and current_user.is_admin %}Você está logado como administrador e pode criar, editar e excluir conteúdo.{% else %}Somente o administrador da campanha pode editar o conteúdo.{% endif %}</p>
</div>

{% if not topics %}
  <div class="panel">Nenhum tópico criado ainda. {% if current_user.is_authenticated and current_user.is_admin %}<a href="{{ url_for('new_topic') }}">Crie o primeiro tópico</a>.{% endif %}</div>
{% endif %}

{% for topic in topics %}
  <div class="topic-card">
    <h2><a href="{{ url_for('view_topic', topic_id=topic['id']) }}">{{ topic['title'] }}</a></h2>
    {% if topic['description'] %}<p class="desc">{{ topic['description'] }}</p>{% endif %}
    <ul class="sub-list">
      {% for sub in topic['subs'] %}
        <li>&bull; <a href="{{ url_for('view_subtopic', topic_id=topic['id'], sub_id=sub['id']) }}">{{ sub['title'] }}</a></li>
      {% else %}
        <li style="color:var(--muted); border:none;">Sem subtópicos ainda.</li>
      {% endfor %}
    </ul>
    {% if current_user.is_authenticated and current_user.is_admin %}
    <div class="actions">
      <a class="btn btn-secondary" href="{{ url_for('edit_topic', topic_id=topic['id']) }}">Editar tópico</a>
      <a class="btn" href="{{ url_for('new_subtopic', topic_id=topic['id']) }}">+ Subtópico</a>
      <form class="inline" method="post" action="{{ url_for('delete_topic', topic_id=topic['id']) }}" onsubmit="return confirm('Excluir este tópico e todos os subtópicos dele?');">
        <button class="btn btn-danger" type="submit">Excluir tópico</button>
      </form>
    </div>
    {% endif %}
  </div>
{% endfor %}
"""

TOPIC_BODY = """
<div class="breadcrumb"><a href="{{ url_for('index') }}">Início</a> &raquo; {{ topic['title'] }}</div>
<div class="panel">
  <h2 style="margin-top:0;">{{ topic['title'] }}</h2>
  {% if topic['description'] %}<p>{{ topic['description'] }}</p>{% endif %}
  {% if current_user.is_authenticated and current_user.is_admin %}
  <div class="actions">
    <a class="btn btn-secondary" href="{{ url_for('edit_topic', topic_id=topic['id']) }}">Editar tópico</a>
    <a class="btn" href="{{ url_for('new_subtopic', topic_id=topic['id']) }}">+ Novo subtópico</a>
  </div>
  {% endif %}
</div>

{% if not subs %}
  <div class="panel">Nenhum subtópico ainda.</div>
{% endif %}

{% for sub in subs %}
  <div class="topic-card">
    <h2 style="font-size:1.2em;"><a href="{{ url_for('view_subtopic', topic_id=topic['id'], sub_id=sub['id']) }}">{{ sub['title'] }}</a></h2>
    <p class="desc">{{ sub['content'][:180] }}{% if sub['content']|length > 180 %}...{% endif %}</p>
  </div>
{% endfor %}
"""

SUBTOPIC_BODY = """
<div class="breadcrumb">
  <a href="{{ url_for('index') }}">Início</a> &raquo;
  <a href="{{ url_for('view_topic', topic_id=topic['id']) }}">{{ topic['title'] }}</a> &raquo;
  {{ sub['title'] }}
</div>
<div class="panel">
  <h2 style="margin-top:0;">{{ sub['title'] }}</h2>
  <div class="content-body">{{ sub['content'] }}</div>
  <p style="color:var(--muted); font-size:0.85em; margin-top:20px;">Última atualização: {{ sub['updated_at'] }}</p>
  {% if current_user.is_authenticated and current_user.is_admin %}
  <div class="actions">
    <a class="btn btn-secondary" href="{{ url_for('edit_subtopic', topic_id=topic['id'], sub_id=sub['id']) }}">Editar</a>
    <form class="inline" method="post" action="{{ url_for('delete_subtopic', topic_id=topic['id'], sub_id=sub['id']) }}" onsubmit="return confirm('Excluir este subtópico?');">
      <button class="btn btn-danger" type="submit">Excluir</button>
    </form>
  </div>
  {% endif %}
</div>
"""

FORM_TOPIC_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">{{ 'Editar' if topic else 'Novo' }} Tópico</h2>
  <form method="post">
    <label>Título</label>
    <input type="text" name="title" required value="{{ topic['title'] if topic else '' }}">
    <label>Descrição (curta, opcional)</label>
    <textarea name="description" style="min-height:100px;">{{ topic['description'] if topic else '' }}</textarea>
    <button class="btn" type="submit">Salvar</button>
    <a class="btn btn-secondary" href="{{ url_for('index') }}">Cancelar</a>
  </form>
</div>
"""

FORM_SUBTOPIC_BODY = """
<div class="breadcrumb"><a href="{{ url_for('index') }}">Início</a> &raquo; <a href="{{ url_for('view_topic', topic_id=topic['id']) }}">{{ topic['title'] }}</a></div>
<div class="panel">
  <h2 style="margin-top:0;">{{ 'Editar' if sub else 'Novo' }} Subtópico em "{{ topic['title'] }}"</h2>
  <form method="post">
    <label>Título</label>
    <input type="text" name="title" required value="{{ sub['title'] if sub else '' }}">
    <label>Conteúdo</label>
    <textarea name="content" placeholder="Escreva aqui a história, descrição, regras, etc.">{{ sub['content'] if sub else '' }}</textarea>
    <button class="btn" type="submit">Salvar</button>
    <a class="btn btn-secondary" href="{{ url_for('view_topic', topic_id=topic['id']) }}">Cancelar</a>
  </form>
</div>
"""

LOGIN_BODY = """
<div class="panel" style="max-width:400px; margin:40px auto;">
  <h2 style="margin-top:0;">Login do Administrador</h2>
  <form method="post">
    <label>Usuário</label>
    <input type="text" name="username" required autofocus>
    <label>Senha</label>
    <input type="password" name="password" required>
    <button class="btn" type="submit">Entrar</button>
  </form>
</div>
"""

CHANGE_PW_BODY = """
<div class="panel" style="max-width:400px; margin:40px auto;">
  <h2 style="margin-top:0;">Trocar senha</h2>
  <form method="post">
    <label>Senha atual</label>
    <input type="password" name="current_password" required>
    <label>Nova senha</label>
    <input type="password" name="new_password" required>
    <label>Confirmar nova senha</label>
    <input type="password" name="confirm_password" required>
    <button class="btn" type="submit">Salvar</button>
  </form>
</div>
"""


# ----------------------------------------------------------------------
# Rotas públicas
# ----------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    topics = db.execute("SELECT * FROM topics ORDER BY position, id").fetchall()
    topics_full = []
    for t in topics:
        subs = db.execute(
            "SELECT * FROM subtopics WHERE topic_id = ? ORDER BY position, id",
            (t["id"],),
        ).fetchall()
        td = dict(t)
        td["subs"] = subs
        topics_full.append(td)
    return render_page(INDEX_BODY, topics=topics_full)


@app.route("/topico/<int:topic_id>")
def view_topic(topic_id):
    db = get_db()
    topic = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        abort(404)
    subs = db.execute(
        "SELECT * FROM subtopics WHERE topic_id = ? ORDER BY position, id",
        (topic_id,),
    ).fetchall()
    return render_page(TOPIC_BODY, page_title=topic["title"], topic=topic, subs=subs)


@app.route("/topico/<int:topic_id>/<int:sub_id>")
def view_subtopic(topic_id, sub_id):
    db = get_db()
    topic = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    sub = db.execute(
        "SELECT * FROM subtopics WHERE id = ? AND topic_id = ?", (sub_id, topic_id)
    ).fetchone()
    if not topic or not sub:
        abort(404)
    return render_page(SUBTOPIC_BODY, page_title=sub["title"], topic=topic, sub=sub)


# ----------------------------------------------------------------------
# Autenticação
# ----------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        flash("Usuário ou senha inválidos.", "error")
    return render_page(LOGIN_BODY, page_title="Login")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu da conta.", "success")
    return redirect(url_for("index"))


@app.route("/trocar-senha", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE id = ?", (current_user.id,)).fetchone()
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not check_password_hash(row["password_hash"], current_pw):
            flash("Senha atual incorreta.", "error")
        elif new_pw != confirm_pw:
            flash("As novas senhas não coincidem.", "error")
        elif len(new_pw) < 4:
            flash("A nova senha deve ter pelo menos 4 caracteres.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_pw), current_user.id),
            )
            db.commit()
            flash("Senha alterada com sucesso!", "success")
            return redirect(url_for("index"))
    return render_page(CHANGE_PW_BODY, page_title="Trocar senha")


# ----------------------------------------------------------------------
# CRUD de Tópicos (admin)
# ----------------------------------------------------------------------

@app.route("/topico/novo", methods=["GET", "POST"])
@login_required
@admin_required
def new_topic():
    if request.method == "POST":
        db = get_db()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("O título é obrigatório.", "error")
        else:
            max_pos = db.execute("SELECT COALESCE(MAX(position), -1) AS m FROM topics").fetchone()["m"]
            db.execute(
                "INSERT INTO topics (title, description, position) VALUES (?, ?, ?)",
                (title, description, max_pos + 1),
            )
            db.commit()
            flash("Tópico criado!", "success")
            return redirect(url_for("index"))
    return render_page(FORM_TOPIC_BODY, page_title="Novo tópico", topic=None)


@app.route("/topico/<int:topic_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def edit_topic(topic_id):
    db = get_db()
    topic = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("O título é obrigatório.", "error")
        else:
            db.execute(
                "UPDATE topics SET title = ?, description = ? WHERE id = ?",
                (title, description, topic_id),
            )
            db.commit()
            flash("Tópico atualizado!", "success")
            return redirect(url_for("view_topic", topic_id=topic_id))
    return render_page(FORM_TOPIC_BODY, page_title="Editar tópico", topic=topic)


@app.route("/topico/<int:topic_id>/excluir", methods=["POST"])
@login_required
@admin_required
def delete_topic(topic_id):
    db = get_db()
    db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    db.commit()
    flash("Tópico excluído.", "success")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# CRUD de Subtópicos (admin)
# ----------------------------------------------------------------------

@app.route("/topico/<int:topic_id>/subtopico/novo", methods=["GET", "POST"])
@login_required
@admin_required
def new_subtopic(topic_id):
    db = get_db()
    topic = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        if not title:
            flash("O título é obrigatório.", "error")
        else:
            max_pos = db.execute(
                "SELECT COALESCE(MAX(position), -1) AS m FROM subtopics WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()["m"]
            db.execute(
                "INSERT INTO subtopics (topic_id, title, content, position) VALUES (?, ?, ?, ?)",
                (topic_id, title, content, max_pos + 1),
            )
            db.commit()
            flash("Subtópico criado!", "success")
            return redirect(url_for("view_topic", topic_id=topic_id))
    return render_page(FORM_SUBTOPIC_BODY, page_title="Novo subtópico", topic=topic, sub=None)


@app.route("/topico/<int:topic_id>/subtopico/<int:sub_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def edit_subtopic(topic_id, sub_id):
    db = get_db()
    topic = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    sub = db.execute(
        "SELECT * FROM subtopics WHERE id = ? AND topic_id = ?", (sub_id, topic_id)
    ).fetchone()
    if not topic or not sub:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        if not title:
            flash("O título é obrigatório.", "error")
        else:
            db.execute(
                "UPDATE subtopics SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, datetime.now().strftime("%Y-%m-%d %H:%M"), sub_id),
            )
            db.commit()
            flash("Subtópico atualizado!", "success")
            return redirect(url_for("view_subtopic", topic_id=topic_id, sub_id=sub_id))
    return render_page(FORM_SUBTOPIC_BODY, page_title="Editar subtópico", topic=topic, sub=sub)


@app.route("/topico/<int:topic_id>/subtopico/<int:sub_id>/excluir", methods=["POST"])
@login_required
@admin_required
def delete_subtopic(topic_id, sub_id):
    db = get_db()
    db.execute("DELETE FROM subtopics WHERE id = ? AND topic_id = ?", (sub_id, topic_id))
    db.commit()
    flash("Subtópico excluído.", "success")
    return redirect(url_for("view_topic", topic_id=topic_id))


# ----------------------------------------------------------------------
# Erros
# ----------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_page("<div class='panel'><h2>Acesso negado</h2><p>Você não tem permissão para acessar esta página.</p></div>", page_title="Acesso negado"), 403


@app.errorhandler(404)
def not_found(e):
    return render_page("<div class='panel'><h2>Página não encontrada</h2><p><a href='" + url_for('index') + "'>Voltar ao início</a></p></div>", page_title="Não encontrado"), 404


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

# Garante que o banco existe mesmo quando rodado via gunicorn (produção)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
