import os
import sqlite3
import requests
from flask import Flask, request

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.db")
# Variáveis de ambiente (Render define via painel ou render.yaml)
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")

# Cria banco SQLite automaticamente se não existir
def init_db():
    if not os.path.exists("tokens.db"):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT,
            refresh_token TEXT,
            token_type TEXT,
            expires_in INTEGER,
            scope TEXT,
            user_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
        conn.close()

init_db()

# Página inicial com link de autorização
@app.route("/")
def home():
    url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    return f'<h1>Conectar com Mercado Livre</h1><a href="{url}">Clique aqui para autorizar</a>'

# Callback para trocar o code por token e salvar
@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erro: código de autorização não encontrado."

    # Troca code pelo token
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

    # Salva no banco
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        token_info.get("access_token"),
        token_info.get("refresh_token"),
        token_info.get("token_type"),
        token_info.get("expires_in"),
        token_info.get("scope"),
        token_info.get("user_id")
    ))
    conn.commit()
    conn.close()

    return f"<h3>Token salvo com sucesso para user_id: {token_info.get('user_id')}</h3>"

@app.route("/refresh_token")
def refresh_token():
    # Pega o último refresh_token salvo no banco
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT refresh_token FROM tokens ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return "Nenhum refresh_token encontrado no banco de dados.", 404

    refresh_token_value = row[0]

    # Requisição para renovar o token
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_value
    }

    response = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
    if response.status_code != 200:
        return f"Erro ao renovar token: {response.text}", 400

    token_info = response.json()

    # Salva novo token no banco
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO tokens (access_token, refresh_token, token_type, expires_in, scope, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        token_info.get("access_token"),
        token_info.get("refresh_token"),
        token_info.get("token_type"),
        token_info.get("expires_in"),
        token_info.get("scope"),
        token_info.get("user_id")
    ))
    conn.commit()
    conn.close()

    return f"<h3>Token renovado com sucesso para user_id: {token_info.get('user_id')}</h3>"

@app.route("/tokens")
def list_tokens():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, access_token, refresh_token, created_at FROM tokens ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    html = "<h2>Tokens salvos:</h2><ul>"
    for r in rows:
        html += f"<li><b>ID:</b> {r[0]} | <b>access_token:</b> {r[1][:10]}... | <b>refresh_token:</b> {r[2][:10]}... | <b>created_at:</b> {r[3]}</li>"
    html += "</ul>"
    return html
@app.route("/me")
def get_me():
    # Pega o último access_token
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token FROM tokens ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return "Nenhum token encontrado.", 404

    access_token = row[0]

    # Chamada à API do Mercado Livre
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.mercadolibre.com/users/me", headers=headers)


    if response.status_code != 200:
        return f"Erro ao acessar /users/me: {response.text}", 400

    return response.json()

@app.route("/me/anuncios")
def listar_anuncios():
    # Pega o último token e user_id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, user_id FROM tokens ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return "Nenhum token encontrado.", 404

    access_token, user_id = row
    url = f"https://api.mercadolibre.com/users/{user_id}/items/search"

    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return f"Erro ao buscar anúncios: {response.text}", 400

    data = response.json()
    total = data.get("paging", {}).get("total", 0)
    items = data.get("results", [])

    return {
        "total_anuncios": total,
        "ids": items
    }

@app.route("/debug_db")
def debug_db():
    return f"Caminho absoluto do banco: <code>{DB_PATH}</code>"
# Configuração de execução compatível com Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
