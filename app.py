import os
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from flask import Flask, redirect, request, session, jsonify, url_for, abort
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    TIMESTAMP,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError

###############################################################################
# Configuration helpers
###############################################################################

DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/mercadolivre")
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "http://localhost:5000/callback")
API_BASE = "https://api.mercadolibre.com"

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Missing ML_CLIENT_ID or ML_CLIENT_SECRET env vars")

SECRET_KEY = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Flask app
app = Flask(__name__)
app.secret_key = SECRET_KEY

###############################################################################
# Database setup (SQLAlchemy + PostgreSQL)
###############################################################################

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False))
Base = declarative_base()


class Token(Base):
    """Tokens table mapping (multi‑user)."""

    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_type = Column(String(50))
    expires_in = Column(Integer)  # seconds
    scope = Column(Text)
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    @property
    def expires_at(self) -> datetime:
        """Return absolute expiration datetime in UTC."""
        return self.created_at + timedelta(seconds=self.expires_in or 0)


Base.metadata.create_all(engine)

###############################################################################
# OAuth helpers
###############################################################################

def _token_endpoint():
    return f"{API_BASE}/oauth/token"


def _auth_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    return f"https://auth.mercadolivre.com.br/authorization?{urlencode(params)}"


def _save_token(db, payload: dict, user_id: str):
    token = (
        db.query(Token).filter_by(user_id=user_id).order_by(Token.id.desc()).first()
    )
    if token:
        # Update existing
        token.access_token = payload["access_token"]
        token.refresh_token = payload.get("refresh_token", token.refresh_token)
        token.token_type = payload.get("token_type")
        token.expires_in = payload.get("expires_in")
        token.scope = payload.get("scope")
        token.created_at = datetime.now(timezone.utc)
    else:
        token = Token(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            token_type=payload.get("token_type"),
            expires_in=payload.get("expires_in"),
            scope=payload.get("scope"),
            user_id=user_id,
        )
        db.add(token)
    db.commit()
    return token


def _request_token(code: str):
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(_token_endpoint(), data=payload, timeout=20)
    if resp.status_code != 200:
        abort(resp.status_code, resp.text)
    return resp.json()


def _refresh_token(token: Token):
    payload = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": token.refresh_token,
    }
    resp = requests.post(_token_endpoint(), data=payload, timeout=20)
    if resp.status_code != 200:
        abort(resp.status_code, resp.text)
    return resp.json()


def get_token(user_id: str, db=None) -> Token:
    """Return a valid (possibly refreshed) Token for user_id."""
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    token: Token | None = (
        db.query(Token).filter_by(user_id=user_id).order_by(Token.id.desc()).first()
    )
    if not token:
        abort(404, f"Token not found for user {user_id}")

    # Refresh if needed (with 2‑minute buffer)
    if token.expires_in and token.expires_at < datetime.now(timezone.utc) + timedelta(minutes=2):
        payload = _refresh_token(token)
        token = _save_token(db, payload, user_id)

    if close_session:
        db.close()
    return token

###############################################################################
# Flask routes
###############################################################################

@app.route("/")
def index():
    return {
        "msg": "Mercado Livre OAuth + Promotions API",
        "auth_url": url_for("login", _external=True),
    }


@app.route("/login")
def login():
    state = os.urandom(8).hex()
    session["oauth_state"] = state
    return redirect(_auth_url(state))


@app.route("/callback")
def callback():
    state = request.args.get("state")
    if state != session.get("oauth_state"):
        abort(400, "Invalid state parameter")

    code = request.args.get("code")
    if not code:
        abort(400, "Missing code param")

    data = _request_token(code)

    # Mercado Livre responde user_id dentro do JSON
    user_id = str(data.get("user_id") or data.get("x_ml_user_id"))
    if not user_id:
        abort(400, "Couldn't find user_id in token response")

    with SessionLocal() as db:
        _save_token(db, data, user_id)

    return {
        "msg": "OAuth successful",
        "user_id": user_id,
    }


###############################################################################
# API proxies (prices & promotions)
###############################################################################


def ml_get(path: str, token: Token, params: dict | None = None, headers: dict | None = None):
    headers = headers or {}
    headers.update({"Authorization": f"Bearer {token.access_token}"})
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code == 401 and "expired" in resp.text.lower():
        # Refresh and retry once
        with SessionLocal() as db:
            refreshed = _save_token(db, _refresh_token(token), token.user_id)
        return ml_get(path, refreshed, params, headers)
    resp.raise_for_status()
    return resp.json()


# 1) Get sale price for a single item
@app.route("/items/<item_id>/price")
def item_sale_price(item_id):
    user_id = request.args.get("user_id")
    if not user_id:
        abort(400, "user_id query param required")

    token = get_token(user_id)
    data = ml_get(f"/items/{item_id}/sale_price", token, params={"context": "channel_marketplace"})
    return jsonify(data)


# 2) List active seller promotions for user
@app.route("/promotions")
def list_promotions():
    user_id = request.args.get("user_id")
    if not user_id:
        abort(400, "user_id query param required")
    token = get_token(user_id)

    data = ml_get(
        f"/marketplace/seller-promotions/users/{user_id}",
        token,
        headers={"version": "v2"},
    )
    return jsonify(data)


# 3) List items inside a promotion (e.g., DEAL, DOD)
@app.route("/promotions/<promotion_id>/items")
def promotion_items(promotion_id):
    user_id = request.args.get("user_id")
    promotion_type = request.args.get("promotion_type", "DEAL")  # DEAL, DOD, PRICE_DISCOUNT etc.
    status_filter = request.args.get("status", "started")  # started, candidate, ended...

    token = get_token(user_id)
    params = {
        "user_id": user_id,
        "status": status_filter,
        "promotion_type": promotion_type,
    }

    data = ml_get(
        f"/marketplace/seller-promotions/promotions/{promotion_id}/items",
        token,
        params=params,
        headers={"version": "v2"},
    )
    return jsonify(data)

###############################################################################
# Error handling + helpers
###############################################################################

@app.errorhandler(SQLAlchemyError)
@app.errorhandler(requests.RequestException)
def handle_error(err):
    app.logger.exception(err)
    return {
        "error": str(err),
    }, 500

###############################################################################
# Entry‑point
###############################################################################

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
