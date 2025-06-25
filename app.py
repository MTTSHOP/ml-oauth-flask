import os
import psycopg2
import requests
from flask import Flask, request

app = Flask(__name__)

# Variáveis de ambiente
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

# Criação automática da tabela tokens no início da aplicação
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

@app.route("/tokens")
def list_tokens():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, access_token, refresh_token, created_at FROM tokens ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = "<h2>Tokens salvos:</h2><ul>"
    for r in rows:
        html += f"<li><b>ID:</b> {r[0]} | <b>User ID:</b> {r[1]} | <b>Access:</b> {r[2][:10]}... | <b>Refresh:</b> {r[3][:10]}... | <b>Em:</b> {r[4]}</li>"
    html += "</ul>"
    return html

@app.route("/usuarios")
def listar_usuarios():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM tokens ORDER BY user_id")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = "<h2>Usuários autenticados:</h2><ul>"
    for r in rows:
        html += f'<li><a href="/me/{r[0]}">{r[0]}</a></li>'
    html += "</ul>"
    return html

@app.route("/me/<user_id>")
def get_me_user(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT access_token FROM tokens WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return f"Nenhum token encontrado para user_id {user_id}", 404

    access_token = row[0]
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.mercadolibre.com/users/me", headers=headers)

    if response.status_code != 200:
        return f"Erro ao acessar /users/me: {response.text}", 400

    return response.json()

@app.route("/me/<user_id>/anuncios")
def listar_anuncios_user(user_id):
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
    return {
        "total_anuncios": data.get("paging", {}).get("total", 0),
        "ids": data.get("results", [])
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    