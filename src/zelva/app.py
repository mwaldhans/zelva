from __future__ import annotations

import json
import os
import re
import sqlite3
from functools import wraps
from pathlib import Path
from uuid import uuid4

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, current_app, g, jsonify, redirect, render_template, request, session, url_for


LOGIN_DOMAIN = "gymnzidlo.cz"
DEFAULT_ADMIN_EMAIL = "waldhans.m@gymnzidlo.cz"

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _database_path(app: Flask) -> str:
    configured = app.config.get("DATABASE")
    if configured:
        return str(configured)
    return str(Path(app.instance_path) / "zelva.db")


def _pattern_overrides_path(app: Flask) -> Path:
    configured_dir = app.config.get("DATA_DIR") or os.getenv("ZELVA_DATA_DIR")
    base_dir = Path(configured_dir) if configured_dir else Path.home() / ".zelva"
    return base_dir / "pattern_overrides.json"


def _custom_patterns_path(app: Flask) -> Path:
    configured_dir = app.config.get("DATA_DIR") or os.getenv("ZELVA_DATA_DIR")
    base_dir = Path(configured_dir) if configured_dir else Path.home() / ".zelva"
    return base_dir / "custom_patterns.json"


def _pattern_ids_from_source() -> list[str]:
    source_path = Path(__file__).resolve().parent / "static" / "turtle.js"
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError:
        return []

    ids: list[str] = []
    for match in re.finditer(r'id:\s*"([^"]+)"', source_text):
        pattern_id = match.group(1)
        if pattern_id not in ids:
            ids.append(pattern_id)
    return ids


def _admin_pattern_ids() -> list[str]:
    return _pattern_ids_from_source()


def _clean_pattern_overrides(raw_overrides: object) -> dict[str, dict[str, object]]:
    if not isinstance(raw_overrides, dict):
        return {}

    cleaned: dict[str, dict[str, object]] = {}
    for pattern_id, override in raw_overrides.items():
        if not isinstance(pattern_id, str) or not isinstance(override, dict):
            continue

        entry: dict[str, object] = {}
        for key in ("category", "name", "hint", "initial_text"):
            value = override.get(key)
            if isinstance(value, str):
                entry[key] = value

        initial_lines = override.get("initial_lines")
        if isinstance(initial_lines, (int, float)):
            safe_lines = int(initial_lines)
            if safe_lines > 0:
                entry["initial_lines"] = safe_lines

        commands = override.get("commands")
        if isinstance(commands, list) and all(isinstance(item, str) for item in commands):
            entry["commands"] = commands

        if entry:
            cleaned[pattern_id] = entry

    return cleaned


def _load_pattern_overrides(app: Flask) -> dict[str, dict[str, object]]:
    overrides_path = _pattern_overrides_path(app)
    if not overrides_path.exists():
        return {}

    try:
        raw_overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return _clean_pattern_overrides(raw_overrides)


def _save_pattern_overrides(app: Flask, overrides: dict[str, dict[str, object]]) -> None:
    overrides_path = _pattern_overrides_path(app)
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_custom_patterns(app: Flask) -> dict[str, dict[str, object]]:
    path = _custom_patterns_path(app)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {pattern_id: pattern for pattern_id, pattern in raw.items() if isinstance(pattern_id, str) and isinstance(pattern, dict)}


def _save_custom_patterns(app: Flask, patterns: dict[str, dict[str, object]]) -> None:
    path = _custom_patterns_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(patterns, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sanitize_custom_pattern(payload: object) -> tuple[str, dict[str, object]] | None:
    if not isinstance(payload, dict):
        return None
    pattern_id = str(payload.get("id", "")).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,48}", pattern_id):
        return None
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    commands = payload.get("commands")
    if not name or not category or not isinstance(commands, list) or not commands or not all(isinstance(item, str) for item in commands):
        return None
    try:
        initial_lines = max(1, int(payload.get("initial_lines", 2)))
    except (TypeError, ValueError):
        initial_lines = 2
    pattern: dict[str, object] = {
        "category": category,
        "name": name,
        "hint": str(payload.get("hint", "")).strip(),
        "commands": [item.rstrip() for item in commands],
        "initial_lines": initial_lines,
        "initial_text": str(payload.get("initial_text", "")).strip(),
    }
    return pattern_id, pattern


def _sanitize_pattern_override(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}

    override: dict[str, object] = {}
    for key in ("category", "name", "hint", "initial_text"):
        value = payload.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value:
                override[key] = value

    initial_lines_raw = payload.get("initial_lines")
    if isinstance(initial_lines_raw, str):
        initial_lines_raw = initial_lines_raw.strip()
        if initial_lines_raw:
            try:
                initial_lines_raw = int(initial_lines_raw)
            except ValueError:
                initial_lines_raw = None

    if isinstance(initial_lines_raw, (int, float)):
        safe_lines = int(initial_lines_raw)
        if safe_lines > 0:
            override["initial_lines"] = safe_lines

    commands = payload.get("commands")
    if isinstance(commands, str):
        command_lines = [line.rstrip() for line in commands.splitlines()]
        if any(line.strip() for line in command_lines):
            override["commands"] = command_lines
    elif isinstance(commands, list) and all(isinstance(item, str) for item in commands):
        command_lines = [item.rstrip() for item in commands]
        if any(line.strip() for line in command_lines):
            override["commands"] = command_lines

    return override


def _get_pattern_override(app: Flask, pattern_id: str) -> dict[str, object]:
    overrides = _load_pattern_overrides(app)
    return dict(overrides.get(pattern_id, {}))


def _store_pattern_override(app: Flask, pattern_id: str, override: dict[str, object]) -> dict[str, object]:
    overrides = _load_pattern_overrides(app)
    if override:
        overrides[pattern_id] = override
    else:
        overrides.pop(pattern_id, None)
    _save_pattern_overrides(app, overrides)
    return override


def _get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = _database_path(current_app)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


def _close_db(_: object = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _google_client(app: Flask):
    oauth = OAuth(app)
    client_id = app.config.get("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = app.config.get("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "hd": LOGIN_DOMAIN},
    )


def _current_user() -> dict[str, str] | None:
    user = session.get("user")
    return user if isinstance(user, dict) else None


def _is_admin(user: dict[str, str] | None) -> bool:
    admin_email = current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    return bool(user and user.get("email", "").lower() == admin_email.lower())


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if user is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Přihlášení je povinné."}), 401
            return redirect(url_for("login", next=request.full_path))
        if not _is_admin(user):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Nemáte oprávnění správce."}), 403
            return "Přístup do administrace je povolen pouze správci.", 403
        return view(*args, **kwargs)

    return wrapped


def _init_db(app: Flask) -> None:
    db_path = Path(_database_path(app))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                pattern_id TEXT NOT NULL,
                solution_text TEXT NOT NULL DEFAULT '',
                solved INTEGER NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_user_pattern
            ON user_progress (user_id, pattern_id)
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
        ADMIN_EMAIL=os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL),
    )
    if test_config:
        app.config.update(test_config)

    google = _google_client(app)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    _init_db(app)
    app.teardown_appcontext(_close_db)

    @app.before_request
    def require_login() -> object | None:
        public_endpoints = {"login", "login_google", "auth_callback", "logout", "health", "static"}
        if request.endpoint in public_endpoints or _current_user() is not None:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "Přihlášení je povinné."}), 401
        return redirect(url_for("login", next=request.full_path))

    @app.before_request
    def ensure_browser_user() -> None:
        browser_user_id = request.cookies.get("zelva_user_id")
        if browser_user_id:
            g.browser_user_id = browser_user_id
            g.should_set_user_cookie = False
            return

        g.browser_user_id = str(uuid4())
        g.should_set_user_cookie = True

    @app.after_request
    def persist_browser_user_cookie(response):
        if getattr(g, "should_set_user_cookie", False):
            response.set_cookie(
                "zelva_user_id",
                g.browser_user_id,
                max_age=60 * 60 * 24 * 365,
                samesite="Lax",
                httponly=False,
            )
        return response

    @app.get("/login")
    def login():
        if _current_user() is not None:
            return redirect(request.args.get("next") or url_for("index"))
        if google is None:
            return render_template("login.html", google_configured=False), 503
        next_url = request.args.get("next") or url_for("index")
        session["login_next"] = next_url if next_url.startswith("/") else url_for("index")
        return render_template("login.html", google_configured=True)

    @app.get("/login/google")
    def login_google():
        if google is None:
            return redirect(url_for("login"))
        next_url = request.args.get("next") or url_for("index")
        session["login_next"] = next_url if next_url.startswith("/") else url_for("index")
        return google.authorize_redirect(url_for("auth_callback", _external=True))

    @app.get("/auth/callback")
    def auth_callback():
        if google is None:
            return "Google přihlášení není nakonfigurované.", 503
        token = google.authorize_access_token()
        userinfo = token.get("userinfo") or google.userinfo()
        email = str(userinfo.get("email", "")).strip().lower()
        subject = str(userinfo.get("sub", "")).strip()
        if not email.endswith(f"@{LOGIN_DOMAIN}") or not subject or not userinfo.get("email_verified", False):
            session.clear()
            return "Přihlásit se mohou pouze ověřené účty z domény gymnzidlo.cz.", 403

        session["user"] = {
            "sub": subject,
            "email": email,
            "name": str(userinfo.get("name", "")).strip(),
            "picture": str(userinfo.get("picture", "")).strip(),
        }
        return redirect(session.pop("login_next", url_for("index")))

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.context_processor
    def inject_auth_state():
        user = _current_user()
        return {"current_user": user, "current_user_is_admin": _is_admin(user)}

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/sandbox")
    def sandbox() -> str:
        return render_template("sandbox.html")

    @app.get("/admin")
    @_admin_required
    def admin() -> str:
        overrides = _load_pattern_overrides(app)
        custom_patterns = _load_custom_patterns(app)
        return render_template(
            "admin.html",
            pattern_ids=_admin_pattern_ids() + [pattern_id for pattern_id in custom_patterns if pattern_id not in _admin_pattern_ids()],
            overrides_json=json.dumps(overrides, ensure_ascii=False, indent=2),
        )

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return jsonify({"status": "ok", "service": "zelva-web"}), 200

    @app.get("/api/pattern-overrides")
    def get_pattern_overrides() -> tuple[dict[str, dict[str, dict[str, object]]], int]:
        return jsonify({"overrides": _load_pattern_overrides(app), "custom_patterns": _load_custom_patterns(app)}), 200

    @app.post("/api/custom-patterns")
    @_admin_required
    def create_custom_pattern() -> tuple[dict[str, object], int]:
        sanitized = _sanitize_custom_pattern(request.get_json(silent=True) or {})
        if sanitized is None:
            return jsonify({"error": "Vyplň platné ID, název, kategorii a alespoň jeden příkaz."}), 400
        pattern_id, pattern = sanitized
        if pattern_id in _pattern_ids_from_source() or pattern_id in _load_custom_patterns(app):
            return jsonify({"error": "Úloha s tímto ID už existuje."}), 409
        patterns = _load_custom_patterns(app)
        patterns[pattern_id] = pattern
        _save_custom_patterns(app, patterns)
        return jsonify({"pattern_id": pattern_id, "pattern": pattern}), 201

    @app.get("/api/pattern-overrides/<pattern_id>")
    @_admin_required
    def get_pattern_override(pattern_id: str) -> tuple[dict[str, object], int]:
        return jsonify({"pattern_id": pattern_id, "override": _get_pattern_override(app, pattern_id)}), 200

    @app.put("/api/pattern-overrides/<pattern_id>")
    @_admin_required
    def update_pattern_override(pattern_id: str) -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        override = _sanitize_pattern_override(payload)
        _store_pattern_override(app, pattern_id, override)
        return jsonify({"pattern_id": pattern_id, "override": override}), 200

    @app.delete("/api/pattern-overrides/<pattern_id>")
    @_admin_required
    def delete_pattern_override(pattern_id: str) -> tuple[dict[str, object], int]:
        _store_pattern_override(app, pattern_id, {})
        return jsonify({"pattern_id": pattern_id, "override": {}}), 200

    @app.put("/api/pattern-overrides")
    @_admin_required
    def update_pattern_overrides() -> tuple[dict[str, dict[str, dict[str, object]]], int]:
        payload = request.get_json(silent=True) or {}
        raw_overrides = payload.get("overrides", payload)
        overrides = _clean_pattern_overrides(raw_overrides)
        _save_pattern_overrides(app, overrides)
        return jsonify({"overrides": overrides}), 200

    @app.delete("/api/pattern-overrides")
    @_admin_required
    def delete_pattern_overrides() -> tuple[dict[str, dict[str, dict[str, object]]], int]:
        _save_pattern_overrides(app, {})
        return jsonify({"overrides": {}}), 200

    @app.get("/api/progress")
    def get_progress() -> tuple[dict[str, list[dict[str, object]]], int]:
        user_id = session.get("user", {}).get("sub", g.browser_user_id)
        db = _get_db()
        rows = db.execute(
            """
            SELECT pattern_id, solution_text, solved, score, updated_at
            FROM user_progress
            WHERE user_id = ?
            ORDER BY pattern_id
            """,
            (user_id,),
        ).fetchall()
        items = [
            {
                "pattern_id": row["pattern_id"],
                "solution_text": row["solution_text"],
                "solved": bool(row["solved"]),
                "score": float(row["score"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return jsonify({"items": items}), 200

    @app.put("/api/progress/<pattern_id>")
    def upsert_progress(pattern_id: str) -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        solution_text = str(payload.get("solution_text", ""))
        solved = bool(payload.get("solved", False))
        score = float(payload.get("score", 0))

        db = _get_db()
        db.execute(
            """
            INSERT INTO user_progress (user_id, pattern_id, solution_text, solved, score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, pattern_id) DO UPDATE SET
                solution_text = excluded.solution_text,
                solved = excluded.solved,
                score = excluded.score,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session.get("user", {}).get("sub", g.browser_user_id), pattern_id, solution_text, int(solved), score),
        )
        db.commit()

        return jsonify(
            {
                "pattern_id": pattern_id,
                "solution_text": solution_text,
                "solved": solved,
                "score": score,
            }
        ), 200

    return app


app = create_app()
