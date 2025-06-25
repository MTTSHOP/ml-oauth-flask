import os
from datetime import datetime

import psycopg2
import requests
from flask import Flask, request

app = Flask(__name__)

CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

# Tabela tokens
with get_db_conn() as conn:
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tokens (
            id SERIAL PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            token_type TEXT,
            expires_in INTEGER,
            scope TEXT,
            user_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

# --------------------------------------------------
# Helpers Mercado Livre
# --------------------------------------------------

def obter_item_ids(user_id, token):
    url = f"https://api.mercadolibre.com/users/{user_id}/items/search"
    r = requests.get(url, params={"access_token": token})
    app.logger.info("/items/search %s", r.status_code)
    return r.json().get("results", []) if r.ok else []


def fetch_items_detalhes(item_ids, token):
    detalhes, step = [], 20
    for i in range(0, len(item_ids), step):
        chunk = item_ids[i : i + step]
        r = requests.get(
            "https://api.mercadolibre.com/items",
            params={
                "ids": ",".join(chunk),
                "attributes": "title,price,original_price,sale_price,catalog_listing,status,permalink",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        app.logger.info("/items multi %s", r.status_code)
        if not r.ok:
            continue
        detalhes.extend([it["body"] for it in r.json() if it.get("code") == 200])
    return detalhes

STATUS_PT = {"active": "Ativo", "paused": "Pausado", "closed": "Finalizado"}

# --------------------------------------------------
# Rotas
# --------------------------------------------------

@app.route("/painel/anuncios/<user_id>")
def painel_anuncios(user_id):
    # token
    with get_db_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT access_token FROM tokens WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user_id,))
            row = c.fetchone()
    if not row:
        return "Token não encontrado", 404
    token = row[0]

    item_ids = obter_item_ids(user_id, token)
    if not item_ids:
        return "<p>Usuário sem anúncios.</p>"

    detalhes = fetch_items_detalhes(item_ids, token)

    # monta HTML
    html = """
    <html><head><meta charset='utf-8'>
    <style>
      body{font-family:Arial,Helvetica,sans-serif}
      table{border-collapse:collapse;width:100%}
      th,td{border:1px solid #ccc;padding:6px}
      th{background:#f2f2f2;text-align:left}
    </style></head><body>
    """
    html += f"<h2>Anúncios do usuário {user_id}</h2>"
    html += "<table><tr><th>Título</th><th>Preço (R$)</th><th>Promoção (R$)</th><th>Catálogo?</th><th>Status</th><th>Link</th></tr>"

    for d in detalhes:
        titulo = d.get("title", "–")
        preco = float(d.get("price", 0))
        promo = d.get("sale_price") or (
            preco if d.get("original_price") and d.get("original_price") > preco else None
        )
        promo_str = f"{promo:,.2f}" if promo else "–"
        catalogo = "Sim" if d.get("catalog_listing") else "Não"
        status = STATUS_PT.get(d.get("status"), d.get("status"))
        link = d.get("permalink", "#")
        html += (
            f"<tr><td>{titulo}</td>"
            f"<td>{preco:,.2f}</td>"
            f"<td>{promo_str}</td>"
            f"<td>{catalogo}</td>"
            f"<td>{status}</td>"
            f"<td><a href='{link}' target='_blank'>Abrir</a></td></tr>"
        )

    html += "</table><br><a href='/painel'>Voltar ao painel</a></body></html>"
    return html

# -------------------- restante do arquivo (rotas /painel etc.) permanece igual --------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
