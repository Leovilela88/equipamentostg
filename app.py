import os
import json
import sqlite3
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

try:
    import boto3
    from botocore.config import Config as BotoConfig
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "equipamentos-av-key-2024")

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "equipamentos.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "heic"}

CATEGORIAS = [
    "Câmera",
    "Lente",
    "Tripé / Suporte",
    "Iluminação",
    "Microfone / Áudio",
    "Bateria",
    "Cartão de memória",
    "Drone",
    "Monitor / Vídeo",
    "Acessório",
    "Outros",
]


# ── Config (R2) ────────────────────────────────────────────────────────────────

def carregar_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def salvar_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_r2_config():
    """Env vars têm prioridade sobre config.json."""
    cfg = carregar_config()
    def _v(env, key):
        return os.environ.get(env) or cfg.get(key, "")
    return {
        "account_id": _v("R2_ACCOUNT_ID", "r2_account_id"),
        "access_key": _v("R2_ACCESS_KEY", "r2_access_key"),
        "secret_key": _v("R2_SECRET_KEY", "r2_secret_key"),
        "bucket":     _v("R2_BUCKET",     "r2_bucket"),
        "public_url": _v("R2_PUBLIC_URL", "r2_public_url"),
        "prefixo":    _v("R2_PREFIX",     "r2_prefixo") or "equipamentos",
    }


def get_r2():
    c = get_r2_config()
    if HAS_BOTO and c["account_id"] and c["access_key"] and c["secret_key"] and c["bucket"]:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{c['account_id']}.r2.cloudflarestorage.com",
            aws_access_key_id=c["access_key"],
            aws_secret_access_key=c["secret_key"],
            config=BotoConfig(signature_version="s3v4"),
            region_name="auto",
        )
        return client, c["bucket"], c["public_url"], c["prefixo"]
    return None, None, None, None


def upload_foto(file_obj, prefix="foto"):
    ext = file_obj.filename.rsplit(".", 1)[-1].lower()
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    client, bucket, public_url, pasta = get_r2()
    if client:
        key = f"{pasta.strip('/')}/{filename}"
        client.upload_fileobj(
            file_obj,
            bucket,
            key,
            ExtraArgs={"ContentType": file_obj.content_type or "image/jpeg"},
        )
        return f"{public_url.rstrip('/')}/{key}"
    # fallback local
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    dest = os.path.join(UPLOAD_FOLDER, filename)
    file_obj.save(dest)
    return url_for("static", filename=f"uploads/{filename}", _external=False)


def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Banco de dados ─────────────────────────────────────────────────────────────

def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS registros (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pauta       TEXT NOT NULL,
                data_inicio TEXT NOT NULL,
                data_fim    TEXT NOT NULL,
                cinegrafista TEXT NOT NULL,
                reporter    TEXT,
                destino     TEXT,
                equipamentos TEXT,
                observacoes TEXT,
                foto_saida  TEXT,
                foto_devolucao TEXT,
                status      TEXT DEFAULT 'Em campo',
                criado_em   TEXT DEFAULT (datetime('now','localtime')),
                devolvido_em TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalogo (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                nome      TEXT NOT NULL,
                descricao TEXT,
                criado_em TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()


init_db()


def listar_catalogo():
    """Retorna {categoria: [itens...]} ordenado."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM catalogo ORDER BY categoria, nome COLLATE NOCASE"
        ).fetchall()
    grupos = {}
    for r in rows:
        grupos.setdefault(r["categoria"], []).append(dict(r))
    return grupos


# ── Helpers ────────────────────────────────────────────────────────────────────

def formatar_periodo(inicio, fim):
    try:
        d1 = datetime.strptime(inicio, "%Y-%m-%d")
        d2 = datetime.strptime(fim, "%Y-%m-%d")
        if d1.month == d2.month and d1.year == d2.year:
            return f"{d1.day} a {d2.strftime('%d/%m/%Y')}"
        return f"{d1.strftime('%d/%m')} a {d2.strftime('%d/%m/%Y')}"
    except Exception:
        return f"{inicio} – {fim}"


app.jinja_env.globals["formatar_periodo"] = formatar_periodo


# ── Rotas ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    status_filter = request.args.get("status", "todos")
    with get_db() as conn:
        if status_filter == "reservado":
            rows = conn.execute(
                "SELECT * FROM registros WHERE status='Reservado' ORDER BY data_inicio ASC, criado_em DESC"
            ).fetchall()
        elif status_filter == "em_campo":
            rows = conn.execute(
                "SELECT * FROM registros WHERE status='Em campo' ORDER BY criado_em DESC"
            ).fetchall()
        elif status_filter == "devolvido":
            rows = conn.execute(
                "SELECT * FROM registros WHERE status='Devolvido' ORDER BY devolvido_em DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM registros ORDER BY "
                "CASE status WHEN 'Reservado' THEN 1 WHEN 'Em campo' THEN 2 ELSE 3 END, "
                "criado_em DESC"
            ).fetchall()

        totais = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='Reservado' THEN 1 ELSE 0 END) as reservado,
                SUM(CASE WHEN status='Em campo'  THEN 1 ELSE 0 END) as em_campo,
                SUM(CASE WHEN status='Devolvido' THEN 1 ELSE 0 END) as devolvido
            FROM registros
        """).fetchone()

    return render_template("index.html", registros=rows, status_filter=status_filter, totais=totais)


@app.route("/novo", methods=["GET", "POST"])
def novo():
    catalogo = listar_catalogo()
    if request.method == "POST":
        pauta        = request.form.get("pauta", "").strip()
        data_inicio  = request.form.get("data_inicio", "")
        data_fim     = request.form.get("data_fim", "")
        cinegrafista = request.form.get("cinegrafista", "").strip()
        reporter     = request.form.get("reporter", "").strip()
        destino      = request.form.get("destino", "").strip()
        observacoes  = request.form.get("observacoes", "").strip()

        # Equipamentos: combina selecionados do catálogo + texto livre "outros"
        selecionados = request.form.getlist("equipamentos_ids")
        outros       = request.form.get("equipamentos_outros", "").strip()

        itens = []
        if selecionados:
            with get_db() as conn:
                qmarks = ",".join("?" * len(selecionados))
                rows = conn.execute(
                    f"SELECT categoria, nome FROM catalogo WHERE id IN ({qmarks})",
                    selecionados,
                ).fetchall()
                itens = [f"[{r['categoria']}] {r['nome']}" for r in rows]
        if outros:
            itens.extend([l.strip() for l in outros.splitlines() if l.strip()])
        equipamentos = "\n".join(itens)

        if not pauta or not data_inicio or not data_fim or not cinegrafista:
            flash("Preencha os campos obrigatórios: Pauta, Período e Cinegrafista.", "erro")
            return render_template("novo.html", form=request.form, catalogo=catalogo,
                                   selecionados=set(selecionados))

        # tipo = "reserva" ou "saida" (default)
        tipo = request.form.get("tipo", "saida")
        status = "Reservado" if tipo == "reserva" else "Em campo"

        foto_url = None
        if tipo == "saida":
            file = request.files.get("foto_saida")
            if file and file.filename and allowed(file.filename):
                try:
                    foto_url = upload_foto(file, prefix="saida")
                except Exception as e:
                    flash(f"Erro ao enviar foto: {e}", "erro")

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO registros
                    (pauta, data_inicio, data_fim, cinegrafista, reporter, destino,
                     equipamentos, observacoes, foto_saida, status)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (pauta, data_inicio, data_fim, cinegrafista, reporter, destino,
                  equipamentos, observacoes, foto_url, status))
            conn.commit()
            registro_id = cursor.lastrowid

        msg = "Reserva criada com sucesso!" if tipo == "reserva" else "Saída registrada com sucesso!"
        flash(msg, "ok")
        return redirect(url_for("detalhe", id=registro_id))

    return render_template("novo.html", form={}, catalogo=catalogo, selecionados=set())


@app.route("/registro/<int:id>")
def detalhe(id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM registros WHERE id=?", (id,)).fetchone()
    if not row:
        flash("Registro não encontrado.", "erro")
        return redirect(url_for("index"))
    return render_template("detalhe.html", r=row)


@app.route("/registro/<int:id>/foto-saida", methods=["POST"])
def foto_saida(id):
    file = request.files.get("foto")
    if not file or not file.filename or not allowed(file.filename):
        flash("Selecione uma imagem válida (jpg, png, jpeg, webp).", "erro")
        return redirect(url_for("detalhe", id=id))
    try:
        url = upload_foto(file, prefix="saida")
        with get_db() as conn:
            conn.execute("UPDATE registros SET foto_saida=? WHERE id=?", (url, id))
            conn.commit()
        flash("Foto de saída atualizada.", "ok")
    except Exception as e:
        flash(f"Erro ao enviar foto: {e}", "erro")
    return redirect(url_for("detalhe", id=id))


@app.route("/registro/<int:id>/devolver", methods=["POST"])
def devolver(id):
    foto_url = None
    file = request.files.get("foto_devolucao")
    if file and file.filename and allowed(file.filename):
        try:
            foto_url = upload_foto(file, prefix="devolucao")
        except Exception as e:
            flash(f"Erro ao enviar foto: {e}", "erro")
            return redirect(url_for("detalhe", id=id))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        if foto_url:
            conn.execute("""
                UPDATE registros
                SET status='Devolvido', devolvido_em=?, foto_devolucao=?
                WHERE id=?
            """, (now, foto_url, id))
        else:
            conn.execute("""
                UPDATE registros
                SET status='Devolvido', devolvido_em=?
                WHERE id=?
            """, (now, id))
        conn.commit()

    flash("Equipamentos marcados como devolvidos!", "ok")
    return redirect(url_for("detalhe", id=id))


@app.route("/registro/<int:id>/confirmar-saida", methods=["POST"])
def confirmar_saida(id):
    """Converte uma Reserva em 'Em campo' (opcionalmente com foto)."""
    foto_url = None
    file = request.files.get("foto_saida")
    if file and file.filename and allowed(file.filename):
        try:
            foto_url = upload_foto(file, prefix="saida")
        except Exception as e:
            flash(f"Erro ao enviar foto: {e}", "erro")
            return redirect(url_for("detalhe", id=id))

    with get_db() as conn:
        if foto_url:
            conn.execute(
                "UPDATE registros SET status='Em campo', foto_saida=?, "
                "criado_em=datetime('now','localtime') WHERE id=?",
                (foto_url, id),
            )
        else:
            conn.execute(
                "UPDATE registros SET status='Em campo', "
                "criado_em=datetime('now','localtime') WHERE id=?",
                (id,),
            )
        conn.commit()
    flash("Saída confirmada! Reserva agora está em campo.", "ok")
    return redirect(url_for("detalhe", id=id))


@app.route("/registro/<int:id>/reabrir", methods=["POST"])
def reabrir(id):
    with get_db() as conn:
        conn.execute("""
            UPDATE registros SET status='Em campo', devolvido_em=NULL WHERE id=?
        """, (id,))
        conn.commit()
    flash("Registro reaberto.", "ok")
    return redirect(url_for("detalhe", id=id))


@app.route("/registro/<int:id>/excluir", methods=["POST"])
def excluir(id):
    with get_db() as conn:
        conn.execute("DELETE FROM registros WHERE id=?", (id,))
        conn.commit()
    flash("Registro excluído.", "ok")
    return redirect(url_for("index"))


# ── Admin (acesso direto via /admin) ───────────────────────────────────────────

@app.route("/admin")
def admin():
    cfg = get_r2_config()
    client, *_ = get_r2()
    status = "configurado" if client else "não configurado"
    catalogo = listar_catalogo()
    return render_template("admin.html",
                           cfg=cfg,
                           status=status,
                           env_override=bool(os.environ.get("R2_ACCOUNT_ID")),
                           categorias=CATEGORIAS,
                           catalogo=catalogo)


@app.route("/admin/salvar", methods=["POST"])
def admin_salvar():
    cfg = carregar_config()
    cfg["r2_account_id"] = request.form.get("account_id", "").strip()
    cfg["r2_access_key"] = request.form.get("access_key", "").strip()
    cfg["r2_secret_key"] = request.form.get("secret_key", "").strip()
    cfg["r2_bucket"]     = request.form.get("bucket", "").strip()
    cfg["r2_public_url"] = request.form.get("public_url", "").strip().rstrip("/")
    cfg["r2_prefixo"]    = (request.form.get("prefixo", "").strip() or "equipamentos").strip("/")
    salvar_config(cfg)
    flash("Configurações do R2 salvas.", "ok")
    return redirect(url_for("admin"))


@app.route("/admin/testar", methods=["POST"])
def admin_testar():
    client, bucket, public_url, pasta = get_r2()
    if not client:
        return jsonify({"ok": False, "erro": "Configuração incompleta ou boto3 ausente."}), 400
    try:
        client.head_bucket(Bucket=bucket)
        test_key = f"{pasta.strip('/')}/_teste_{uuid.uuid4().hex[:8]}.txt"
        client.put_object(Bucket=bucket, Key=test_key,
                          Body=b"teste de conexao equipav",
                          ContentType="text/plain")
        client.delete_object(Bucket=bucket, Key=test_key)
        return jsonify({"ok": True, "bucket": bucket, "public_url": public_url, "pasta": pasta})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── Catálogo de equipamentos ───────────────────────────────────────────────────

@app.route("/admin/catalogo/novo", methods=["POST"])
def catalogo_novo():
    categoria = request.form.get("categoria", "").strip()
    nome      = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()

    if not categoria or not nome:
        flash("Informe categoria e nome do equipamento.", "erro")
        return redirect(url_for("admin") + "#catalogo")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO catalogo (categoria, nome, descricao) VALUES (?,?,?)",
            (categoria, nome, descricao),
        )
        conn.commit()
    flash(f"Equipamento '{nome}' adicionado ao catálogo.", "ok")
    return redirect(url_for("admin") + "#catalogo")


@app.route("/admin/catalogo/<int:id>/excluir", methods=["POST"])
def catalogo_excluir(id):
    with get_db() as conn:
        conn.execute("DELETE FROM catalogo WHERE id=?", (id,))
        conn.commit()
    flash("Equipamento removido do catálogo.", "ok")
    return redirect(url_for("admin") + "#catalogo")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)
