import os, sqlite3, csv, io
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash)
from PIL import Image
import pytesseract

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pastorDesertuna")
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
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nome          TEXT UNIQUE NOT NULL,
            nome_whatsapp TEXT DEFAULT ''
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
    try:
        with get_db() as con:
            con.execute("ALTER TABLE elementos ADD COLUMN nome_whatsapp TEXT DEFAULT ''")
    except Exception:
        pass

with app.app_context():
    init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
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

# ── Index ─────────────────────────────────────────────────────────────────────

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
    nome = request.form.get("nome", "").strip()
    nwa  = request.form.get("nome_whatsapp", "").strip()
    if nome:
        try:
            with get_db() as con:
                con.execute("INSERT INTO elementos (nome, nome_whatsapp) VALUES (?,?)", (nome, nwa))
        except sqlite3.IntegrityError:
            flash(f"'{nome}' ja existe.")
    return redirect(url_for("elementos"))

@app.route("/elementos/edit/<int:eid>", methods=["POST"])
@login_required
def edit_elemento(eid):
    nwa = request.form.get("nome_whatsapp", "").strip()
    with get_db() as con:
        con.execute("UPDATE elementos SET nome_whatsapp=? WHERE id=?", (nwa, eid))
    return redirect(url_for("elementos"))

@app.route("/elementos/del/<int:eid>", methods=["POST"])
@login_required
def del_elemento(eid):
    with get_db() as con:
        con.execute("DELETE FROM elementos WHERE id=?", (eid,))
    return redirect(url_for("elementos"))

# ── Eventos ───────────────────────────────────────────────────────────────────

@app.route("/eventos/novo", methods=["GET", "POST"])
@login_required
def novo_evento():
    if request.method == "POST":
        nome   = request.form.get("nome", "").strip()
        opcoes = request.form.get("opcoes", "").strip()
        if nome and opcoes:
            with get_db() as con:
                con.execute(
                    "INSERT INTO eventos (nome, opcoes, criado) VALUES (?,?,?)",
                    (nome, opcoes, datetime.now().strftime("%d/%m/%Y"))
                )
            return redirect(url_for("index"))
        flash("Preenche o nome e as opcoes.")
    return render_template("novo_evento.html")

@app.route("/eventos/<int:eid>/del", methods=["POST"])
@login_required
def del_evento(eid):
    with get_db() as con:
        con.execute("DELETE FROM respostas WHERE evento_id=?", (eid,))
        con.execute("DELETE FROM eventos WHERE id=?", (eid,))
    return redirect(url_for("index"))

# ── Evento / Respostas ────────────────────────────────────────────────────────

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
    opcao   = request.form.get("opcao", "").strip()
    if elem_id:
        with get_db() as con:
            con.execute("""
                INSERT INTO respostas (evento_id, elemento_id, opcao)
                VALUES (?,?,?)
                ON CONFLICT(evento_id, elemento_id)
                DO UPDATE SET opcao=excluded.opcao
            """, (eid, elem_id, opcao))
    return redirect(url_for("evento", eid=eid))

# ── Lógica de importação CSV (partilhada) ─────────────────────────────────────

def parse_csv(file_stream):
    """Lê o CSV do script WhatsApp e devolve (titulo, opcoes, votos).
    votos = [ {nome_csv, opcao}, ... ]
    """
    stream = io.StringIO(file_stream.read().decode("utf-8-sig"))
    reader = csv.reader(stream)

    titulo      = ""
    opcoes_set  = []
    votos       = []
    opcao_atual = None

    for row in reader:
        if not row:
            continue
        col0 = row[0].strip() if len(row) > 0 else ""
        col1 = row[1].strip() if len(row) > 1 else ""

        # Linha do título da sondagem
        if col0 == "Sondagem":
            titulo = col1
            continue

        # Cabeçalho ou linha vazia
        if col0 in ("Opcao", "Opção", "") and col1 in ("Nome", ""):
            continue

        # Linha com opção e nome
        if col0:
            opcao_atual = col0
            if opcao_atual not in opcoes_set:
                opcoes_set.append(opcao_atual)

        nome_csv = col1
        if not opcao_atual or not nome_csv or nome_csv == "(sem votos)":
            continue

        votos.append({"nome": nome_csv, "opcao": opcao_atual})

    return titulo, opcoes_set, votos


def aplicar_votos(evento_id, votos):
    """Cruza nomes do CSV com elementos da BD e guarda respostas."""
    with get_db() as con:
        elems = con.execute("SELECT id, nome, nome_whatsapp FROM elementos").fetchall()

    elem_index = {e["nome"].lower().strip(): e["id"] for e in elems}
    elem_wa    = {e["nome_whatsapp"].lower().strip(): e["id"]
                  for e in elems if e["nome_whatsapp"]}
    elem_first = {}
    for e in elems:
        primeiro = e["nome"].lower().split()[0]
        if primeiro not in elem_first:
            elem_first[primeiro] = e["id"]

    def encontrar(n):
        n = n.lower().strip()
        if n in elem_wa:    return elem_wa[n]
        if n in elem_index: return elem_index[n]
        for k, v in elem_wa.items():
            if n in k or k in n: return v
        for k, v in elem_index.items():
            if n in k or k in n: return v
        return elem_first.get(n.split()[0])

    registados      = 0
    nao_encontrados = []
    for voto in votos:
        elem_id = encontrar(voto["nome"])
        if elem_id:
            with get_db() as con:
                con.execute("""
                    INSERT INTO respostas (evento_id, elemento_id, opcao)
                    VALUES (?,?,?)
                    ON CONFLICT(evento_id, elemento_id)
                    DO UPDATE SET opcao=excluded.opcao
                """, (evento_id, elem_id, voto["opcao"]))
            registados += 1
        else:
            nao_encontrados.append(voto["nome"])

    return registados, nao_encontrados

# ── Importar CSV — criar novo evento ─────────────────────────────────────────

@app.route("/importar-csv", methods=["POST"])
@login_required
def importar_csv_novo():
    file = request.files.get("csv_file")
    if not file:
        flash("Nenhum ficheiro enviado.")
        return redirect(url_for("index"))

    titulo, opcoes, votos = parse_csv(file)

    if not titulo:
        flash("Nao foi possivel ler o titulo da sondagem no CSV.")
        return redirect(url_for("index"))

    # Criar o evento
    with get_db() as con:
        cur = con.execute(
            "INSERT INTO eventos (nome, opcoes, criado) VALUES (?,?,?)",
            (titulo, "\n".join(opcoes), datetime.now().strftime("%d/%m/%Y %H:%M"))
        )
        evento_id = cur.lastrowid

    registados, nao_encontrados = aplicar_votos(evento_id, votos)

    msg = f"Evento '{titulo}' criado com {registados} resposta(s)."
    if nao_encontrados:
        msg += f" Nao encontrados: {', '.join(set(nao_encontrados))}"
    flash(msg)
    return redirect(url_for("evento", eid=evento_id))

# ── Importar CSV — atualizar evento existente ─────────────────────────────────

@app.route("/eventos/<int:eid>/importar-csv", methods=["POST"])
@login_required
def importar_csv_update(eid):
    file = request.files.get("csv_file")
    if not file:
        flash("Nenhum ficheiro enviado.")
        return redirect(url_for("evento", eid=eid))

    _, _, votos = parse_csv(file)
    registados, nao_encontrados = aplicar_votos(eid, votos)

    msg = f"{registados} resposta(s) atualizadas."
    if nao_encontrados:
        msg += f" Nao encontrados: {', '.join(set(nao_encontrados))}"
    flash(msg)
    return redirect(url_for("evento", eid=eid))

# ── Tabela ────────────────────────────────────────────────────────────────────

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