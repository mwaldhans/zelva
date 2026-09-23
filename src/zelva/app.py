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
    base_dir = Path(configured_dir) if configured_dir else Path(app.instance_path)
    return base_dir / "pattern_overrides.json"


def _custom_patterns_path(app: Flask) -> Path:
    configured_dir = app.config.get("DATA_DIR") or os.getenv("ZELVA_DATA_DIR")
    base_dir = Path(configured_dir) if configured_dir else Path(app.instance_path)
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


def _load_deleted_patterns(app: Flask) -> set[str]:
    rows = _get_db().execute("SELECT pattern_id FROM deleted_patterns").fetchall()
    return {row["pattern_id"] for row in rows}


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

        for key in ("start_x", "start_y", "start_angle"):
            value = override.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[key] = float(value)

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


def _load_pattern_overrides_file(app: Flask) -> dict[str, dict[str, object]]:
    overrides_path = _pattern_overrides_path(app)
    if not overrides_path.exists():
        return {}

    try:
        raw_overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return _clean_pattern_overrides(raw_overrides)


def _save_pattern_overrides_file(app: Flask, overrides: dict[str, dict[str, object]]) -> None:
    overrides_path = _pattern_overrides_path(app)
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_custom_patterns_file(app: Flask) -> dict[str, dict[str, object]]:
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


def _save_custom_patterns_file(app: Flask, patterns: dict[str, dict[str, object]]) -> None:
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
    for key in ("start_x", "start_y", "start_angle"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            pattern[key] = float(value)
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

    for key in ("start_x", "start_y", "start_angle"):
        value = payload.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value:
                try:
                    value = float(value)
                except ValueError:
                    value = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            override[key] = float(value)

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


def _pattern_from_row(row: sqlite3.Row) -> dict[str, object]:
    pattern: dict[str, object] = {}
    for key in ("category", "name", "hint", "initial_text"):
        if row[key] is not None and row[key] != "":
            pattern[key] = row[key]
    for key in ("start_x", "start_y", "start_angle"):
        if row[key] is not None:
            pattern[key] = float(row[key])
    if row["initial_lines"] is not None:
        pattern["initial_lines"] = int(row["initial_lines"])
    if row["commands_json"]:
        pattern["commands"] = json.loads(row["commands_json"])
    return pattern


def _load_pattern_overrides(app: Flask) -> dict[str, dict[str, object]]:
    rows = _get_db().execute(
        "SELECT pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle FROM pattern_overrides"
    ).fetchall()
    return {row["pattern_id"]: _pattern_from_row(row) for row in rows}


def _save_pattern_overrides(app: Flask, overrides: dict[str, dict[str, object]]) -> None:
    db = _get_db()
    db.execute("DELETE FROM pattern_overrides")
    for pattern_id, override in overrides.items():
        db.execute(
            """
            INSERT INTO pattern_overrides
                (pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                override.get("category"),
                override.get("name"),
                override.get("hint"),
                override.get("initial_text"),
                override.get("initial_lines"),
                json.dumps(override.get("commands"), ensure_ascii=False) if "commands" in override else None,
                override.get("start_x"),
                override.get("start_y"),
                override.get("start_angle"),
            ),
        )
    db.commit()


def _load_custom_patterns(app: Flask) -> dict[str, dict[str, object]]:
    rows = _get_db().execute(
        "SELECT pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle FROM custom_patterns"
    ).fetchall()
    return {row["pattern_id"]: _pattern_from_row(row) for row in rows}


def _save_custom_patterns(app: Flask, patterns: dict[str, dict[str, object]]) -> None:
    db = _get_db()
    db.execute("DELETE FROM custom_patterns")
    for pattern_id, pattern in patterns.items():
        db.execute(
            """
            INSERT INTO custom_patterns
                (pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                pattern.get("category") or "Obecne",
                pattern.get("name") or pattern_id,
                pattern.get("hint") or "",
                pattern.get("initial_text") or "",
                pattern.get("initial_lines") or 2,
                json.dumps(pattern.get("commands") or [], ensure_ascii=False),
                pattern.get("start_x"),
                pattern.get("start_y"),
                pattern.get("start_angle"),
            ),
        )
    db.commit()


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
        client_kwargs={"scope": "openid email profile"},
    )


def _current_user() -> dict[str, str] | None:
    user = session.get("user")
    return user if isinstance(user, dict) else None


def _is_admin(user: dict[str, str] | None) -> bool:
    admin_email = current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    return bool(user and user.get("email", "").lower() == admin_email.lower())


def _is_allowed_login_email(email: str) -> bool:
    if email.count("@") != 1:
        return False

    domain = email.rsplit("@", 1)[1]
    labels = domain.split(".")
    if any(not label for label in labels):
        return False

    def is_allowed_domain(remaining_labels: list[str]) -> bool:
        if ".".join(remaining_labels) == LOGIN_DOMAIN:
            return True
        if len(remaining_labels) <= 1:
            return False
        return is_allowed_domain(remaining_labels[1:])

    return is_allowed_domain(labels)


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
                user_name TEXT NOT NULL DEFAULT '',
                user_email TEXT NOT NULL DEFAULT '',
                time_seconds INTEGER NOT NULL DEFAULT 0,
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
        progress_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(user_progress)").fetchall()
        }
        for column, definition in (
            ("user_name", "TEXT NOT NULL DEFAULT ''"),
            ("user_email", "TEXT NOT NULL DEFAULT ''"),
            ("time_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in progress_columns:
                conn.execute(f"ALTER TABLE user_progress ADD COLUMN {column} {definition}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pattern_overrides (
                pattern_id TEXT PRIMARY KEY,
                category TEXT,
                name TEXT,
                hint TEXT,
                initial_text TEXT,
                initial_lines INTEGER,
                commands_json TEXT,
                start_x REAL,
                start_y REAL,
                start_angle REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_patterns (
                pattern_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                hint TEXT NOT NULL DEFAULT '',
                initial_text TEXT NOT NULL DEFAULT '',
                initial_lines INTEGER NOT NULL DEFAULT 2,
                commands_json TEXT NOT NULL,
                start_x REAL,
                start_y REAL,
                start_angle REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deleted_patterns (
                pattern_id TEXT PRIMARY KEY
            )
            """
        )

        table_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(custom_patterns)").fetchall()
        }
        for column, definition in (
            ("category", "TEXT NOT NULL DEFAULT 'Obecne'"),
            ("name", "TEXT NOT NULL DEFAULT ''"),
            ("hint", "TEXT NOT NULL DEFAULT ''"),
            ("initial_text", "TEXT NOT NULL DEFAULT ''"),
            ("initial_lines", "INTEGER NOT NULL DEFAULT 2"),
            ("commands_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("start_x", "REAL"),
            ("start_y", "REAL"),
            ("start_angle", "REAL"),
        ):
            if column not in table_columns:
                conn.execute(f"ALTER TABLE custom_patterns ADD COLUMN {column} {definition}")

        override_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pattern_overrides)").fetchall()
        }
        for column, definition in (
            ("category", "TEXT"),
            ("name", "TEXT"),
            ("hint", "TEXT"),
            ("initial_text", "TEXT"),
            ("initial_lines", "INTEGER"),
            ("commands_json", "TEXT"),
            ("start_x", "REAL"),
            ("start_y", "REAL"),
            ("start_angle", "REAL"),
        ):
            if column not in override_columns:
                conn.execute(f"ALTER TABLE pattern_overrides ADD COLUMN {column} {definition}")

        override_count = conn.execute("SELECT COUNT(*) FROM pattern_overrides").fetchone()[0]
        if override_count == 0:
            for pattern_id, override in _load_pattern_overrides_file(app).items():
                conn.execute(
                    """
                    INSERT INTO pattern_overrides
                        (pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pattern_id,
                        override.get("category"),
                        override.get("name"),
                        override.get("hint"),
                        override.get("initial_text"),
                        override.get("initial_lines"),
                        json.dumps(override.get("commands"), ensure_ascii=False) if "commands" in override else None,
                        override.get("start_x"),
                        override.get("start_y"),
                        override.get("start_angle"),
                    ),
                )

        custom_count = conn.execute("SELECT COUNT(*) FROM custom_patterns").fetchone()[0]
        if custom_count == 0:
            for pattern_id, pattern in _load_custom_patterns_file(app).items():
                sanitized = _sanitize_custom_pattern({"id": pattern_id, **pattern})
                if sanitized is None:
                    continue
                _, clean_pattern = sanitized
                conn.execute(
                    """
                    INSERT INTO custom_patterns
                        (pattern_id, category, name, hint, initial_text, initial_lines, commands_json, start_x, start_y, start_angle)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pattern_id,
                        clean_pattern["category"],
                        clean_pattern["name"],
                        clean_pattern["hint"],
                        clean_pattern["initial_text"],
                        clean_pattern["initial_lines"],
                        json.dumps(clean_pattern["commands"], ensure_ascii=False),
                        clean_pattern.get("start_x"),
                        clean_pattern.get("start_y"),
                        clean_pattern.get("start_angle"),
                    ),
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
        if not _is_allowed_login_email(email) or not subject or not userinfo.get("email_verified", False):
            session.clear()
            return "Přihlásit se mohou pouze ověřené účty z domény gymnzidlo.cz nebo jejích subdomén.", 403

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
        deleted_patterns = _load_deleted_patterns(app)
        pattern_ids = [pattern_id for pattern_id in _admin_pattern_ids() if pattern_id not in deleted_patterns]
        return render_template(
            "admin.html",
            pattern_ids=pattern_ids + [pattern_id for pattern_id in custom_patterns if pattern_id not in _admin_pattern_ids()],
            custom_pattern_ids_json=json.dumps(list(custom_patterns), ensure_ascii=False),
            overrides_json=json.dumps(overrides, ensure_ascii=False, indent=2),
        )

    @app.get("/admin/results")
    @_admin_required
    def admin_results() -> str:
        return render_template("admin_results.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return jsonify({"status": "ok", "service": "zelva-web"}), 200

    @app.get("/api/pattern-overrides")
    def get_pattern_overrides() -> tuple[dict[str, dict[str, dict[str, object]]], int]:
        deleted_patterns = _load_deleted_patterns(app)
        return jsonify({
            "overrides": _load_pattern_overrides(app),
            "custom_patterns": _load_custom_patterns(app),
            "deleted_patterns": sorted(deleted_patterns),
        }), 200

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

    @app.delete("/api/custom-patterns/<pattern_id>")
    @_admin_required
    def delete_custom_pattern(pattern_id: str) -> tuple[dict[str, str], int]:
        if pattern_id in _pattern_ids_from_source():
            db = _get_db()
            db.execute("INSERT OR IGNORE INTO deleted_patterns (pattern_id) VALUES (?)", (pattern_id,))
            db.commit()
            return jsonify({"pattern_id": pattern_id}), 200

        patterns = _load_custom_patterns(app)
        if pattern_id not in patterns:
            return jsonify({"error": "Vlastní úloha nebyla nalezena."}), 404

        patterns.pop(pattern_id)
        _save_custom_patterns(app, patterns)
        return jsonify({"pattern_id": pattern_id}), 200

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
            SELECT pattern_id, solution_text, solved, score, time_seconds, updated_at
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
                "time_seconds": int(row["time_seconds"]),
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
        time_seconds = max(0, int(payload.get("time_seconds", 0) or 0))
        user = _current_user() or {}
        user_id = user.get("sub", g.browser_user_id)
        user_name = str(user.get("name", ""))
        user_email = str(user.get("email", ""))

        db = _get_db()
        db.execute(
            """
            INSERT INTO user_progress
                (user_id, pattern_id, solution_text, solved, score, user_name, user_email, time_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, pattern_id) DO UPDATE SET
                solution_text = excluded.solution_text,
                solved = excluded.solved,
                score = excluded.score,
                user_name = excluded.user_name,
                user_email = excluded.user_email,
                time_seconds = excluded.time_seconds,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, pattern_id, solution_text, int(solved), score, user_name, user_email, time_seconds),
        )
        db.commit()

        return jsonify(
            {
                "pattern_id": pattern_id,
                "solution_text": solution_text,
                "solved": solved,
                "score": score,
                "time_seconds": time_seconds,
            }
        ), 200

    @app.get("/api/admin/progress")
    @_admin_required
    def get_admin_progress() -> tuple[dict[str, list[dict[str, object]]], int]:
        rows = _get_db().execute(
            """
            SELECT user_id, user_name, user_email, pattern_id, solution_text,
                   solved, score, time_seconds, updated_at
            FROM user_progress
            ORDER BY updated_at DESC, user_email, pattern_id
            """
        ).fetchall()
        return jsonify({
            "items": [
                {
                    "user_id": row["user_id"],
                    "user_name": row["user_name"],
                    "user_email": row["user_email"],
                    "pattern_id": row["pattern_id"],
                    "solution_text": row["solution_text"],
                    "solved": bool(row["solved"]),
                    "score": float(row["score"]),
                    "time_seconds": int(row["time_seconds"]),
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        }), 200

    return app


app = create_app()
