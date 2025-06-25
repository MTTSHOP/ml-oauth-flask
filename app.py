from flask import Flask, redirect, request
import requests
import os

app = Flask(__name__)

CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")

@app.route("/")
def home():
    url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    return f'<a href="{url}">Conectar com Mercado Livre</a>'

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erro: nenhum código recebido."

    token_url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }

    resp = requests.post(token_url, data=payload)
    return f"<pre>{resp.json()}</pre>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
