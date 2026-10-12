import os

from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_dance.contrib.google import make_google_blueprint, google
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

from models import db, User, Message
from chatbot import ask_gemini

load_dotenv()

# Allow HTTP during local OAuth testing only. Remove in production (HTTPS).
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# How many past messages to feed back to the model for context.
HISTORY_TURNS = 10

# Chat input limits. The chat endpoint is open to guests and spends Gemini quota.
MAX_MESSAGE_CHARS = 2000
LANGUAGES = {
    "English", "Hindi", "Bengali", "Tamil", "Telugu", "Marathi",
    "Gujarati", "Kannada", "Malayalam", "Punjabi", "Urdu", "Odia",
}  # same list the UI offers; anything else would be pasted into the model prompt verbatim

app = Flask(__name__)

# Trust the host's proxy so url_for / OAuth callbacks use https in production.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Some hosts (e.g. Render, Heroku) hand out "postgres://" URLs, but SQLAlchemy
# needs "postgresql://". Normalize it so the same code works everywhere.
database_url = os.getenv("DATABASE_URL", "sqlite:///healthbot.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# A known fallback key would let anyone forge a login session, so refuse to start without one.
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    if os.getenv("FLASK_DEBUG") == "1":
        secret_key = "dev-only-insecure-key"
    else:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` and add it to .env "
            "(or set FLASK_DEBUG=1 for throwaway local development)."
        )
app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site form posts riding the login cookie
app.config["SESSION_COOKIE_SECURE"] = True      # `python app.py` turns this off for plain-http local dev
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

db.init_app(app)
CORS(app)

login_manager = LoginManager()
# Redirect unauthenticated users to the landing page, not the POST-only API.
login_manager.login_view = "home"
login_manager.init_app(app)

google_bp = make_google_blueprint(
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
    ],
    redirect_url="/google/authorized",
)

app.register_blueprint(google_bp, url_prefix="/login")

with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------

@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# ----------------------------------------------------------------------------
# Health check
# ----------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "SwasthyaAI API"})


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    user = User(
        name=name,
        email=email,
        password=generate_password_hash(password),
    )

    db.session.add(user)
    db.session.commit()

    login_user(user)

    return jsonify(
        {
            "message": "User registered successfully",
            "user_id": user.id,
            "name": user.name,
        }
    ), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(user)

    return jsonify(
        {
            "message": "Login successful",
            "user_id": user.id,
            "name": user.name,
        }
    )


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/google/authorized")
def google_authorized():
    if not google.authorized:
        return redirect(url_for("home"))

    try:
        response = google.get("/oauth2/v2/userinfo")

        if not response.ok:
            return redirect(url_for("home"))

        info = response.json()

        email = (info.get("email") or "").strip().lower()
        name = info.get("name") or info.get("given_name") or "User"

        if not email:
            return redirect(url_for("home"))

        user = User.query.filter_by(email=email).first()

        if not user:
            user = User(
                name=name,
                email=email,
                password=generate_password_hash(os.urandom(24).hex()),
            )
            db.session.add(user)
            db.session.commit()

        login_user(user)

        return redirect(url_for("dashboard"))

    except Exception:
        app.logger.exception("Google OAuth error")
        return redirect(url_for("home"))


# ----------------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------------

def build_history(user_id):
    """Return recent conversation as a plain-text transcript for the model."""
    recent = (
        Message.query.filter_by(user_id=user_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    recent.reverse()

    lines = []
    for m in recent:
        speaker = "User" if m.role == "user" else "Assistant"
        lines.append(f"{speaker}: {m.content}")

    return "\n".join(lines)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    message = (data.get("message") or "").strip() if isinstance(data.get("message"), str) else ""
    language = data.get("language")
    if language not in LANGUAGES:
        language = "English"

    if not message:
        return jsonify({"error": "Message is required"}), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify({"error": f"Message is too long (max {MAX_MESSAGE_CHARS} characters)"}), 400

    # Only signed-in users get remembered context and saved history.
    history = ""
    if current_user.is_authenticated:
        history = build_history(current_user.id)

    try:
        answer = ask_gemini(message, history, language)
    except Exception:
        # Log the cause server-side; the raw error can include request details we shouldn't show users.
        app.logger.exception("Gemini request failed")
        return jsonify({"error": "AI service unavailable. Please try again."}), 500

    # Persist the exchange for signed-in users.
    if current_user.is_authenticated:
        db.session.add(
            Message(user_id=current_user.id, role="user", content=message)
        )
        db.session.add(
            Message(user_id=current_user.id, role="assistant", content=answer)
        )
        db.session.commit()

    return jsonify({"answer": answer, "language": language})


@app.route("/api/history")
@login_required
def history():
    messages = (
        Message.query.filter_by(user_id=current_user.id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return jsonify(
        [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    )


@app.route("/api/history/clear", methods=["POST"])
@login_required
def clear_history():
    Message.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"message": "History cleared"})


@app.route("/api/user")
@login_required
def user():
    return jsonify(
        {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
        }
    )


if __name__ == "__main__":
    # Local development only (production runs under gunicorn, see Procfile).
    app.config["SESSION_COOKIE_SECURE"] = False  # plain http://localhost
    # The Werkzeug debugger allows remote code execution, so it is opt-in and the server
    # listens on localhost only. Use FLASK_DEBUG=1 and/or HOST=0.0.0.0 deliberately.
    app.run(
        debug=os.getenv("FLASK_DEBUG") == "1",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
    )
