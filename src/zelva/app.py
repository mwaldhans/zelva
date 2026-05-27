from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from flask import Flask, current_app, g, jsonify, render_template, request


def _database_path(app: Flask) -> str:
    configured = app.config.get("DATABASE")
    if configured:
        return str(configured)
    return str(Path(app.instance_path) / "zelva.db")


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
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    _init_db(app)
    app.teardown_appcontext(_close_db)

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

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return jsonify({"status": "ok", "service": "zelva-web"}), 200

    @app.get("/api/progress")
    def get_progress() -> tuple[dict[str, list[dict[str, object]]], int]:
        db = _get_db()
        rows = db.execute(
            """
            SELECT pattern_id, solution_text, solved, score, updated_at
            FROM user_progress
            WHERE user_id = ?
            ORDER BY pattern_id
            """,
            (g.browser_user_id,),
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
            (g.browser_user_id, pattern_id, solution_text, int(solved), score),
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
