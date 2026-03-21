import os, sqlite3, csv, io, libsql_experimental as libsql
from datetime import datetime, date
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)
PASSWORD    = os.environ.get("APP_PASSWORD")
TURSO_URL   = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

HIERARQUIA = ["Xeque", "Camelo", "Ali-Bobó"]

# ── Base de dados ─────────────────────────────────────────────────────────────

class DictRow(dict):
    def __getattr__(self, name):
        return self[name]

def dict_factory(cursor, row):
    return DictRow(zip([d[0] for d in cursor.description], row))

class TursoConnection:
    def __init__(self, con):
        self._con = con

    def execute(self, sql, params=()):
        cursor = self._con.execute(sql, params)
        return self._wrap_cursor(cursor)

    def executescript(self, sql):
        return self._con.executescript(sql)

    def _wrap_cursor(self, cursor):
        rows = cursor.fetchall()
        desc = cursor.description or []
        cols = [d[0] for d in desc]
        lastrowid = cursor.lastrowid

        class WrappedCursor:
            def fetchall(self):
                return [DictRow(zip(cols, row)) for row in rows]
            def fetchone(self):
                if rows:
                    return DictRow(zip(cols, rows[0]))
                return None
            @property
            def lastrowid(self):
                return lastrowid

        return WrappedCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._con.commit()

def get_db():
    if TURSO_URL and TURSO_TOKEN:
        con = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
        return TursoConnection(con)
    else:
        con = sqlite3.connect("tuna.db")
        con.row_factory = dict_factory
        return con

def init_db():
    with get_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS elementos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nome          TEXT UNIQUE NOT NULL,
            nome_whatsapp TEXT DEFAULT '',
            categoria     TEXT DEFAULT 'Ali-Bobó',
            ordem         INTEGER DEFAULT 0,
            ativo         INTEGER DEFAULT 1,
            instrumento   TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS eventos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT NOT NULL,
            opcoes      TEXT NOT NULL,
            criado      TEXT NOT NULL,
            data_evento TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS respostas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id   INTEGER NOT NULL,
            elemento_id INTEGER NOT NULL,
            opcao       TEXT NOT NULL,
            UNIQUE(evento_id, elemento_id, opcao),
            FOREIGN KEY(evento_id)   REFERENCES eventos(id),
            FOREIGN KEY(elemento_id) REFERENCES elementos(id)
        );
        CREATE TABLE IF NOT EXISTS ensaios (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            data    TEXT NOT NULL,
            criado  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS presencas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ensaio_id   INTEGER NOT NULL,
            elemento_id INTEGER NOT NULL,
            estado      TEXT NOT NULL DEFAULT 'sem-registo',
            hora        TEXT DEFAULT '',
            nota        TEXT DEFAULT '',
            UNIQUE(ensaio_id, elemento_id),
            FOREIGN KEY(ensaio_id)   REFERENCES ensaios(id),
            FOREIGN KEY(elemento_id) REFERENCES elementos(id)
        );
        """)
    # migrações seguras para bases de dados existentes
    for col in [
        "nome_whatsapp TEXT DEFAULT ''",
        "categoria TEXT DEFAULT 'Ali-Bobó'",
        "ordem INTEGER DEFAULT 0",
        "ativo INTEGER DEFAULT 1",
        "instrumento TEXT DEFAULT ''",
    ]:
        try:
            with get_db() as con:
                con.execute(f"ALTER TABLE elementos ADD COLUMN {col}")
        except Exception:
            pass

    # migração: adicionar data_evento à tabela eventos
    try:
        with get_db() as con:
            con.execute("ALTER TABLE eventos ADD COLUMN data_evento TEXT DEFAULT ''")
    except Exception:
        pass

    # migração: recriar tabela respostas com UNIQUE(evento_id, elemento_id, opcao)
    # para suportar múltiplas opções por pessoa
    try:
        with get_db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS respostas_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id   INTEGER NOT NULL,
                    elemento_id INTEGER NOT NULL,
                    opcao       TEXT NOT NULL,
                    UNIQUE(evento_id, elemento_id, opcao),
                    FOREIGN KEY(evento_id)   REFERENCES eventos(id),
                    FOREIGN KEY(elemento_id) REFERENCES elementos(id)
                );
                INSERT OR IGNORE INTO respostas_new (evento_id, elemento_id, opcao)
                    SELECT evento_id, elemento_id, opcao FROM respostas;
                DROP TABLE respostas;
                ALTER TABLE respostas_new RENAME TO respostas;
            """)
    except Exception:
        pass

@app.template_filter('format_date')
def format_date_filter(data_str):
    try:
        d = datetime.strptime(data_str, "%Y-%m-%d")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        return f"{dias[d.weekday()]}, {d.strftime('%d/%m/%Y')}"
    except Exception:
        return data_str


# Meses em português para extração de datas dos nomes de eventos
_MESES = {
    "jan":1,"fev":2,"mar":3,"abr":4,"mai":5,"jun":6,
    "jul":7,"ago":8,"set":9,"out":10,"nov":11,"dez":12,
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

def extrair_data_nome(nome):
    """Tenta extrair uma data de um nome de evento como '27/MAR', '14/JUN', '(29/Mar, Domingo)' etc.
    Devolve um objeto date ou None."""
    import re
    nome_lower = nome.lower()
    # padrão: número/mês (ex: 27/mar, 14/jun, 29/mar)
    m = re.search(r'(\d{1,2})[/\-\.](\w{3,})', nome_lower)
    if m:
        dia = int(m.group(1))
        mes_str = m.group(2)[:3]
        mes = _MESES.get(mes_str)
        if mes:
            ano = date.today().year
            # se o mês já passou este ano, provavelmente é do próximo
            try:
                d = date(ano, mes, dia)
                if d < date.today() - __import__('datetime').timedelta(days=30):
                    d = date(ano + 1, mes, dia)
                return d
            except Exception:
                pass
    return None

@app.template_filter('proximidade_class')
def proximidade_class_filter(ev_nome):
    d = extrair_data_nome(ev_nome)
    if not d: return "data-futuro"
    diff = (d - date.today()).days
    if diff < 0:  return "data-passado"
    if diff == 0: return "data-hoje"
    if diff <= 7: return "data-semana"
    return "data-futuro"

@app.template_filter('proximidade_label')
def proximidade_label_filter(ev_nome):
    d = extrair_data_nome(ev_nome)
    if not d: return ""
    diff = (d - date.today()).days
    if diff < 0:  return f"há {-diff}d"
    if diff == 0: return "hoje"
    if diff == 1: return "amanhã"
    return f"daqui a {diff}d"

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
        eventos_raw = con.execute("SELECT * FROM eventos").fetchall()
    # ordenar por data extraída do nome (eventos sem data detectável ficam no fim)
    def sort_key(ev):
        d = extrair_data_nome(ev["nome"])
        return d if d else date(9999, 12, 31)
    eventos = sorted(eventos_raw, key=sort_key)
    return render_template("index.html", eventos=eventos)

# ── Elementos ─────────────────────────────────────────────────────────────────

@app.route("/elementos")
@login_required
def elementos():
    with get_db() as con:
        elems   = con.execute("SELECT * FROM elementos WHERE ativo=1 ORDER BY categoria, ordem, nome").fetchall()
        ex_memb = con.execute("SELECT * FROM elementos WHERE ativo=0 ORDER BY categoria, nome").fetchall()
    return render_template("elementos.html", elementos=elems, ex_membros=ex_memb,
                           hierarquia=HIERARQUIA)

@app.route("/elementos/add", methods=["POST"])
@login_required
def add_elemento():
    nome        = request.form.get("nome", "").strip()
    nwa         = request.form.get("nome_whatsapp", "").strip()
    categoria   = request.form.get("categoria", "Ali-Bobó").strip()
    instrumento = request.form.get("instrumento", "").strip()
    try:
        ordem = int(request.form.get("ordem", 0))
    except ValueError:
        ordem = 0
    if nome:
        try:
            with get_db() as con:
                con.execute(
                    "INSERT INTO elementos (nome, nome_whatsapp, categoria, ordem, instrumento) VALUES (?,?,?,?,?)",
                    (nome, nwa, categoria, ordem, instrumento)
                )
        except Exception:
            flash(f"'{nome}' ja existe.")
    return redirect(url_for("elementos"))

@app.route("/elementos/edit/<int:eid>", methods=["POST"])
@login_required
def edit_elemento(eid):
    nwa         = request.form.get("nome_whatsapp", "").strip()
    categoria   = request.form.get("categoria", "Ali-Bobó").strip()
    instrumento = request.form.get("instrumento", "").strip()
    try:
        ordem = int(request.form.get("ordem", 0))
    except ValueError:
        ordem = 0
    with get_db() as con:
        con.execute(
            "UPDATE elementos SET nome_whatsapp=?, categoria=?, ordem=?, instrumento=? WHERE id=?",
            (nwa, categoria, ordem, instrumento, eid)
        )
    return redirect(url_for("elementos"))

@app.route("/elementos/del/<int:eid>", methods=["POST"])
@login_required
def del_elemento(eid):
    """Soft delete — marca como inativo para preservar registos históricos."""
    with get_db() as con:
        con.execute("UPDATE elementos SET ativo=0 WHERE id=?", (eid,))
    return redirect(url_for("elementos"))

@app.route("/elementos/reativar/<int:eid>", methods=["POST"])
@login_required
def reativar_elemento(eid):
    with get_db() as con:
        con.execute("UPDATE elementos SET ativo=1 WHERE id=?", (eid,))
    return redirect(url_for("elementos"))

@app.route("/elementos/apagar/<int:eid>", methods=["POST"])
@login_required
def apagar_elemento(eid):
    """Hard delete — só para ex-membros, apaga tudo permanentemente."""
    with get_db() as con:
        con.execute("DELETE FROM presencas WHERE elemento_id=?", (eid,))
        con.execute("DELETE FROM respostas WHERE elemento_id=?", (eid,))
        con.execute("DELETE FROM elementos WHERE id=?", (eid,))
    return redirect(url_for("elementos"))

@app.route("/elementos/reordenar", methods=["POST"])
@login_required
def reordenar_elementos():
    """Recebe JSON: {"ids": [3, 1, 5, 2, ...]} — ordem dentro de UMA categoria."""
    data = request.get_json()
    ids  = data.get("ids", [])
    with get_db() as con:
        for i, eid in enumerate(ids):
            con.execute("UPDATE elementos SET ordem=? WHERE id=?", (i, eid))
    return jsonify({"ok": True})

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
        elems = con.execute(
            "SELECT * FROM elementos WHERE ativo=1 ORDER BY categoria, ordem, nome"
        ).fetchall()
        resps = con.execute(
            "SELECT elemento_id, opcao FROM respostas WHERE evento_id=?", (eid,)
        ).fetchall()
    if not ev:
        return redirect(url_for("index"))
    opcoes   = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    resp_map = {}
    for r in resps:
        if r["opcao"] not in resp_map.setdefault(r["elemento_id"], []): resp_map[r["elemento_id"]].append(r["opcao"])
    return render_template("evento.html", ev=ev, elementos=elems,
                           opcoes=opcoes, resp_map=resp_map, hierarquia=HIERARQUIA)

@app.route("/eventos/<int:eid>/resposta", methods=["POST"])
@login_required
def set_resposta(eid):
    elem_id = request.form.get("elemento_id")
    opcao   = request.form.get("opcao", "").strip()
    ativo   = request.form.get("ativo", "1")  # "1" = marcar, "0" = desmarcar
    if elem_id and opcao:
        with get_db() as con:
            if ativo == "0":
                con.execute(
                    "DELETE FROM respostas WHERE evento_id=? AND elemento_id=? AND opcao=?",
                    (eid, elem_id, opcao)
                )
            else:
                con.execute("""
                    INSERT OR IGNORE INTO respostas (evento_id, elemento_id, opcao)
                    VALUES (?,?,?)
                """, (eid, elem_id, opcao))
    return redirect(url_for("evento", eid=eid))

# ── CSV helpers ───────────────────────────────────────────────────────────────

def parse_csv(file_stream):
    stream      = io.StringIO(file_stream.read().decode("utf-8-sig"))
    reader      = csv.reader(stream)
    titulo      = ""
    opcoes_set  = []
    votos       = []
    opcao_atual = None
    for row in reader:
        if not row: continue
        col0 = row[0].strip() if len(row) > 0 else ""
        col1 = row[1].strip() if len(row) > 1 else ""
        if col0 == "Sondagem":
            titulo = col1; continue
        if col0 in ("Opcao", "Opção", "") and col1 in ("Nome", ""):
            continue
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
    with get_db() as con:
        elems = con.execute("SELECT id, nome, nome_whatsapp FROM elementos").fetchall()
    elem_index = {e["nome"].lower().strip(): e["id"] for e in elems}
    elem_wa    = {e["nome_whatsapp"].lower().strip(): e["id"] for e in elems if e["nome_whatsapp"]}
    elem_first = {}
    for e in elems:
        p = e["nome"].lower().split()[0]
        if p not in elem_first: elem_first[p] = e["id"]

    def encontrar(n):
        n = n.lower().strip()
        if n in elem_wa:    return elem_wa[n]
        if n in elem_index: return elem_index[n]
        for k, v in elem_wa.items():
            if n in k or k in n: return v
        for k, v in elem_index.items():
            if n in k or k in n: return v
        return elem_first.get(n.split()[0])

    registados, nao_encontrados = 0, []
    for voto in votos:
        elem_id = encontrar(voto["nome"])
        if elem_id:
            with get_db() as con:
                con.execute("""
                    INSERT OR IGNORE INTO respostas (evento_id, elemento_id, opcao)
                    VALUES (?,?,?)
                """, (evento_id, elem_id, voto["opcao"]))
            registados += 1
        else:
            nao_encontrados.append(voto["nome"])
    return registados, nao_encontrados

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
    with get_db() as con:
        cur = con.execute(
            "INSERT INTO eventos (nome, opcoes, criado) VALUES (?,?,?)",
            (titulo, "\n".join(opcoes), datetime.now().strftime("%d/%m/%Y %H:%M"))
        )
        evento_id = cur.lastrowid
    registados, nao = aplicar_votos(evento_id, votos)
    msg = f"Evento '{titulo}' criado com {registados} resposta(s)."
    if nao: msg += f" Nao encontrados: {', '.join(set(nao))}"
    flash(msg)
    return redirect(url_for("evento", eid=evento_id))

@app.route("/eventos/<int:eid>/importar-csv", methods=["POST"])
@login_required
def importar_csv_update(eid):
    file = request.files.get("csv_file")
    if not file:
        flash("Nenhum ficheiro enviado.")
        return redirect(url_for("evento", eid=eid))
    _, _, votos = parse_csv(file)
    registados, nao = aplicar_votos(eid, votos)
    msg = f"{registados} resposta(s) atualizadas."
    if nao: msg += f" Nao encontrados: {', '.join(set(nao))}"
    flash(msg)
    return redirect(url_for("evento", eid=eid))

# ── Tabela ────────────────────────────────────────────────────────────────────

@app.route("/eventos/<int:eid>/tabela")
@login_required
def tabela(eid):
    with get_db() as con:
        ev    = con.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        elems = con.execute(
            "SELECT * FROM elementos ORDER BY categoria, ordem, nome"
        ).fetchall()
        resps = con.execute(
            "SELECT elemento_id, opcao FROM respostas WHERE evento_id=?", (eid,)
        ).fetchall()
    if not ev:
        return redirect(url_for("index"))
    opcoes   = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    resp_map = {}
    for r in resps:
        op = r["opcao"].strip()
        if op not in resp_map.setdefault(r["elemento_id"], []): resp_map[r["elemento_id"]].append(op)
    totais   = {op: sum(1 for v in resp_map.values() if op in v) for op in opcoes}
    sem_resp = sum(1 for e in elems if e["id"] not in resp_map)
    xeques   = [e for e in elems if e["categoria"] == "Xeque"]
    membros  = [e for e in elems if e["categoria"] != "Xeque"]
    return render_template("tabela.html", ev=ev, elementos=elems,
                           opcoes=opcoes, resp_map=resp_map,
                           totais=totais, sem_resp=sem_resp,
                           xeques=xeques, membros=membros,
                           hierarquia=HIERARQUIA)


@app.route("/eventos/<int:eid>/instrumentos")
@login_required
def evento_instrumentos(eid):
    with get_db() as con:
        ev    = con.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        elems = con.execute("SELECT * FROM elementos ORDER BY categoria, ordem, nome").fetchall()
        resps = con.execute(
            "SELECT elemento_id, opcao FROM respostas WHERE evento_id=?", (eid,)
        ).fetchall()
    if not ev:
        return redirect(url_for("index"))

    opcoes = [o.strip() for o in ev["opcoes"].split("\n") if o.strip()]
    resp_map = {}
    for r in resps:
        if r["opcao"] not in resp_map.setdefault(r["elemento_id"], []):
            resp_map[r["elemento_id"]].append(r["opcao"])

    # opções que significam "vai" — sim, yes, vou, levo, ou fallback para todas
    opcoes_sim = [o for o in opcoes if any(s in o.lower() for s in ["sim","yes","vou","levo"])]
    if not opcoes_sim:
        opcoes_sim = opcoes

    # separar quem vai, quem não vai, quem não respondeu
    vai   = [e for e in elems if any(op in resp_map.get(e["id"],[]) for op in opcoes_sim)]
    nao   = [e for e in elems if e["id"] in resp_map and not any(op in resp_map.get(e["id"],[]) for op in opcoes_sim)]
    s_resp = [e for e in elems if e["id"] not in resp_map]

    # contagem de instrumentos de quem vai
    instr_count = {}
    for e in vai:
        instr = (e["instrumento"] or "").strip()
        if instr:
            instr_count[instr] = instr_count.get(instr, 0) + 1

    return render_template("evento_instrumentos.html",
                           ev=ev, opcoes=opcoes,
                           vai=vai, nao=nao, sem_resp=s_resp,
                           instr_count=instr_count,
                           resp_map=resp_map, opcoes_sim=opcoes_sim)

# ── Ensaios ───────────────────────────────────────────────────────────────────

@app.route("/ensaios")
@login_required
def ensaios():
    with get_db() as con:
        lista = con.execute("SELECT * FROM ensaios ORDER BY data DESC").fetchall()
    return render_template("ensaios.html", ensaios=lista)

@app.route("/ensaios/novo", methods=["POST"])
@login_required
def novo_ensaio():
    data_str = request.form.get("data", "").strip()
    if not data_str:
        flash("Escolhe uma data.")
        return redirect(url_for("ensaios"))
    with get_db() as con:
        existe = con.execute("SELECT id FROM ensaios WHERE data=?", (data_str,)).fetchone()
        if existe:
            flash("Já existe um ensaio registado para essa data.")
            return redirect(url_for("ensaios"))
        cur = con.execute(
            "INSERT INTO ensaios (data, criado) VALUES (?,?)",
            (data_str, datetime.now().strftime("%d/%m/%Y %H:%M"))
        )
        eid = cur.lastrowid
    return redirect(url_for("ensaio_detail", eid=eid))

@app.route("/ensaios/<int:eid>/del", methods=["POST"])
@login_required
def del_ensaio(eid):
    with get_db() as con:
        con.execute("DELETE FROM presencas WHERE ensaio_id=?", (eid,))
        con.execute("DELETE FROM ensaios WHERE id=?", (eid,))
    return redirect(url_for("ensaios"))

@app.route("/ensaios/<int:eid>")
@login_required
def ensaio_detail(eid):
    with get_db() as con:
        ensaio = con.execute("SELECT * FROM ensaios WHERE id=?", (eid,)).fetchone()
        elems  = con.execute(
            "SELECT * FROM elementos WHERE ativo=1 ORDER BY categoria, ordem, nome"
        ).fetchall()
        prescs = con.execute(
            "SELECT elemento_id, estado, hora, nota FROM presencas WHERE ensaio_id=?", (eid,)
        ).fetchall()
    if not ensaio:
        return redirect(url_for("ensaios"))

    try:
        d = datetime.strptime(ensaio["data"], "%Y-%m-%d")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        titulo = f"Ensaio de {dias[d.weekday()]}, {d.strftime('%d/%m/%Y')}"
    except Exception:
        titulo = f"Ensaio de {ensaio['data']}"

    presc_map = {p["elemento_id"]: p for p in prescs}
    totais = {
        "a-horas":     sum(1 for p in prescs if p["estado"] == "a-horas"),
        "atrasado":    sum(1 for p in prescs if p["estado"] == "atrasado"),
        "nao-veio":    sum(1 for p in prescs if p["estado"] == "nao-veio"),
        "sem-registo": sum(1 for e in elems if presc_map.get(e["id"], {}).get("estado", "sem-registo") == "sem-registo"),
    }
    return render_template("ensaio_detail.html",
                           ensaio=ensaio, titulo=titulo,
                           elementos=elems, presc_map=presc_map,
                           totais=totais, hierarquia=HIERARQUIA)

@app.route("/ensaios/<int:eid>/presenca", methods=["POST"])
@login_required
def set_presenca(eid):
    elem_id = request.form.get("elemento_id")
    estado  = request.form.get("estado", "sem-registo").strip()
    hora    = request.form.get("hora", "").strip()
    nota    = request.form.get("nota", "").strip()
    if elem_id:
        with get_db() as con:
            con.execute("""
                INSERT INTO presencas (ensaio_id, elemento_id, estado, hora, nota)
                VALUES (?,?,?,?,?)
                ON CONFLICT(ensaio_id, elemento_id)
                DO UPDATE SET estado=excluded.estado, hora=excluded.hora, nota=excluded.nota
            """, (eid, elem_id, estado, hora, nota))
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True})
    return redirect(url_for("ensaio_detail", eid=eid))

# ── Estatísticas ──────────────────────────────────────────────────────────────

@app.route("/estatisticas")
@login_required
def estatisticas():
    with get_db() as con:
        elems           = con.execute(
            "SELECT * FROM elementos ORDER BY categoria, ordem, nome"
        ).fetchall()
        total_ensaios   = con.execute("SELECT COUNT(*) as n FROM ensaios").fetchone()["n"]
        presencas_todas = con.execute("SELECT elemento_id, estado FROM presencas").fetchall()

    presc_por_elem = {}
    for p in presencas_todas:
        presc_por_elem.setdefault(p["elemento_id"], []).append(p["estado"])

    stats = []
    for e in elems:
        prescs       = presc_por_elem.get(e["id"], [])
        n_presente   = sum(1 for p in prescs if p in ("a-horas", "atrasado"))
        n_atrasado   = sum(1 for p in prescs if p == "atrasado")
        n_nao_veio   = sum(1 for p in prescs if p == "nao-veio")
        pct_presenca = round(n_presente / total_ensaios * 100) if total_ensaios else 0
        pct_atraso   = round(n_atrasado / n_presente   * 100) if n_presente    else 0
        pct_falta    = round(n_nao_veio / total_ensaios * 100) if total_ensaios else 0
        stats.append({
            "elem": e,
            "n_presente":    n_presente,
            "n_atrasado":    n_atrasado,
            "n_nao_veio":    n_nao_veio,
            "total_ensaios": total_ensaios,
            "pct_presenca":  pct_presenca,
            "pct_atraso":    pct_atraso,
            "pct_falta":     pct_falta,
        })

    return render_template("estatisticas.html", stats=stats,
                           total_ensaios=total_ensaios,
                           hierarquia=HIERARQUIA)

@app.route("/estatisticas/<int:elem_id>")
@login_required
def estatisticas_membro(elem_id):
    with get_db() as con:
        elem          = con.execute("SELECT * FROM elementos WHERE id=?", (elem_id,)).fetchone()
        ensaios_lista = con.execute("SELECT * FROM ensaios ORDER BY data DESC").fetchall()
        prescs        = con.execute(
            "SELECT ensaio_id, estado FROM presencas WHERE elemento_id=?", (elem_id,)
        ).fetchall()

    if not elem:
        return redirect(url_for("estatisticas"))

    presc_map     = {p["ensaio_id"]: p for p in prescs}
    total_ensaios = len(ensaios_lista)
    n_a_horas     = sum(1 for p in prescs if p["estado"] == "a-horas")
    n_atrasado    = sum(1 for p in prescs if p["estado"] == "atrasado")
    n_nao_veio    = sum(1 for p in prescs if p["estado"] == "nao-veio")
    n_presente    = n_a_horas + n_atrasado

    pct_presenca = round(n_presente / total_ensaios * 100) if total_ensaios else 0
    pct_ahoras   = round(n_a_horas  / total_ensaios * 100) if total_ensaios else 0
    pct_atraso   = round(n_atrasado / total_ensaios * 100) if total_ensaios else 0
    pct_falta    = round(n_nao_veio / total_ensaios * 100) if total_ensaios else 0

    hist_ensaios = []
    for ens in ensaios_lista:
        p = presc_map.get(ens["id"], None)
        try:
            d = datetime.strptime(ens["data"], "%Y-%m-%d")
            dias  = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            titulo = f"{dias[d.weekday()]} {d.strftime('%d/%m/%Y')}"
        except Exception:
            titulo = ens["data"]
        hist_ensaios.append({"ens": ens, "titulo": titulo, "presc": p})

    return render_template("estatisticas_membro.html",
                           elem=elem,
                           hist_ensaios=hist_ensaios,
                           total_ensaios=total_ensaios,
                           n_a_horas=n_a_horas,
                           n_atrasado=n_atrasado,
                           n_nao_veio=n_nao_veio,
                           n_presente=n_presente,
                           pct_presenca=pct_presenca,
                           pct_ahoras=pct_ahoras,
                           pct_atraso=pct_atraso,
                           pct_falta=pct_falta)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
