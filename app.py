
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
import uuid
import json
import re as _re
from datetime import datetime

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, g, abort, send_from_directory
)
from werkzeug.utils import secure_filename
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "wiki.db")

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("WIKI_SECRET_KEY", "troque-esta-chave-em-producao-por-favor")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB max por upload


def allowed_image(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def save_uploaded_image(file_storage):
    """Salva a imagem enviada e retorna o nome do arquivo salvo, ou None."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_image(file_storage.filename):
        flash("Formato de imagem não suportado. Use PNG, JPG, GIF ou WEBP.", "error")
        return None
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(UPLOAD_DIR, new_name))
    return new_name

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
            image TEXT,
            position INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sheet_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            schema_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            template_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (template_id) REFERENCES sheet_templates(id) ON DELETE CASCADE
        )
    """)
    db.commit()

    # Migração: adiciona a coluna 'image' em bancos já existentes
    existing_cols = [row[1] for row in db.execute("PRAGMA table_info(subtopics)").fetchall()]
    if "image" not in existing_cols:
        db.execute("ALTER TABLE subtopics ADD COLUMN image TEXT")
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

        # Modelo de ficha de exemplo (baseado na planilha Scion)
        default_schema = [
            {"key": "nome", "label": "Nome", "type": "text", "section": "Informações Básicas"},
            {"key": "jogador", "label": "Jogador", "type": "text", "section": "Informações Básicas"},
            {"key": "origem", "label": "Origem", "type": "text", "section": "Informações Básicas"},
            {"key": "ocupacao", "label": "Ocupação", "type": "text", "section": "Informações Básicas"},
            {"key": "panteao", "label": "Panteão", "type": "text", "section": "Informações Básicas"},
            {"key": "forca", "label": "Força", "type": "number", "section": "Atributos Físicos"},
            {"key": "destreza", "label": "Destreza", "type": "number", "section": "Atributos Físicos"},
            {"key": "vigor", "label": "Vigor", "type": "number", "section": "Atributos Físicos"},
            {"key": "carisma", "label": "Carisma", "type": "number", "section": "Atributos Sociais"},
            {"key": "manipulacao", "label": "Manipulação", "type": "number", "section": "Atributos Sociais"},
            {"key": "aparencia", "label": "Aparência", "type": "number", "section": "Atributos Sociais"},
            {"key": "percepcao", "label": "Percepção", "type": "number", "section": "Atributos Mentais"},
            {"key": "inteligencia", "label": "Inteligência", "type": "number", "section": "Atributos Mentais"},
            {"key": "raciocinio", "label": "Raciocínio", "type": "number", "section": "Atributos Mentais"},
            {"key": "academicos", "label": "Acadêmicos", "type": "number", "section": "Perícias"},
            {"key": "atletismo", "label": "Atletismo", "type": "number", "section": "Perícias"},
            {"key": "combate_corpo_a_corpo", "label": "Combate Corpo a Corpo", "type": "number", "section": "Perícias"},
            {"key": "cultura", "label": "Cultura", "type": "number", "section": "Perícias"},
            {"key": "empatia", "label": "Empatia", "type": "number", "section": "Perícias"},
            {"key": "armas_de_fogo", "label": "Armas de Fogo", "type": "number", "section": "Perícias"},
            {"key": "integridade", "label": "Integridade", "type": "number", "section": "Perícias"},
            {"key": "lideranca", "label": "Liderança", "type": "number", "section": "Perícias"},
            {"key": "medicina", "label": "Medicina", "type": "number", "section": "Perícias"},
            {"key": "ocultismo", "label": "Ocultismo", "type": "number", "section": "Perícias"},
            {"key": "persuasao", "label": "Persuasão", "type": "number", "section": "Perícias"},
            {"key": "pilotagem", "label": "Pilotagem", "type": "number", "section": "Perícias"},
            {"key": "ciencia", "label": "Ciência", "type": "number", "section": "Perícias"},
            {"key": "subterfugio", "label": "Subterfúgio", "type": "number", "section": "Perícias"},
            {"key": "sobrevivencia", "label": "Sobrevivência", "type": "number", "section": "Perícias"},
            {"key": "tecnologia", "label": "Tecnologia", "type": "number", "section": "Perícias"},
            {"key": "vida", "label": "Vida (atual/máx)", "type": "text", "section": "Status"},
            {"key": "empenho", "label": "Empenho (atual/máx)", "type": "text", "section": "Status"},
            {"key": "eter", "label": "Éter (atual/máx)", "type": "text", "section": "Status"},
            {"key": "lucidez", "label": "Lucidez (atual/máx)", "type": "text", "section": "Status"},
            {"key": "armas", "label": "Armas (nome, ataque, tipo, dano)", "type": "textarea", "section": "Equipamento"},
            {"key": "armadura", "label": "Armadura (tipo, defesa, outros)", "type": "textarea", "section": "Equipamento"},
            {"key": "habilidades", "label": "Habilidades", "type": "textarea", "section": "Poderes"},
            {"key": "magias", "label": "Magias (nome, energia, magia, efeito, dano/cura, gasto, detalhes)", "type": "textarea", "section": "Poderes"},
            {"key": "anotacoes", "label": "Anotações", "type": "textarea", "section": "Outros"},
        ]
        db.execute(
            "INSERT INTO sheet_templates (name, schema_json) VALUES (?, ?)",
            ("Ficha Scion", json.dumps(default_schema, ensure_ascii=False)),
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
  .search-form { display: flex; gap: 6px; align-items: center; }
  .search-form input[type=text] { margin: 0; width: 220px; }
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
  <h1><a href="{{ url_for('home') }}">📜 {{ site_title }}</a></h1>
  <form class="search-form" method="get" action="{{ url_for('search') }}">
    <input type="text" name="q" placeholder="Pesquisar subtópico..." value="{{ request.args.get('q', '') }}" style="margin:0; width:220px;">
    <button class="btn" type="submit" style="padding:8px 14px;">Buscar</button>
  </form>
  <nav>
    <a href="{{ url_for('home') }}">Início</a>
    <a href="{{ url_for('wiki_index') }}">Wiki</a>
    {% if current_user.is_authenticated %}
      <a href="{{ url_for('my_sheets') }}">Minhas Fichas</a>
    {% endif %}
    {% if current_user.is_authenticated and current_user.is_admin %}
      <a href="{{ url_for('new_topic') }}">+ Novo Tópico</a>
      <a href="{{ url_for('admin_templates') }}">Modelos de Ficha</a>
      <a href="{{ url_for('admin_sheets') }}">Todas as Fichas</a>
      <a href="{{ url_for('change_password') }}">Trocar senha</a>
      <a href="{{ url_for('logout') }}">Sair ({{ current_user.username }})</a>
    {% elif current_user.is_authenticated %}
      <a href="{{ url_for('change_password') }}">Trocar senha</a>
      <a href="{{ url_for('logout') }}">Sair ({{ current_user.username }})</a>
    {% else %}
      <a href="{{ url_for('login') }}">Entrar</a>
      <a href="{{ url_for('register') }}">Criar conta</a>
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
<footer>Feito por: Vinicius Daniel Boni</footer>
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
  <h2 style="margin-top:0;">Bem-vindo(a) à Wiki de Ascensão!</h2>
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

SEARCH_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Resultados da pesquisa</h2>
  {% if query %}
    <p>{{ results|length }} subtópico(s) encontrado(s) para "<strong>{{ query }}</strong>".</p>
  {% else %}
    <p>Digite um termo no campo de busca acima para procurar por subtópicos.</p>
  {% endif %}
</div>

{% if query and not results %}
  <div class="panel">Nenhum subtópico encontrado com esse nome.</div>
{% endif %}

{% for r in results %}
  <div class="topic-card">
    <div class="breadcrumb" style="margin-bottom:6px;"><a href="{{ url_for('view_topic', topic_id=r['topic_id']) }}">{{ r['topic_title'] }}</a></div>
    <h2 style="font-size:1.2em;"><a href="{{ url_for('view_subtopic', topic_id=r['topic_id'], sub_id=r['id']) }}">{{ r['title'] }}</a></h2>
    <p class="desc">{{ r['content'][:180] }}{% if r['content']|length > 180 %}...{% endif %}</p>
  </div>
{% endfor %}
"""

TOPIC_BODY = """
<div class="breadcrumb"><a href="{{ url_for('wiki_index') }}">Início</a> &raquo; {{ topic['title'] }}</div>
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
  <a href="{{ url_for('wiki_index') }}">Início</a> &raquo;
  <a href="{{ url_for('view_topic', topic_id=topic['id']) }}">{{ topic['title'] }}</a> &raquo;
  {{ sub['title'] }}
</div>
<div class="panel">
  <h2 style="margin-top:0;">{{ sub['title'] }}</h2>
  {% if sub['image'] %}
    <img src="{{ url_for('uploaded_file', filename=sub['image']) }}" alt="{{ sub['title'] }}" style="max-width:100%; border-radius:8px; border:1px solid var(--border); margin-bottom:16px;">
  {% endif %}
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
    <a class="btn btn-secondary" href="{{ url_for('wiki_index') }}">Cancelar</a>
  </form>
</div>
"""

FORM_SUBTOPIC_BODY = """
<div class="breadcrumb"><a href="{{ url_for('wiki_index') }}">Início</a> &raquo; <a href="{{ url_for('view_topic', topic_id=topic['id']) }}">{{ topic['title'] }}</a></div>
<div class="panel">
  <h2 style="margin-top:0;">{{ 'Editar' if sub else 'Novo' }} Subtópico em "{{ topic['title'] }}"</h2>
  <form method="post" enctype="multipart/form-data">
    <label>Título</label>
    <input type="text" name="title" required value="{{ sub['title'] if sub else '' }}">
    <label>Conteúdo</label>
    <textarea name="content" placeholder="Escreva aqui a história, descrição, regras, etc.">{{ sub['content'] if sub else '' }}</textarea>
    <label>Imagem (opcional, apenas admin)</label>
    {% if sub and sub['image'] %}
      <div style="margin-bottom:10px;">
        <img src="{{ url_for('uploaded_file', filename=sub['image']) }}" alt="imagem atual" style="max-width:220px; border-radius:8px; border:1px solid var(--border); display:block; margin-bottom:8px;">
        <label style="font-weight:normal; color:var(--muted);"><input type="checkbox" name="remove_image" value="1" style="width:auto; margin-right:6px;">Remover imagem atual</label>
      </div>
    {% endif %}
    <input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp">
    <button class="btn" type="submit">Salvar</button>
    <a class="btn btn-secondary" href="{{ url_for('view_topic', topic_id=topic['id']) }}">Cancelar</a>
  </form>
</div>
"""

HOME_BODY = """
<div class="panel" style="text-align:center;">
  <h2 style="margin-top:0;">Bem-vindo(a), aventureiro(a)!</h2>
  <p>O que você deseja fazer?</p>
</div>
<div style="display:flex; gap:20px; flex-wrap:wrap; justify-content:center;">
  <a class="topic-card" href="{{ url_for('wiki_index') }}" style="flex:1; min-width:240px; text-align:center; text-decoration:none;">
    <h2 style="margin-top:0;">📚 Entrar na Wiki</h2>
    <p class="desc">Explore o mundo, tópicos e lore da campanha.</p>
  </a>
  {% if current_user.is_authenticated %}
  <a class="topic-card" href="{{ url_for('my_sheets') }}" style="flex:1; min-width:240px; text-align:center; text-decoration:none;">
    <h2 style="margin-top:0;">📜 Minhas Fichas</h2>
    <p class="desc">Veja e edite suas fichas de personagem.</p>
  </a>
  {% else %}
  <a class="topic-card" href="{{ url_for('login') }}" style="flex:1; min-width:240px; text-align:center; text-decoration:none;">
    <h2 style="margin-top:0;">📜 Entrar na Ficha</h2>
    <p class="desc">Faça login ou crie uma conta para acessar suas fichas de personagem.</p>
  </a>
  {% endif %}
</div>
"""

LOGIN_BODY = """
<div class="panel" style="max-width:400px; margin:40px auto;">
  <h2 style="margin-top:0;">Login</h2>
  <form method="post">
    <label>Usuário</label>
    <input type="text" name="username" required autofocus>
    <label>Senha</label>
    <input type="password" name="password" required>
    <button class="btn" type="submit">Entrar</button>
  </form>
  <p style="margin-top:14px; color:var(--muted);">Não tem conta? <a href="{{ url_for('register') }}">Criar conta</a></p>
</div>
"""

REGISTER_BODY = """
<div class="panel" style="max-width:400px; margin:40px auto;">
  <h2 style="margin-top:0;">Criar conta</h2>
  <form method="post">
    <label>Usuário</label>
    <input type="text" name="username" required autofocus>
    <label>Senha</label>
    <input type="password" name="password" required>
    <label>Confirmar senha</label>
    <input type="password" name="confirm_password" required>
    <button class="btn" type="submit">Criar conta</button>
  </form>
  <p style="margin-top:14px; color:var(--muted);">Já tem conta? <a href="{{ url_for('login') }}">Entrar</a></p>
</div>
"""

MY_SHEETS_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Minhas Fichas</h2>
  <div class="actions">
    <a class="btn" href="{{ url_for('new_sheet') }}">+ Nova ficha</a>
  </div>
</div>
{% if not sheets %}
  <div class="panel">Você ainda não tem nenhuma ficha.</div>
{% endif %}
{% for sh in sheets %}
  <div class="topic-card">
    <h2 style="font-size:1.2em;"><a href="{{ url_for('view_sheet', sheet_id=sh['id']) }}">{{ sh['name'] }}</a></h2>
    <p class="desc">Modelo: {{ sh['template_name'] }} &bull; Atualizado em {{ sh['updated_at'] }}</p>
    <div class="actions">
      <a class="btn btn-secondary" href="{{ url_for('view_sheet', sheet_id=sh['id']) }}">Abrir / Editar</a>
      <form class="inline" method="post" action="{{ url_for('delete_sheet', sheet_id=sh['id']) }}" onsubmit="return confirm('Excluir esta ficha?');">
        <button class="btn btn-danger" type="submit">Excluir</button>
      </form>
    </div>
  </div>
{% endfor %}
"""

NEW_SHEET_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Nova Ficha</h2>
  {% if not templates %}
    <p>Nenhum modelo de ficha disponível ainda. Peça para o administrador criar um.</p>
  {% else %}
  <form method="post">
    <label>Nome do personagem</label>
    <input type="text" name="name" required>
    <label>Modelo de ficha</label>
    <select name="template_id" required>
      {% for t in templates %}
        <option value="{{ t['id'] }}">{{ t['name'] }}</option>
      {% endfor %}
    </select>
    <button class="btn" type="submit">Criar ficha</button>
    <a class="btn btn-secondary" href="{{ url_for('my_sheets') }}">Cancelar</a>
  </form>
  {% endif %}
</div>
"""

SHEET_VIEW_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">{{ sheet['name'] }}</h2>
  <p class="desc">Modelo: {{ template['name'] }} &bull; Dono: {{ owner_username }} &bull; Atualizado em {{ sheet['updated_at'] }}</p>
  <form method="post">
    {% for section, fields in sections.items() %}
      <h3 style="color:var(--accent); border-bottom:1px solid var(--border); padding-bottom:4px; margin-top:24px;">{{ section }}</h3>
      {% for f in fields %}
        <label>{{ f['label'] }}</label>
        {% if f['type'] == 'textarea' %}
          <textarea name="field_{{ f['key'] }}" style="min-height:120px;">{{ data.get(f['key'], '') }}</textarea>
        {% elif f['type'] == 'number' %}
          <input type="number" name="field_{{ f['key'] }}" value="{{ data.get(f['key'], '') }}">
        {% else %}
          <input type="text" name="field_{{ f['key'] }}" value="{{ data.get(f['key'], '') }}">
        {% endif %}
      {% endfor %}
    {% endfor %}
    <div class="actions">
      <button class="btn" type="submit">Salvar ficha</button>
      <a class="btn btn-secondary" href="{{ url_for('my_sheets') if not is_admin_view else url_for('admin_sheets') }}">Voltar</a>
    </div>
  </form>
</div>
"""

ADMIN_SHEETS_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Todas as Fichas (Admin)</h2>
  <p>Como administrador você pode abrir e editar a ficha de qualquer jogador.</p>
</div>
{% if not sheets %}
  <div class="panel">Nenhuma ficha criada ainda.</div>
{% endif %}
{% for sh in sheets %}
  <div class="topic-card">
    <h2 style="font-size:1.2em;"><a href="{{ url_for('view_sheet', sheet_id=sh['id']) }}">{{ sh['name'] }}</a></h2>
    <p class="desc">Jogador: {{ sh['owner_username'] }} &bull; Modelo: {{ sh['template_name'] }} &bull; Atualizado em {{ sh['updated_at'] }}</p>
    <div class="actions">
      <a class="btn btn-secondary" href="{{ url_for('view_sheet', sheet_id=sh['id']) }}">Abrir / Editar</a>
      <form class="inline" method="post" action="{{ url_for('delete_sheet', sheet_id=sh['id']) }}" onsubmit="return confirm('Excluir esta ficha?');">
        <button class="btn btn-danger" type="submit">Excluir</button>
      </form>
    </div>
  </div>
{% endfor %}
"""

ADMIN_TEMPLATES_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Modelos de Ficha (Admin)</h2>
  <div class="actions">
    <a class="btn" href="{{ url_for('new_template') }}">+ Novo modelo</a>
  </div>
</div>
{% if not templates %}
  <div class="panel">Nenhum modelo criado ainda.</div>
{% endif %}
{% for t in templates %}
  <div class="topic-card">
    <h2 style="font-size:1.2em;">{{ t['name'] }}</h2>
    <p class="desc">{{ t['field_count'] }} campo(s) &bull; usado em {{ t['sheet_count'] }} ficha(s)</p>
    <div class="actions">
      <a class="btn btn-secondary" href="{{ url_for('edit_template', template_id=t['id']) }}">Editar campos</a>
      <form class="inline" method="post" action="{{ url_for('delete_template', template_id=t['id']) }}" onsubmit="return confirm('Excluir este modelo? Só é possível se não houver fichas usando ele.');">
        <button class="btn btn-danger" type="submit">Excluir</button>
      </form>
    </div>
  </div>
{% endfor %}
"""

EDIT_TEMPLATE_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Editar modelo: {{ template['name'] }}</h2>
  <p class="desc">Adicione, organize e remova os campos que vão aparecer nas fichas que usam este modelo.</p>
</div>

<div class="panel">
  <h3 style="margin-top:0;">Adicionar campo</h3>
  <form method="post" action="{{ url_for('add_template_field', template_id=template['id']) }}">
    <label>Seção (agrupamento)</label>
    <input type="text" name="section" placeholder="Ex: Atributos" required>
    <label>Rótulo do campo</label>
    <input type="text" name="label" placeholder="Ex: Força" required>
    <label>Tipo</label>
    <select name="type">
      <option value="text">Texto curto</option>
      <option value="number">Número</option>
      <option value="textarea">Texto longo</option>
    </select>
    <button class="btn" type="submit">Adicionar campo</button>
  </form>
</div>

{% for section, fields in sections.items() %}
  <div class="panel">
    <h3 style="margin-top:0; color:var(--accent);">{{ section }}</h3>
    <ul class="sub-list">
      {% for f in fields %}
        <li style="display:flex; justify-content:space-between; align-items:center;">
          <span>{{ f['label'] }} <span class="badge">{{ f['type'] }}</span></span>
          <form class="inline" method="post" action="{{ url_for('remove_template_field', template_id=template['id'], field_key=f['key']) }}" onsubmit="return confirm('Remover este campo? Dados já salvos nas fichas para esse campo serão perdidos.');">
            <button class="btn btn-danger" type="submit" style="padding:2px 10px; font-size:0.8em;">Remover</button>
          </form>
        </li>
      {% endfor %}
    </ul>
  </div>
{% endfor %}

<a class="btn btn-secondary" href="{{ url_for('admin_templates') }}">Voltar aos modelos</a>
"""

NEW_TEMPLATE_BODY = """
<div class="panel">
  <h2 style="margin-top:0;">Novo modelo de ficha</h2>
  <form method="post">
    <label>Nome do modelo</label>
    <input type="text" name="name" placeholder="Ex: Ficha de Vampiro" required>
    <button class="btn" type="submit">Criar modelo</button>
    <a class="btn btn-secondary" href="{{ url_for('admin_templates') }}">Cancelar</a>
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
def home():
    return render_page(HOME_BODY, page_title=None)


@app.route("/wiki")
def wiki_index():
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


@app.route("/pesquisar")
def search():
    query = request.args.get("q", "").strip()
    results = []
    if query:
        db = get_db()
        rows = db.execute(
            """
            SELECT s.id, s.title, s.content, s.topic_id, t.title AS topic_title
            FROM subtopics s
            JOIN topics t ON t.id = s.topic_id
            WHERE s.title LIKE ?
            ORDER BY t.position, t.id, s.position, s.id
            """,
            (f"%{query}%",),
        ).fetchall()
        results = [dict(r) for r in rows]
    return render_page(SEARCH_BODY, page_title="Pesquisar", query=query, results=results)


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
        return redirect(url_for("wiki_index"))
    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("wiki_index"))
        flash("Usuário ou senha inválidos.", "error")
    return render_page(LOGIN_BODY, page_title="Login")


@app.route("/registrar", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("wiki_index"))
    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not username or not password:
            flash("Usuário e senha são obrigatórios.", "error")
        elif len(password) < 4:
            flash("A senha deve ter pelo menos 4 caracteres.", "error")
        elif password != confirm_password:
            flash("As senhas não coincidem.", "error")
        else:
            existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                flash("Já existe uma conta com esse nome de usuário.", "error")
            else:
                pw_hash = generate_password_hash(password)
                cur = db.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                    (username, pw_hash),
                )
                db.commit()
                row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
                login_user(User(row))
                flash("Conta criada com sucesso! Bem-vindo(a).", "success")
                return redirect(url_for("my_sheets"))
    return render_page(REGISTER_BODY, page_title="Criar conta")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu da conta.", "success")
    return redirect(url_for("wiki_index"))


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
            return redirect(url_for("wiki_index"))
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
            return redirect(url_for("wiki_index"))
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
    return redirect(url_for("wiki_index"))


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
            image_name = save_uploaded_image(request.files.get("image"))
            max_pos = db.execute(
                "SELECT COALESCE(MAX(position), -1) AS m FROM subtopics WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()["m"]
            db.execute(
                "INSERT INTO subtopics (topic_id, title, content, image, position) VALUES (?, ?, ?, ?, ?)",
                (topic_id, title, content, image_name, max_pos + 1),
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
            image_name = sub["image"]
            new_image = save_uploaded_image(request.files.get("image"))
            if new_image:
                image_name = new_image
            elif request.form.get("remove_image") == "1":
                image_name = None
            db.execute(
                "UPDATE subtopics SET title = ?, content = ?, image = ?, updated_at = ? WHERE id = ?",
                (title, content, image_name, datetime.now().strftime("%Y-%m-%d %H:%M"), sub_id),
            )
            db.commit()
            flash("Subtópico atualizado!", "success")
            return redirect(url_for("view_subtopic", topic_id=topic_id, sub_id=sub_id))
    return render_page(FORM_SUBTOPIC_BODY, page_title="Editar subtópico", topic=topic, sub=sub)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


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
# Fichas de personagem
# ----------------------------------------------------------------------

def slugify_key(text, existing_keys):
    base = _re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_") or "campo"
    key = base
    i = 2
    while key in existing_keys:
        key = f"{base}_{i}"
        i += 1
    return key


def group_by_section(schema):
    sections = {}
    for f in schema:
        sections.setdefault(f.get("section") or "Geral", []).append(f)
    return sections


def get_template_or_404(db, template_id):
    row = db.execute("SELECT * FROM sheet_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        abort(404)
    return row


def get_sheet_or_404(db, sheet_id):
    row = db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,)).fetchone()
    if not row:
        abort(404)
    return row


@app.route("/fichas")
@login_required
def my_sheets():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, t.name AS template_name
        FROM sheets s JOIN sheet_templates t ON t.id = s.template_id
        WHERE s.user_id = ?
        ORDER BY s.updated_at DESC
        """,
        (current_user.id,),
    ).fetchall()
    return render_page(MY_SHEETS_BODY, page_title="Minhas Fichas", sheets=rows)


@app.route("/fichas/nova", methods=["GET", "POST"])
@login_required
def new_sheet():
    db = get_db()
    templates = db.execute("SELECT * FROM sheet_templates ORDER BY name").fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        template_id = request.form.get("template_id", "")
        template = db.execute("SELECT * FROM sheet_templates WHERE id = ?", (template_id,)).fetchone()
        if not name or not template:
            flash("Preencha o nome e escolha um modelo válido.", "error")
        else:
            db.execute(
                "INSERT INTO sheets (user_id, template_id, name, data_json) VALUES (?, ?, ?, ?)",
                (current_user.id, template["id"], name, "{}"),
            )
            db.commit()
            flash("Ficha criada!", "success")
            return redirect(url_for("my_sheets"))
    return render_page(NEW_SHEET_BODY, page_title="Nova ficha", templates=templates)


@app.route("/fichas/<int:sheet_id>", methods=["GET", "POST"])
@login_required
def view_sheet(sheet_id):
    db = get_db()
    sheet = get_sheet_or_404(db, sheet_id)
    if sheet["user_id"] != current_user.id and not current_user.is_admin:
        abort(403)
    template = get_template_or_404(db, sheet["template_id"])
    schema = json.loads(template["schema_json"])
    if request.method == "POST":
        data = {}
        for f in schema:
            data[f["key"]] = request.form.get(f"field_{f['key']}", "").strip()
        db.execute(
            "UPDATE sheets SET data_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d %H:%M"), sheet_id),
        )
        db.commit()
        flash("Ficha salva!", "success")
        return redirect(url_for("view_sheet", sheet_id=sheet_id))
    data = json.loads(sheet["data_json"])
    sections = group_by_section(schema)
    owner_row = db.execute("SELECT username FROM users WHERE id = ?", (sheet["user_id"],)).fetchone()
    return render_page(
        SHEET_VIEW_BODY,
        page_title=sheet["name"],
        sheet=sheet,
        template=template,
        sections=sections,
        data=data,
        owner_username=owner_row["username"] if owner_row else "?",
        is_admin_view=(sheet["user_id"] != current_user.id),
    )


@app.route("/fichas/<int:sheet_id>/excluir", methods=["POST"])
@login_required
def delete_sheet(sheet_id):
    db = get_db()
    sheet = get_sheet_or_404(db, sheet_id)
    if sheet["user_id"] != current_user.id and not current_user.is_admin:
        abort(403)
    db.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))
    db.commit()
    flash("Ficha excluída.", "success")
    return redirect(url_for("admin_sheets") if sheet["user_id"] != current_user.id else url_for("my_sheets"))


@app.route("/admin/fichas")
@login_required
@admin_required
def admin_sheets():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, t.name AS template_name, u.username AS owner_username
        FROM sheets s
        JOIN sheet_templates t ON t.id = s.template_id
        JOIN users u ON u.id = s.user_id
        ORDER BY s.updated_at DESC
        """
    ).fetchall()
    return render_page(ADMIN_SHEETS_BODY, page_title="Todas as Fichas", sheets=rows)


@app.route("/admin/modelos")
@login_required
@admin_required
def admin_templates():
    db = get_db()
    rows = db.execute("SELECT * FROM sheet_templates ORDER BY name").fetchall()
    templates = []
    for t in rows:
        schema = json.loads(t["schema_json"])
        sheet_count = db.execute(
            "SELECT COUNT(*) AS c FROM sheets WHERE template_id = ?", (t["id"],)
        ).fetchone()["c"]
        td = dict(t)
        td["field_count"] = len(schema)
        td["sheet_count"] = sheet_count
        templates.append(td)
    return render_page(ADMIN_TEMPLATES_BODY, page_title="Modelos de Ficha", templates=templates)


@app.route("/admin/modelos/novo", methods=["GET", "POST"])
@login_required
@admin_required
def new_template():
    if request.method == "POST":
        db = get_db()
        name = request.form.get("name", "").strip()
        if not name:
            flash("O nome do modelo é obrigatório.", "error")
        else:
            db.execute(
                "INSERT INTO sheet_templates (name, schema_json) VALUES (?, ?)",
                (name, "[]"),
            )
            db.commit()
            flash("Modelo criado! Agora adicione os campos.", "success")
            return redirect(url_for("admin_templates"))
    return render_page(NEW_TEMPLATE_BODY, page_title="Novo modelo")


@app.route("/admin/modelos/<int:template_id>/editar")
@login_required
@admin_required
def edit_template(template_id):
    db = get_db()
    template = get_template_or_404(db, template_id)
    schema = json.loads(template["schema_json"])
    sections = group_by_section(schema)
    return render_page(EDIT_TEMPLATE_BODY, page_title=f"Editar {template['name']}", template=template, sections=sections)


@app.route("/admin/modelos/<int:template_id>/campo/novo", methods=["POST"])
@login_required
@admin_required
def add_template_field(template_id):
    db = get_db()
    template = get_template_or_404(db, template_id)
    schema = json.loads(template["schema_json"])
    section = request.form.get("section", "Geral").strip() or "Geral"
    label = request.form.get("label", "").strip()
    field_type = request.form.get("type", "text")
    if field_type not in ("text", "number", "textarea"):
        field_type = "text"
    if not label:
        flash("O rótulo do campo é obrigatório.", "error")
    else:
        existing_keys = {f["key"] for f in schema}
        key = slugify_key(label, existing_keys)
        schema.append({"key": key, "label": label, "type": field_type, "section": section})
        db.execute(
            "UPDATE sheet_templates SET schema_json = ? WHERE id = ?",
            (json.dumps(schema, ensure_ascii=False), template_id),
        )
        db.commit()
        flash("Campo adicionado!", "success")
    return redirect(url_for("edit_template", template_id=template_id))


@app.route("/admin/modelos/<int:template_id>/campo/<field_key>/remover", methods=["POST"])
@login_required
@admin_required
def remove_template_field(template_id, field_key):
    db = get_db()
    template = get_template_or_404(db, template_id)
    schema = json.loads(template["schema_json"])
    schema = [f for f in schema if f["key"] != field_key]
    db.execute(
        "UPDATE sheet_templates SET schema_json = ? WHERE id = ?",
        (json.dumps(schema, ensure_ascii=False), template_id),
    )
    db.commit()
    flash("Campo removido.", "success")
    return redirect(url_for("edit_template", template_id=template_id))


@app.route("/admin/modelos/<int:template_id>/excluir", methods=["POST"])
@login_required
@admin_required
def delete_template(template_id):
    db = get_db()
    in_use = db.execute(
        "SELECT COUNT(*) AS c FROM sheets WHERE template_id = ?", (template_id,)
    ).fetchone()["c"]
    if in_use:
        flash("Não é possível excluir: existem fichas usando este modelo.", "error")
    else:
        db.execute("DELETE FROM sheet_templates WHERE id = ?", (template_id,))
        db.commit()
        flash("Modelo excluído.", "success")
    return redirect(url_for("admin_templates"))


# ----------------------------------------------------------------------
# Erros
# ----------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_page("<div class='panel'><h2>Acesso negado</h2><p>Você não tem permissão para acessar esta página.</p></div>", page_title="Acesso negado"), 403


@app.errorhandler(404)
def not_found(e):
    return render_page("<div class='panel'><h2>Página não encontrada</h2><p><a href='" + url_for('wiki_index') + "'>Voltar ao início</a></p></div>", page_title="Não encontrado"), 404


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

# Garante que o banco existe mesmo quando rodado via gunicorn (produção)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
