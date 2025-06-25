import os
from datetime import datetime

import psycopg2
import requests
from flask import Flask, request

app = Flask(__name__)

# -----------------------------------------------------------------------------
# Configurações de ambiente
# -----------------------------------------------------------------------------
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")  # Ex: postgres://user:pwd@host:5432/db

# -----------------------------------------------------------------------------
# Helpers de banco
# -----------------------------------------------------------------------------

def get_db_conn():
    """Retorna uma nova conexão com o Postgres."""
    return psycopg2.connect(DATABASE_URL)

# Cria a tabela `tokens` caso não exista
try:
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    id SERIAL PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    token_type TEXT,
                    expires_in INTEGER,
                    scope TEXT,
                    user_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
except Exception as exc:
    print("[WARN] Erro ao criar tabela tokens:", exc)

# -----------------------------------------------------------------------------
# Helpers de API Mercado Livre
# -----------------------------------------------------------------------------

def obter_item_ids(user_id: str, access_token: str):
    """Retorna a lista de ITEM_IDs de um vendedor."""
    url = f"https://api.mercadolibre.com/users/{user_id}/items/search"
    
    resp = requests.get(url, params={"access_token": access_token})
    print("[DEBUG] /items/search status:", resp.status_code, resp.text[:200])
    if resp.status_code != 200:
        print("[API] Falha ao buscar itens:", resp.text)
        return []
    return resp.json().get("results", [])


def fetch_items_detalhes(item_ids: list[str]):
    """Busca título, preço, status e permalink de vários itens em blocos de 20."""
    detalhes = []
    chunk_size = 20
    for i in range(0, len(item_ids), chunk_size):
        chunk = item_ids[i : i + chunk_size]
        url = "https://api.mercadolibre.com/items"
        params = {
            "ids": ",".join(chunk),
            "attributes": "title,price,status,permalink",
        }
        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            print("[API] Erro /items:", resp.text)
            continue
        for itm in resp.json():
            if itm.get("code") == 200 and "body" in itm:
                detalhes.append(itm["body"])
    return detalhes

# -----------------------------------------------------------------------------
# Rotas Flask
# -----------------------------------------------------------------------------

@app.route("/")
def home():
    auth_url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    return (
        "<h1>Conectar com Mercado Livre</h1>"
        f"<a href='{auth_url}'>Clique aqui para autorizar</a>"
    )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erro: código não encontrado!", 400

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
    if resp.status_code != 200:
        return f"Erro ao trocar código: {resp.text}", 400

    tok = resp.json()
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    tok.get("access_token"),
                    tok.get("refresh_token"),
                    tok.get("token_type"),
                    tok.get("expires_in"),
                    tok.get("scope"),
                    str(tok.get("user_id")),
                ),
            )
            conn.commit()
    return "Token salvo com sucesso. <a href='/painel'>Ir ao painel</a>"

# ----------------- Painel de usuários -----------------

@app.route("/painel")
def painel():
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, MAX(created_at) FROM tokens GROUP BY user_id ORDER BY user_id"
            )
            rows = cur.fetchall()

    html = (
        "<h2>Painel de usuários conectados</h2>"
        "<table border='1' cellpadding='5'>"
        "<tr><th>User ID</th><th>Token criado em</th><th>Anúncios</th><th>Ações</th></tr>"
    )
    for uid, created_at in rows:
        criacao = created_at.strftime("%d/%m/%Y %H:%M")
        html += (
            f"<tr><td>{uid}</td>"
            f"<td>{criacao}</td>"
            f"<td><a href='/painel/anuncios/{uid}'>Ver anúncios</a></td>"
            f"<td><a href='/painel/refresh/{uid}'>Renovar token</a></td></tr>"
        )
    html += "</table>"
    return html


@app.route("/painel/refresh/<user_id>")
def painel_refresh(user_id):
    # Busca o refresh_token mais recente
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT refresh_token FROM tokens WHERE user_id=%s ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return "Usuário não encontrado.", 404

    rt = row[0]
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": rt,
    }
    resp = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
    if resp.status_code != 200:
        return f"Erro: {resp.text}", 400

    tok = resp.json()
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    tok.get("access_token"),
                    tok.get("refresh_token"),
                    tok.get("token_type"),
                    tok.get("expires_in"),
                    tok.get("scope"),
                    str(tok.get("user_id")),
                ),
            )
            conn.commit()
    return "Token renovado. <a href='/painel'>Voltar</a>"


@app.route("/painel/anuncios/<user_id>")
def painel_anuncios(user_id):
    # 1) Obter o access_token mais recente
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM tokens WHERE user_id=%s ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return "Token não encontrado.", 404
    access_token = row[0]

    # 2) Obter todos os ITEM_IDs do vendedor
    item_ids = obter_item_ids(user_id, access_token)
    if not item_ids:
        return "<p>Usuário sem anúncios encontrados.</p>"

    # 3) Buscar detalhes em bloco
    detalhes = fetch_items_detalhes(item_ids)

    # Tradução de status
    traduz = {"active": "Ativo", "paused": "Pausado", "closed": "Finalizado"}

    html = f"<h2>Anúncios do usuário {user_id}</h2>"
    html += "<table border='1' cellpadding='5'><tr>"
    html += "<th>Título</th><th>Preço (R$)</th><th>Status</th><th>Link</th></tr>"

    for d in detalhes:
        titulo = d.get("title", "–")
        preco = float(d.get("price", 0.0))
        status = traduz.get(d.get("status", ""), d.get("status", ""))
        link = d.get("permalink", "#")

        html += "<tr>"
        html += f"<td>{titulo}</td>"
        html += f"<td>{preco:,.2f}</td>"
        html += f"<td>{status}</td>"
        html += f"<td><a href='{link}' target='_blank'>Abrir</a></td>"
        html += "</tr>"
    html += "</table><br><a href='/painel'>Voltar ao painel</a>"
    return html

# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
