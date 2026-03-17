import os, re, sqlite3, base64
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, flash)
from PIL import Image
import pytesseract
import io

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tuna-secret-key-muda-isto")

PASSWORD = os.environ.get("APP_PASSWORD", "tuna2025")
DB = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "tuna.db"))

# ── Base de dados ─────────────────────────────────────────────────────────────


def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with get_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS elementos (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eventos (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nome   TEXT NOT NULL,
            opcoes TEXT NOT NULL,
            criado TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS respostas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id   INTEGER NOT NULL,
            elemento_id INTEGER NOT NULL,
            opcao       TEXT NOT NULL,
            UNIQUE(evento_id, elemento_id),
            FOREIGN KEY(evento_id)   REFERENCES eventos(id),
            FOREIGN KEY(elemento_id) REFERENCES elementos(id)
        );
        """)

# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["auth"] = True
            return redirect(url_for("index"))
        flash("Password incorreta.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Páginas principais ────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    with get_db() as con:
        eventos = con.execute("SELECT * FROM eventos ORDER BY id DESC").fetchall()
    return render_template("index.html", eventos=eventos)

# ── Elementos ─────────────────────────────────────────────────────────────────

@app.route("/elementos")
@login_required
def elementos():
    with get_db() as con:
        elems = con.execute("SELECT * FROM elementos ORDER BY nome").fetchall()
    return render_template("elementos.html", elementos=elems)

@app.route("/elementos/add", methods=["POST"])
@login_required
def add_elemento():
    nome = request.form.get("nome","").strip()
    if nome:
        try:
            with get_db() as con:
                con.execute("INSERT INTO elementos (nome) VALUES (?)", (nome,))
        except sqlite3.IntegrityError:
            flash(f"'{nome}' já existe.")
    return redirect(url_for("elementos"))

@app.route("/elementos/del/<int:eid>", methods=["POST"])
@login_required
def del_elemento(eid):
    with get_db() as con:
        con.execute("DELETE FROM elementos WHERE id=?", (eid,))
    return redirect(url_for("elementos"))

# ── Eventos ───────────────────────────────────────────────────────────────────

@app.route("/eventos/novo", methods=["GET","POST"])
@login_required
def novo_evento():
    if request.method == "POST":
        nome   = request.form.get("nome","").strip()
        opcoes = request.form.get("opcoes","").strip()
        if nome and opcoes:
            with get_db() as con:
                con.execute(
                    "INSERT INTO eventos (nome, opcoes, criado) VALUES (?,?,?)",
                    (nome, opcoes, datetime.now().strftime("%d/%m/%Y"))
                )
            return redirect(url_for("index"))
        flash("Preenche o nome e as opções.")
    return render_template("novo_evento.html")

@app.route("/eventos/<int:eid>/del", methods=["POST"])
@login_required
def del_evento(eid):
    with get_db() as con:
        con.execute("DELETE FROM respostas WHERE evento_id=?", (eid,))
        con.execute("DELETE FROM eventos WHERE id=?", (eid,))
    return redirect(url_for("index"))

# ── Sondagem / Respostas ──────────────────────────────────────────────────────

@app.route("/eventos/<int:eid>")
@login_required
def evento(eid):
    with get_db() as con:
        ev    = con.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        elems = con.execute("SELECT * FROM elementos ORDER BY nome").fetchall()
        resps = con.execute(
            "SELECT elemento_id, opcao FROM respostas WHERE evento_id=?", (eid,)
        ).fetchall()
    if not ev:
        return redirect(url_for("index"))
    opcoes   = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    resp_map = {r["elemento_id"]: r["opcao"] for r in resps}
    return render_template("evento.html", ev=ev, elementos=elems,
                           opcoes=opcoes, resp_map=resp_map)

@app.route("/eventos/<int:eid>/resposta", methods=["POST"])
@login_required
def set_resposta(eid):
    elem_id = request.form.get("elemento_id")
    opcao   = request.form.get("opcao","").strip()
    if elem_id:
        with get_db() as con:
            con.execute("""
                INSERT INTO respostas (evento_id, elemento_id, opcao)
                VALUES (?,?,?)
                ON CONFLICT(evento_id, elemento_id)
                DO UPDATE SET opcao=excluded.opcao
            """, (eid, elem_id, opcao))
    return redirect(url_for("evento", eid=eid))

# ── OCR Screenshot ────────────────────────────────────────────────────────────

@app.route("/eventos/<int:eid>/ocr", methods=["POST"])
@login_required
def ocr_screenshot(eid):
    file = request.files.get("screenshot")
    if not file:
        return jsonify({"error": "Nenhum ficheiro enviado"}), 400

    img  = Image.open(file.stream)
    text = pytesseract.image_to_string(img, lang="por+eng")

    with get_db() as con:
        ev    = con.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        elems = con.execute("SELECT id, nome FROM elementos ORDER BY nome").fetchall()

    opcoes = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    lines  = [l.strip() for l in text.splitlines() if l.strip()]

    # Tentar detetar qual opção está a ser mostrada no screenshot
    opcao_detetada = None
    for op in opcoes:
        if any(op.lower() in l.lower() for l in lines[:6]):
            opcao_detetada = op
            break

    # Tentar cruzar nomes no OCR com elementos registados
    matches = []
    for elem in elems:
        nome_parts = elem["nome"].lower().split()
        for line in lines:
            line_lower = line.lower()
            if any(part in line_lower for part in nome_parts if len(part) > 2):
                matches.append({"id": elem["id"], "nome": elem["nome"], "linha": line})
                break

    return jsonify({
        "texto_ocr":     text,
        "linhas":        lines,
        "opcao_detetada": opcao_detetada,
        "matches":       matches
    })

@app.route("/eventos/<int:eid>/ocr/confirmar", methods=["POST"])
@login_required
def ocr_confirmar(eid):
    data = request.get_json()
    opcao    = data.get("opcao","")
    elem_ids = data.get("elemento_ids", [])
    with get_db() as con:
        for eid2 in elem_ids:
            con.execute("""
                INSERT INTO respostas (evento_id, elemento_id, opcao)
                VALUES (?,?,?)
                ON CONFLICT(evento_id, elemento_id)
                DO UPDATE SET opcao=excluded.opcao
            """, (eid, eid2, opcao))
    return jsonify({"ok": True})

# ── Tabela resumo ─────────────────────────────────────────────────────────────

@app.route("/eventos/<int:eid>/tabela")
@login_required
def tabela(eid):
    with get_db() as con:
        ev    = con.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        elems = con.execute("SELECT * FROM elementos ORDER BY nome").fetchall()
        resps = con.execute(
            "SELECT elemento_id, opcao FROM respostas WHERE evento_id=?", (eid,)
        ).fetchall()
    if not ev:
        return redirect(url_for("index"))
    opcoes   = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    resp_map = {r["elemento_id"]: r["opcao"] for r in resps}
    totais   = {op: sum(1 for v in resp_map.values() if v == op) for op in opcoes}
    sem_resp = sum(1 for e in elems if e["id"] not in resp_map)
    return render_template("tabela.html", ev=ev, elementos=elems,
                           opcoes=opcoes, resp_map=resp_map,
                           totais=totais, sem_resp=sem_resp)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)