import os
import psycopg2
import requests
from flask import Flask, request
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

try:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
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
    """)
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f"Erro ao criar tabela tokens: {e}")

@app.route("/")
def home():
    auth_url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    return f'<h1>Conectar com Mercado Livre</h1><a href="{auth_url}">Clique aqui para autorizar</a>'

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erro: código de autorização não encontrado."

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
    if response.status_code != 200:
        return f"Erro ao obter token: {response.text}", 400

    token_info = response.json()

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (
        token_info.get("access_token"),
        token_info.get("refresh_token"),
        token_info.get("token_type"),
        token_info.get("expires_in"),
        token_info.get("scope"),
        str(token_info.get("user_id"))
    ))
    conn.commit()
    cur.close()
    conn.close()

    return f"Token salvo com sucesso para user_id: {token_info.get('user_id')}"

@app.route("/painel")
def painel():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, MAX(created_at)
        FROM tokens
        GROUP BY user_id
        ORDER BY user_id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = "<h2>Painel de usuários conectados</h2><table border='1' cellpadding='5'><tr><th>User ID</th><th>Token Criado em</th><th>Anúncios</th><th>Ações</th></tr>"
    for user_id, created_at in rows:
        anuncios_link = f"/painel/anuncios/{user_id}"
        refresh_link = f"/painel/refresh/{user_id}"
        created_str = created_at.strftime("%d/%m/%Y %H:%M")
        html += f"<tr><td>{user_id}</td><td>{created_str}</td><td><a href='{anuncios_link}'>Ver anúncios</a></td><td><a href='{refresh_link}'>Renovar token</a></td></tr>"
    html += "</table>"
    return html

@app.route("/painel/refresh/<user_id>")
def painel_refresh(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT refresh_token FROM tokens WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return f"Nenhum refresh_token encontrado para user_id {user_id}", 404

    refresh_token_val = row[0]
    cur.close()
    conn.close()

    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_val,
    }

    response = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
    if response.status_code != 200:
        return f"Erro ao renovar token: {response.text}", 400

    token_info = response.json()

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (
        token_info.get("access_token"),
        token_info.get("refresh_token"),
        token_info.get("token_type"),
        token_info.get("expires_in"),
        token_info.get("scope"),
        str(token_info.get("user_id"))
    ))
    conn.commit()
    cur.close()
    conn.close()

    return f"Token renovado com sucesso para user_id {user_id}. <a href='/painel'>Voltar ao painel</a>"

@app.route("/painel/anuncios/<user_id>")
def painel_anuncios(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT access_token FROM tokens WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return f"Nenhum token encontrado para user_id {user_id}", 404

    access_token = row[0]
    url = f"https://api.mercadolibre.com/users/{user_id}/items/search"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return f"Erro ao buscar anúncios: {response.text}", 400

    data = response.json()
    html = f"<h2>Anúncios de {user_id}</h2><ul>"
    for item_id in data.get("results", []):
        html += f"<li><a href='https://produto.mercadolivre.com.br/{item_id}' target='_blank'>{item_id}</a></li>"
    html += "</ul><a href='/painel'>Voltar ao painel</a>"
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
