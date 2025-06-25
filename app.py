import os
import sqlite3
import requests
from flask import Flask, request

app = Flask(__name__)

# Variáveis de ambiente (Render define via painel ou render.yaml)
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")

# Cria banco SQLite automaticamente se não existir
def init_db():
    if not os.path.exists("tokens.db"):
        conn = sqlite3.connect("tokens.db")
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
    conn = sqlite3.connect("tokens.db")
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

# Configuração de execução compatível com Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
