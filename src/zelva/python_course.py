# -*- coding: utf-8 -*-
"""Programov?n? v Pythonu - sada ?loh, odevzd?v?n? a p?ehledy pro u?itele.

P?ihl??en? ?e?? hlavn? aplikace (Google OAuth); tento blueprint z p?ihl??en?ho
u?ivatele jen odvod? roli (u?itel/student).
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import random
import time
from datetime import datetime
from functools import wraps
from io import BytesIO
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytz
from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for,
)

from .content_transfer import read_content_upload

bp = Blueprint("python", __name__, url_prefix="/python")

AZ_BOARD_SIZE = 4
AZ_SHAPES = ("●", "▲", "■", "◆", "★", "✚")
AZ_SHAPE_INTERVAL_MS = 600
AZ_REACTION_WINDOW_MS = 1200

AZ_QUESTIONS = [
    {
        "question": "Jaký typ vrátí výraz 3 / 2 v Pythonu 3?",
        "options": ["int", "float", "str", "bool"],
        "answer": 1,
    },
    {
        "question": "Který zápis vytvoří prázdný seznam?",
        "options": ["{}", "()", "[]", "set()"],
        "answer": 2,
    },
    {
        "question": "Co vypíše print(len('želva'))?",
        "options": ["4", "5", "6", "Chybu"],
        "answer": 1,
    },
    {
        "question": "Které klíčové slovo vrací hodnotu z funkce?",
        "options": ["yield", "return", "break", "pass"],
        "answer": 1,
    },
    {
        "question": "Jak se správně porovnává, zda jsou dvě hodnoty stejné?",
        "options": ["=", "==", "!=", ":="],
        "answer": 1,
    },
    {
        "question": "Jaký bude výsledek výrazu 2 ** 3?",
        "options": ["6", "8", "9", "5"],
        "answer": 1,
    },
    {
        "question": "Která metoda přidá prvek na konec seznamu?",
        "options": ["add()", "push()", "append()", "insert_end()"],
        "answer": 2,
    },
    {
        "question": "Jak začíná definice funkce s názvem pozdrav?",
        "options": ["function pozdrav():", "def pozdrav():", "func pozdrav():", "define pozdrav():"],
        "answer": 1,
    },
    {
        "question": "Co vrátí bool(0)?",
        "options": ["True", "False", "0", "None"],
        "answer": 1,
    },
    {
        "question": "Který cyklus se běžně používá k procházení prvků seznamu?",
        "options": ["for", "switch", "repeat", "loop"],
        "answer": 0,
    },
    {
        "question": "Jaký typ dat ukládá dvojice klíč–hodnota?",
        "options": ["list", "tuple", "dict", "set"],
        "answer": 2,
    },
    {
        "question": "Co vypíše print('Py' + 'thon')?",
        "options": ["Py thon", "Python", "Py+thon", "Chybu"],
        "answer": 1,
    },
]


def database_path(app):
    configured = app.config.get("PYTHON_DATABASE")
    if configured:
        return str(configured)
    return os.path.join(app.instance_path, "python.db")


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_connection():
    return _connect(database_path(current_app))


def teacher_emails(app):
    configured = app.config.get("PYTHON_TEACHER_EMAILS") or []
    emails = {e.strip().lower() for e in configured if e and e.strip()}
    admin = (app.config.get("ADMIN_EMAIL") or "").strip().lower()
    if admin:
        emails.add(admin)
    return emails


@bp.app_template_filter("localize_time")
def localize_time_filter(utc_str):
    try:
        utc_dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str
    utc_dt = utc_dt.replace(tzinfo=pytz.utc)
    local_dt = utc_dt.astimezone(pytz.timezone("Europe/Prague"))
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


@bp.app_template_test("search")
def search_filter(value, pattern):
    return re.search(pattern, value) is not None


def init_python_db(app):
    os.makedirs(os.path.dirname(database_path(app)), exist_ok=True)
    init_db(database_path(app))


@bp.before_request
def sync_session_with_login():
    user = session.get("user")
    if not user or not user.get("email"):
        session.pop("username", None)
        session.pop("role", None)
        return None
    email = user["email"].strip().lower()
    role = "teacher" if email in teacher_emails(current_app) else "student"
    session["username"] = email
    session["role"] = role
    if role == "student":
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO students (email, name) VALUES (?, ?)",
                (email, user.get("name") or email),
            )
            conn.commit()
        finally:
            conn.close()
    return None


@bp.route("/")
def home():
    if session.get("role") == "teacher":
        return redirect(url_for("python.teacher_dashboard"))
    return redirect(url_for("python.student_dashboard"))


def init_db(database_path):
    conn = _connect(database_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            teacher_code TEXT NOT NULL,
            section TEXT,
            display_order INTEGER,
            section_order INTEGER,
            help_text TEXT,
            test_input_run TEXT,
            test_input_submit TEXT,
            test_call_run TEXT,
            test_call_submit TEXT
        )
    ''')
    # Pokud tabulka již existuje, pokusíme se přidat sloupce
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN display_order INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN section_order INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN help_text TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN test_input_run TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN test_input_submit TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE assignments ADD COLUMN precopy_lines INTEGER NOT NULL DEFAULT 1"
        )
    except sqlite3.OperationalError:
        # sloupec už existuje
        pass
    try:
        conn.execute(
            "ALTER TABLE assignments ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE assignments ADD COLUMN required INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN time_taken INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        # Sloupec už existuje
        pass
    conn.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER,
            student_email TEXT,
            student_code TEXT,
            result TEXT,
            teacher_output TEXT,
            student_output TEXT,
            help_used INTEGER DEFAULT 0,
            submission_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id)
        )
    ''')
    try:
        conn.execute("ALTER TABLE submissions ADD COLUMN help_used INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN time_taken INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    conn.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            class_id INTEGER,
            FOREIGN KEY (class_id) REFERENCES classes(id)
        )
    ''')
    # Tabulka pro přiřazování úkolů třídám s deadliny
    conn.execute('''
        CREATE TABLE IF NOT EXISTS class_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            deadline TIMESTAMP NOT NULL,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id),
            FOREIGN KEY (class_id) REFERENCES classes(id)
        )
    ''')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS class_wall_sections (
            class_id       INTEGER NOT NULL,
            section        TEXT    NOT NULL,
            section_order  INTEGER NOT NULL,
            PRIMARY KEY(class_id, section)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS az_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_a_email TEXT NOT NULL,
            player_a_name TEXT NOT NULL,
            player_b_email TEXT,
            player_b_name TEXT,
            status TEXT NOT NULL,
            turn_email TEXT,
            board TEXT NOT NULL,
            question_index INTEGER,
            winner_email TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE az_games ADD COLUMN current_question TEXT")
    except sqlite3.OperationalError:
        pass
    for column, definition in (
        ("challenge_cell", "INTEGER"),
        ("challenge_started_at", "REAL"),
        ("challenge_target_ms", "INTEGER"),
        ("challenge_frames", "TEXT"),
        ("challenge_reactions", "TEXT"),
        ("challenge_active", "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE az_games ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_az_games_waiting
        ON az_games(status, created_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS az_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            answer INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            source_key TEXT
        )
    """)
    question_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(az_questions)")
    }
    if "source_key" not in question_columns:
        conn.execute("ALTER TABLE az_questions ADD COLUMN source_key TEXT")
    if conn.execute("SELECT COUNT(*) FROM az_questions").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO az_questions (question, options, answer, source_key) VALUES (?, ?, ?, ?)",
            [
                (
                    question["question"],
                    json.dumps(question["options"], ensure_ascii=False),
                    question["answer"],
                    uuid5(NAMESPACE_URL, "zelva:azkviz:" + question["question"]).hex,
                )
                for question in AZ_QUESTIONS
            ],
        )
    default_keys = {
        question["question"]: uuid5(
            NAMESPACE_URL, "zelva:azkviz:" + question["question"]
        ).hex
        for question in AZ_QUESTIONS
    }
    used_source_keys = {
        row["source_key"]
        for row in conn.execute(
            "SELECT source_key FROM az_questions "
            "WHERE source_key IS NOT NULL AND source_key != ''"
        )
    }
    for row in conn.execute(
        "SELECT id, question FROM az_questions WHERE source_key IS NULL OR source_key = ''"
    ).fetchall():
        source_key = default_keys.get(row["question"])
        if source_key is None or source_key in used_source_keys:
            source_key = uuid4().hex
        used_source_keys.add(source_key)
        conn.execute(
            "UPDATE az_questions SET source_key = ? WHERE id = ?",
            (source_key, row["id"]),
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_az_questions_source_key "
        "ON az_questions(source_key)"
    )
    for game in conn.execute(
        "SELECT id, board FROM az_games WHERE status IN ('waiting', 'playing')"
    ).fetchall():
        if len(json.loads(game["board"])) != AZ_BOARD_SIZE * (AZ_BOARD_SIZE + 1) // 2:
            conn.execute(
                """
                UPDATE az_games
                SET status = 'abandoned', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (game["id"],),
            )
    conn.commit()
    conn.close()


def run_python_code(code):
  
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False,encoding="utf-8") as f:
        f.write(code)
        filename = f.name
    try:
        
        
        result = subprocess.run([sys.executable, filename], capture_output=True, text=True, timeout=5,encoding="utf-8")
        
        output = result.stdout.strip()
        if result.stderr:
            output += "\n" + result.stderr.strip()
    except Exception as e:
        output = str(e)
    finally:
        os.remove(filename)
    return output


@bp.app_template_filter('format_datetime')
def format_datetime(value):
    try:
        # ISO-8601 string → datetime → formát „1. 8. 2025 16:35“
        dt = datetime.fromisoformat(value)
        return f"{dt.day}. {dt.month}. {dt.year} {dt:%H:%M}"
    except Exception:
        return value
    

# Funkce pro seskupení úloh podle sekcí
def group_assignments(assignments):
    grouped = {}
    for assignment in assignments:
        # Pokud není sekce vyplněná, použijeme "Ostatní"
        section = assignment["section"] if assignment["section"] else "Ostatní"
        if section not in grouped:
            grouped[section] = []
        grouped[section].append(assignment)
    # Seřadíme úlohy v každé sekci podle display_order (nahrazujeme None hodnotou 0) a názvu
    for sec, items in grouped.items():
        grouped[sec].sort(key=lambda a: ((a["display_order"] if a["display_order"] is not None else 0), a["title"]))
    return grouped


def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "teacher":
            flash("Přístup pouze pro učitele.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            flash("Nejprve se přihlaste.")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def _az_player_required():
    if session.get("role") not in ("student", "teacher"):
        return {"error": "AZ kvíz je dostupný pouze přihlášeným uživatelům."}, 403
    return None


def _az_admin_redirect():
    email = session.get("username", "").strip().lower()
    admin_email = (current_app.config.get("ADMIN_EMAIL") or "").strip().lower()
    if session.get("role") != "teacher" or email != admin_email:
        flash("Správa otázek je dostupná pouze administrátorovi.")
        return redirect(url_for("index"))
    return None


def _az_question_payload(row):
    options = json.loads(row["options"])
    answer = row["answer"]
    choices = list(enumerate(options))
    random.shuffle(choices)
    return {
        "id": row["id"],
        "question": row["question"],
        "options": [option for _index, option in choices],
        "answer": next(
            index for index, (original_index, _option) in enumerate(choices)
            if original_index == answer
        ),
    }


def _az_next_question(conn, current_question=None):
    rows = conn.execute(
        "SELECT id, question, options, answer FROM az_questions WHERE active = 1"
    ).fetchall()
    if not rows:
        raise RuntimeError("V AZ kvízu není žádná aktivní otázka.")
    available = [
        row for row in rows
        if current_question is None or row["id"] != current_question.get("id")
    ]
    return _az_question_payload(random.choice(available or rows))


def _az_connected(board, email):
    coordinates = [
        (q, AZ_BOARD_SIZE - 1 - row)
        for row in range(AZ_BOARD_SIZE)
        for q in range(row + 1)
    ]
    coordinate_indexes = {coordinate: index for index, coordinate in enumerate(coordinates)}
    sides = (
        {index for index, (q, _r) in enumerate(coordinates) if q == 0},
        {index for index, (_q, r) in enumerate(coordinates) if r == 0},
        {
            index
            for index, (q, r) in enumerate(coordinates)
            if q + r == AZ_BOARD_SIZE - 1
        },
    )
    if len(board) != len(coordinates):
        return False

    visited = set()
    pending = [index for index, cell in enumerate(board) if cell == email]
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))

    while pending:
        index = pending.pop()
        if index in visited:
            continue
        visited.add(index)
        q, r = coordinates[index]
        for dq, dr in directions:
            neighbor = coordinate_indexes.get((q + dq, r + dr))
            if neighbor is not None and neighbor not in visited and board[neighbor] == email:
                pending.append(neighbor)
    return all(visited & side for side in sides)


def _az_new_challenge():
    target_index = random.randint(10, 16)
    frames = []
    for _ in range(target_index):
        first, second = random.sample(AZ_SHAPES, 2)
        frames.append([first, second])
    matching_shape = random.choice(AZ_SHAPES)
    frames.append([matching_shape, matching_shape])
    return {
        "started_at": time.time() * 1000,
        "target_ms": target_index * AZ_SHAPE_INTERVAL_MS,
        "frames": frames,
    }


def _az_challenge_view(game, email):
    if not game["challenge_active"]:
        return None
    reactions = json.loads(game["challenge_reactions"] or "{}")
    opponent_email = (
        game["player_b_email"]
        if email == game["player_a_email"]
        else game["player_a_email"]
    )
    return {
        "cell": game["challenge_cell"],
        "started_at": game["challenge_started_at"],
        "target_ms": game["challenge_target_ms"],
        "frames": json.loads(game["challenge_frames"]),
        "interval_ms": AZ_SHAPE_INTERVAL_MS,
        "reaction_window_ms": AZ_REACTION_WINDOW_MS,
        "my_reacted": email in reactions,
        "opponent_reacted": opponent_email in reactions,
    }


def _az_finish_challenge(conn, game, reactions):
    board = json.loads(game["board"])
    challenge_cell = game["challenge_cell"]
    if reactions:
        winner_email = min(reactions, key=reactions.get)
        board[challenge_cell] = winner_email
        status = "playing"
        next_turn = (
            game["player_b_email"]
            if winner_email == game["player_a_email"]
            else game["player_a_email"]
        )
        feedback = "Souboj dokončen. Pole získal hráč s kratším reakčním časem."
    else:
        winner_email = None
        status = "playing"
        next_turn = (
            game["player_b_email"]
            if game["turn_email"] == game["player_a_email"]
            else game["player_a_email"]
        )
        feedback = "Nikdo nestiskl mezerník včas. Pole zůstává šedé."

    if status != "finished" and all(board):
        status = "finished"
        winner_email = None
        next_turn = None

    next_question = (
        _az_next_question(conn, json.loads(game["current_question"]))
        if status == "playing" else None
    )
    conn.execute(
        """
        UPDATE az_games
        SET board = ?, status = ?, turn_email = ?, current_question = ?,
            question_index = NULL, winner_email = ?, challenge_active = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            json.dumps(board, ensure_ascii=False),
            status,
            next_turn,
            json.dumps(next_question, ensure_ascii=False) if next_question else None,
            winner_email,
            game["id"],
        ),
    )
    updated_game = conn.execute(
        "SELECT * FROM az_games WHERE id = ?", (game["id"],)
    ).fetchone()
    return updated_game, feedback


def _az_game_view(game, email):
    player_a = game["player_a_email"] == email
    my_name = game["player_a_name"] if player_a else game["player_b_name"]
    opponent_name = game["player_b_name"] if player_a else game["player_a_name"]
    player_a_name = game["player_a_name"]
    player_b_name = game["player_b_name"]
    color_a = "A"
    color_b = "B"
    board = json.loads(game["board"])
    question = None
    my_turn = game["status"] == "playing" and game["turn_email"] == email
    if my_turn and not game["challenge_active"] and game["current_question"]:
        item = json.loads(game["current_question"])
        question = {"text": item["question"], "options": item["options"]}
    elif my_turn and not game["challenge_active"] and game["question_index"] is not None:
        item = AZ_QUESTIONS[game["question_index"]]
        question = {"text": item["question"], "options": item["options"]}

    winner = None
    if game["status"] == "finished":
        if game["winner_email"] is None:
            winner = "draw"
        else:
            winner = "you" if game["winner_email"] == email else "opponent"

    return {
        "id": game["id"],
        "status": game["status"],
        "board_size": AZ_BOARD_SIZE,
        "board": [
            color_a if cell == game["player_a_email"]
            else color_b if cell == game["player_b_email"] and cell is not None
            else "X" if cell == "X"
            else None
            for cell in board
        ],
        "my_color": color_a if player_a else color_b,
        "my_turn": my_turn,
        "my_name": my_name,
        "opponent_name": opponent_name,
        "winner": winner,
        "winner_name": (
            player_a_name if game["winner_email"] == game["player_a_email"]
            else player_b_name if game["winner_email"] == game["player_b_email"]
            else None
        ),
        "challenge": _az_challenge_view(game, email),
        "question": question,
    }


@bp.route("/azkviz")
@login_required
def azkviz():
    email = session["username"]
    conn = get_db_connection()
    try:
        games = conn.execute(
            """
            SELECT * FROM az_games
            WHERE status = 'finished'
              AND (player_a_email = ? OR player_b_email = ?)
            ORDER BY updated_at DESC, id DESC
            """,
            (email, email),
        ).fetchall()
    finally:
        conn.close()

    wins = sum(game["winner_email"] == email for game in games)
    losses = sum(
        game["winner_email"] is not None and game["winner_email"] != email
        for game in games
    )
    draws = len(games) - wins - losses
    opponents = {}
    history = []
    for game in games:
        is_player_a = game["player_a_email"] == email
        opponent_email = game["player_b_email"] if is_player_a else game["player_a_email"]
        opponent_name = game["player_b_name"] if is_player_a else game["player_a_name"]
        opponent = opponents.setdefault(
            opponent_email,
            {"name": opponent_name, "wins": 0, "losses": 0, "draws": 0},
        )
        result = (
            "draw" if game["winner_email"] is None
            else "win" if game["winner_email"] == email
            else "loss"
        )
        opponent[{"win": "wins", "loss": "losses", "draw": "draws"}[result]] += 1
        history.append({
            "opponent_name": opponent_name,
            "result": result,
            "played_at": game["updated_at"],
        })

    return render_template(
        "python/azkviz.html",
        stats={"wins": wins, "losses": losses, "draws": draws, "played": len(games)},
        opponents=sorted(opponents.values(), key=lambda item: item["name"].lower()),
        history=history[:20],
        is_admin=email == (current_app.config.get("ADMIN_EMAIL") or "").strip().lower(),
    )


@bp.route("/admin/azkviz/questions", methods=["GET", "POST"])
@login_required
def azkviz_admin_questions():
    denied = _az_admin_redirect()
    if denied:
        return denied

    conn = get_db_connection()
    try:
        if request.method == "POST":
            action = request.form.get("action", "")
            question_id_raw = request.form.get("question_id", "")
            question_id = int(question_id_raw) if question_id_raw.isdigit() else None

            if action == "delete":
                existing = conn.execute(
                    "SELECT active FROM az_questions WHERE id = ?", (question_id,)
                ).fetchone()
                if not existing:
                    flash("Otázku se nepodařilo najít.", "error")
                elif existing["active"] and conn.execute(
                    "SELECT COUNT(*) FROM az_questions WHERE active = 1"
                ).fetchone()[0] <= 1:
                    flash("Musí zůstat alespoň jedna aktivní otázka.", "error")
                else:
                    conn.execute("DELETE FROM az_questions WHERE id = ?", (question_id,))
                    conn.commit()
                    flash("Otázka byla smazána.")
                return redirect(url_for("python.azkviz_admin_questions"))

            question_text = request.form.get("question", "").strip()
            options = [option.strip() for option in request.form.get("options", "").splitlines()]
            options = [option for option in options if option]
            answer_raw = request.form.get("answer", "")
            active = int(request.form.get("active") == "1")
            if (
                action not in ("create", "update")
                or not question_text
                or len(question_text) > 500
                or not 2 <= len(options) <= 6
                or any(len(option) > 120 for option in options)
                or not answer_raw.isdigit()
                or not 0 <= int(answer_raw) < len(options)
            ):
                flash("Vyplň otázku, 2 až 6 odpovědí a označ správnou odpověď.", "error")
                return redirect(url_for("python.azkviz_admin_questions"))

            current_active = conn.execute(
                "SELECT COUNT(*) FROM az_questions WHERE active = 1"
            ).fetchone()[0]
            existing = None
            if action == "update":
                existing = conn.execute(
                    "SELECT active FROM az_questions WHERE id = ?", (question_id,)
                ).fetchone()
                if not existing:
                    flash("Otázku se nepodařilo najít.", "error")
                    return redirect(url_for("python.azkviz_admin_questions"))
            next_active_count = current_active - (
                int(existing["active"]) if existing else 0
            ) + active
            if next_active_count < 1:
                flash("Musí zůstat alespoň jedna aktivní otázka.", "error")
                return redirect(url_for("python.azkviz_admin_questions"))

            if action == "create":
                conn.execute(
                    """
                    INSERT INTO az_questions (question, options, answer, active, source_key)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        question_text,
                        json.dumps(options, ensure_ascii=False),
                        int(answer_raw),
                        active,
                        uuid4().hex,
                    ),
                )
                message = "Otázka byla přidána."
            else:
                conn.execute(
                    """
                    UPDATE az_questions
                    SET question = ?, options = ?, answer = ?, active = ?
                    WHERE id = ?
                    """,
                    (
                        question_text,
                        json.dumps(options, ensure_ascii=False),
                        int(answer_raw),
                        active,
                        question_id,
                    ),
                )
                message = "Otázka byla uložena."
            conn.commit()
            flash(message)
            return redirect(url_for("python.azkviz_admin_questions"))

        questions = conn.execute(
            "SELECT id, question, options, answer, active FROM az_questions ORDER BY id"
        ).fetchall()
        question_items = [
            {**dict(question), "options": json.loads(question["options"])}
            for question in questions
        ]
        return render_template(
            "python/azkviz_admin_questions.html",
            questions=question_items,
        )
    finally:
        conn.close()


@bp.get("/admin/azkviz/questions/export")
@login_required
def azkviz_export_questions():
    denied = _az_admin_redirect()
    if denied:
        return denied

    conn = get_db_connection()
    try:
        questions = [
            {
                "id": row["id"],
                "question": row["question"],
                "options": json.loads(row["options"]),
                "answer": row["answer"],
                "active": bool(row["active"]),
                "source_key": row["source_key"],
            }
            for row in conn.execute(
                "SELECT id, question, options, answer, active, source_key "
                "FROM az_questions ORDER BY id"
            ).fetchall()
        ]
    finally:
        conn.close()
    payload = {
        "format": "zelva-content",
        "version": 1,
        "area": "azkviz",
        "items": questions,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(
        BytesIO(content),
        mimetype="application/json",
        as_attachment=True,
        download_name="azkviz-otazky.json",
    )


@bp.post("/admin/azkviz/questions/import")
@login_required
def azkviz_import_questions():
    denied = _az_admin_redirect()
    if denied:
        return denied

    try:
        payload = read_content_upload(request.files.get("file"), "azkviz")
        items = payload.get("items")
        if not isinstance(items, list) or not items or len(items) > 5000:
            raise ValueError("Soubor musí obsahovat 1 až 5000 otázek.")
        imported = []
        imported_ids = set()
        imported_source_keys = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Soubor obsahuje neplatnou otázku.")
            question_id = item.get("id")
            question = item.get("question")
            options = item.get("options")
            answer = item.get("answer")
            active = item.get("active")
            source_key = item.get("source_key")
            if (
                type(question_id) is not int
                or question_id < 1
                or question_id in imported_ids
                or (
                    source_key is not None
                    and (
                        not isinstance(source_key, str)
                        or not re.fullmatch(r"[0-9a-f]{32}", source_key)
                        or source_key in imported_source_keys
                    )
                )
                or not isinstance(question, str)
                or not question.strip()
                or len(question.strip()) > 500
                or not isinstance(options, list)
                or not 2 <= len(options) <= 6
                or any(not isinstance(option, str) or not option.strip() or len(option.strip()) > 120 for option in options)
                or type(answer) is not int
                or not 0 <= answer < len(options)
                or not isinstance(active, bool)
            ):
                raise ValueError("Otázka má neplatné ID, text, možnosti, správnou odpověď nebo stav.")
            imported_ids.add(question_id)
            if source_key:
                imported_source_keys.add(source_key)
            imported.append(
                (
                    question_id,
                    question.strip(),
                    json.dumps([option.strip() for option in options], ensure_ascii=False),
                    answer,
                    int(active),
                    source_key,
                )
            )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("python.azkviz_admin_questions"))

    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing_rows = conn.execute(
            "SELECT id, question, source_key FROM az_questions"
        ).fetchall()
        existing_by_id = {row["id"]: row for row in existing_rows}
        existing_by_source = {
            row["source_key"]: row for row in existing_rows if row["source_key"]
        }
        added = 0
        updated = 0
        for question_id, question, options, answer, active, source_key in imported:
            existing = existing_by_source.get(source_key) if source_key else None
            if existing is None and source_key is None:
                legacy_id_match = existing_by_id.get(question_id)
                if legacy_id_match and legacy_id_match["question"] == question:
                    existing = legacy_id_match
                else:
                    existing = next(
                        (
                            row for row in existing_rows
                            if row["question"] == question
                        ),
                        None,
                    )
            if existing is not None:
                conn.execute(
                    """
                    UPDATE az_questions
                    SET question = ?, options = ?, answer = ?, active = ?
                    WHERE id = ?
                    """,
                    (question, options, answer, active, existing["id"]),
                )
                updated += 1
            else:
                if source_key is None and question_id not in existing_by_id:
                    conn.execute(
                        """
                        INSERT INTO az_questions (id, question, options, answer, active, source_key)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (question_id, question, options, answer, active, uuid4().hex),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO az_questions (question, options, answer, active, source_key)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (question, options, answer, active, source_key or uuid4().hex),
                    )
                added += 1
                inserted = conn.execute(
                    "SELECT id, question, source_key FROM az_questions WHERE id = last_insert_rowid()"
                ).fetchone()
                if inserted:
                    existing_rows.append(inserted)
                    existing_by_id[inserted["id"]] = inserted
                    existing_by_source[inserted["source_key"]] = inserted
        if conn.execute("SELECT COUNT(*) FROM az_questions WHERE active = 1").fetchone()[0] < 1:
            conn.rollback()
            flash("Po importu musí zůstat alespoň jedna aktivní otázka.", "error")
            return redirect(url_for("python.azkviz_admin_questions"))
        conn.commit()
        flash(
            f"Import otázek dokončen: {added} nových a {updated} aktualizovaných otázek."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("python.azkviz_admin_questions"))


@bp.route("/azkviz/match", methods=["POST"])
@login_required
def azkviz_match():
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]

    email = session["username"]
    name = (session.get("user") or {}).get("name") or email
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE az_games SET status = 'abandoned', updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('waiting', 'playing')
              AND updated_at < datetime('now', '-30 minutes')
            """
        )
        game = conn.execute(
            """
            SELECT * FROM az_games
            WHERE status IN ('waiting', 'playing')
              AND (player_a_email = ? OR player_b_email = ?)
            ORDER BY id DESC LIMIT 1
            """,
            (email, email),
        ).fetchone()

        if game is None:
            game = conn.execute(
                """
                SELECT * FROM az_games
                WHERE status = 'waiting' AND player_a_email <> ?
                ORDER BY created_at, id LIMIT 1
                """,
                (email,),
            ).fetchone()
            if game:
                question = _az_next_question(conn)
                conn.execute(
                    """
                    UPDATE az_games
                    SET player_b_email = ?, player_b_name = ?, status = 'playing',
                        turn_email = player_a_email, current_question = ?,
                        question_index = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'waiting'
                    """,
                    (email, name, json.dumps(question, ensure_ascii=False), None, game["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO az_games
                        (player_a_email, player_a_name, status, turn_email, board, question_index)
                    VALUES (?, ?, 'waiting', NULL, ?, NULL)
                    """,
                    (email, name, json.dumps([None] * (AZ_BOARD_SIZE * (AZ_BOARD_SIZE + 1) // 2))),
                )
        conn.commit()
        game_id = game["id"] if game else conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        return jsonify(_az_game_view(game, email))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@bp.route("/azkviz/game/<int:game_id>")
@login_required
def azkviz_game_state(game_id):
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]

    email = session["username"]
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        if not game:
            conn.rollback()
            return jsonify({"error": "Hra nebyla nalezena."}), 404
        if email not in (game["player_a_email"], game["player_b_email"]):
            conn.rollback()
            return jsonify({"error": "K této hře nemáte přístup."}), 403
        feedback = None
        if game["challenge_active"]:
            reactions = json.loads(game["challenge_reactions"] or "{}")
            challenge_ended = (
                time.time() * 1000
                >= game["challenge_started_at"]
                + game["challenge_target_ms"]
                + AZ_REACTION_WINDOW_MS
            )
            if challenge_ended:
                game, feedback = _az_finish_challenge(conn, game, reactions)
        conn.commit()
        response = _az_game_view(game, email)
        if feedback:
            response["feedback"] = feedback
        return jsonify(response)
    finally:
        conn.close()


@bp.route("/azkviz/game/<int:game_id>/challenge", methods=["POST"])
@login_required
def azkviz_start_challenge(game_id):
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json()
    cell = data.get("cell") if isinstance(data, dict) else None
    if type(cell) is not int:
        return jsonify({"error": "Vyber šedé pole."}), 400

    email = session["username"]
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        if not game:
            conn.rollback()
            return jsonify({"error": "Hra nebyla nalezena."}), 404
        if email not in (game["player_a_email"], game["player_b_email"]):
            conn.rollback()
            return jsonify({"error": "K této hře nemáte přístup."}), 403
        if game["status"] != "playing":
            conn.rollback()
            return jsonify({"error": "Hra právě neprobíhá."}), 409
        if game["challenge_active"]:
            conn.rollback()
            return jsonify({"error": "Souboj o šedé pole už probíhá."}), 409

        board = json.loads(game["board"])
        if not 0 <= cell < len(board) or board[cell] != "X":
            conn.rollback()
            return jsonify({"error": "Toto pole není šedé."}), 409

        challenge = _az_new_challenge()
        conn.execute(
            """
            UPDATE az_games
            SET challenge_cell = ?, challenge_started_at = ?,
                challenge_target_ms = ?, challenge_frames = ?,
                challenge_reactions = '{}', challenge_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                cell,
                challenge["started_at"],
                challenge["target_ms"],
                json.dumps(challenge["frames"], ensure_ascii=False),
                game_id,
            ),
        )
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        conn.commit()
        return jsonify(_az_game_view(game, email))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@bp.route("/azkviz/game/<int:game_id>/challenge/react", methods=["POST"])
@login_required
def azkviz_challenge_react(game_id):
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]

    email = session["username"]
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        if not game:
            conn.rollback()
            return jsonify({"error": "Hra nebyla nalezena."}), 404
        if email not in (game["player_a_email"], game["player_b_email"]):
            conn.rollback()
            return jsonify({"error": "K této hře nemáte přístup."}), 403
        if not game["challenge_active"]:
            conn.rollback()
            return jsonify({"error": "Souboj o šedé pole právě neprobíhá."}), 409

        now_ms = time.time() * 1000
        target_at = game["challenge_started_at"] + game["challenge_target_ms"]
        if now_ms >= target_at + AZ_REACTION_WINDOW_MS:
            reactions = json.loads(game["challenge_reactions"] or "{}")
            game, feedback = _az_finish_challenge(conn, game, reactions)
            conn.commit()
            return jsonify({
                "correct": False,
                "feedback": feedback,
                "game": _az_game_view(game, email),
            })

        if now_ms < target_at:
            winner_email = (
                game["player_b_email"]
                if email == game["player_a_email"]
                else game["player_a_email"]
            )
            conn.execute(
                """
                UPDATE az_games
                SET status = 'finished', winner_email = ?, turn_email = NULL,
                    challenge_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (winner_email, game_id),
            )
            game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
            conn.commit()
            return jsonify({
                "correct": False,
                "feedback": "Mezerník jsi stiskl/a dřív. Vyhrává soupeř.",
                "game": _az_game_view(game, email),
            })

        reactions = json.loads(game["challenge_reactions"] or "{}")
        if email in reactions:
            conn.rollback()
            return jsonify({"error": "Tvůj čas už je zaznamenaný."}), 409
        reactions[email] = now_ms - target_at
        if len(reactions) == 2:
            game, feedback = _az_finish_challenge(conn, game, reactions)
        else:
            conn.execute(
                "UPDATE az_games SET challenge_reactions = ? WHERE id = ?",
                (json.dumps(reactions), game_id),
            )
            game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
            feedback = "Čas zaznamenán. Čekáme na soupeřův stisk."
        conn.commit()
        return jsonify({
            "correct": True,
            "feedback": feedback,
            "game": _az_game_view(game, email),
        })
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@bp.route("/azkviz/game/<int:game_id>/cancel", methods=["POST"])
@login_required
def azkviz_cancel(game_id):
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]

    conn = get_db_connection()
    try:
        result = conn.execute(
            """
            UPDATE az_games SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND player_a_email = ? AND status = 'waiting'
            """,
            (game_id, session["username"]),
        )
        conn.commit()
    finally:
        conn.close()
    if result.rowcount != 1:
        return jsonify({"error": "Čekající hru už nelze zrušit."}), 409
    return jsonify({"status": "cancelled"})


@bp.route("/azkviz/game/<int:game_id>/answer", methods=["POST"])
@login_required
def azkviz_answer(game_id):
    denied = _az_player_required()
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json()
    if not isinstance(data, dict) or type(data.get("answer")) is not int:
        return jsonify({"error": "Odpověď musí být celé číslo."}), 400

    email = session["username"]
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        game = conn.execute("SELECT * FROM az_games WHERE id = ?", (game_id,)).fetchone()
        if not game:
            conn.rollback()
            return jsonify({"error": "Hra nebyla nalezena."}), 404
        if email not in (game["player_a_email"], game["player_b_email"]):
            conn.rollback()
            return jsonify({"error": "K této hře nemáte přístup."}), 403
        if game["status"] != "playing" or game["turn_email"] != email:
            conn.rollback()
            return jsonify({"error": "Teď nejste na tahu."}), 409
        if game["challenge_active"]:
            conn.rollback()
            return jsonify({"error": "Během souboje o šedé pole nelze odpovídat na otázku."}), 409

        question = (
            json.loads(game["current_question"])
            if game["current_question"]
            else AZ_QUESTIONS[game["question_index"]]
        )
        answer = data["answer"]
        if not 0 <= answer < len(question["options"]):
            conn.rollback()
            return jsonify({"error": "Vyberte platnou odpověď."}), 400

        board = json.loads(game["board"])
        correct = answer == question["answer"]
        cell = data.get("cell")
        if type(cell) is not int or not 0 <= cell < len(board):
            conn.rollback()
            return jsonify({"error": "Vyber pole na herní desce."}), 400
        if board[cell] == "X":
            conn.rollback()
            return jsonify({"error": "Šedé pole se získává soubojem na mezerník."}), 409
        if board[cell] is not None:
            conn.rollback()
            return jsonify({"error": "Toto pole už je obsazené."}), 409

        if correct:
            board[cell] = email
            won = _az_connected(board, email)
            if won:
                status, turn_email, winner_email = "finished", None, email
            elif all(board):
                status, turn_email, winner_email = "finished", None, None
            else:
                status = "playing"
                turn_email = game["player_b_email"] if email == game["player_a_email"] else game["player_a_email"]
                winner_email = None
            feedback = "Správně! Pole je vaše."
        else:
            board[cell] = "X"
            if all(board):
                status, turn_email, winner_email = "finished", None, None
            else:
                status = "playing"
                turn_email = game["player_b_email"] if email == game["player_a_email"] else game["player_a_email"]
                winner_email = None
            feedback = "Tentokrát ne. Správná odpověď: " + question["options"][question["answer"]]

        next_question = _az_next_question(conn, question) if status == "playing" else None
        conn.execute(
            """
            UPDATE az_games
            SET board = ?, status = ?, turn_email = ?, current_question = ?,
                question_index = NULL,
                winner_email = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                json.dumps(board, ensure_ascii=False), status, turn_email,
                json.dumps(next_question, ensure_ascii=False) if next_question else None,
                winner_email, game_id,
            ),
        )
        conn.commit()
        updated_game = conn.execute(
            "SELECT * FROM az_games WHERE id = ?", (game_id,)
        ).fetchone()
        return jsonify({
            "correct": correct,
            "feedback": feedback,
            "game": _az_game_view(updated_game, email),
        })
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@bp.route("/teacher")
@teacher_required
def teacher_dashboard():
    conn = get_db_connection()
    # Řadíme úlohy podle section_order (s využitím COALESCE), display_order a názvu
    assignments = conn.execute("SELECT * FROM assignments ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), title").fetchall()
    conn.close()
    grouped = group_assignments(assignments)
    return render_template("python/teacher_dashboard.html", grouped=grouped)


@bp.get("/teacher/content/export")
@teacher_required
def teacher_export_content():
    fields = (
        "id", "title", "description", "teacher_code", "section", "display_order",
        "section_order", "help_text", "test_input_run", "test_input_submit",
        "test_call_run", "test_call_submit", "precopy_lines", "active", "required",
    )
    conn = get_db_connection()
    try:
        items = []
        for row in conn.execute(
            "SELECT " + ", ".join(fields) + " FROM assignments ORDER BY id"
        ).fetchall():
            item = dict(row)
            item["active"] = bool(item["active"])
            item["required"] = bool(item["required"])
            items.append(item)
    finally:
        conn.close()
    payload = {
        "format": "zelva-content",
        "version": 1,
        "area": "python",
        "items": items,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(
        BytesIO(content),
        mimetype="application/json",
        as_attachment=True,
        download_name="python-uloha.json",
    )


@bp.post("/teacher/content/import")
@teacher_required
def teacher_import_content():
    fields = (
        "title", "description", "teacher_code", "section", "display_order",
        "section_order", "help_text", "test_input_run", "test_input_submit",
        "test_call_run", "test_call_submit", "precopy_lines", "active", "required",
    )
    optional_text_fields = (
        "description", "section", "help_text", "test_input_run", "test_input_submit",
        "test_call_run", "test_call_submit",
    )
    try:
        payload = read_content_upload(request.files.get("file"), "python")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > 5000:
            raise ValueError("Soubor může obsahovat nejvýše 5000 úloh.")
        imported = []
        imported_ids = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Soubor obsahuje neplatnou úlohu.")
            assignment_id = item.get("id")
            if type(assignment_id) is not int or assignment_id < 1 or assignment_id in imported_ids:
                raise ValueError("Úloha má neplatné nebo duplicitní ID.")
            title = item.get("title")
            teacher_code = item.get("teacher_code")
            if not isinstance(title, str) or not title.strip() or len(title.strip()) > 300:
                raise ValueError("Každá úloha musí mít platný název.")
            if not isinstance(teacher_code, str) or len(teacher_code) > 50000:
                raise ValueError("Každá úloha musí obsahovat platný učitelský kód.")
            if any(
                item.get(field) is not None and not isinstance(item.get(field), str)
                for field in optional_text_fields
            ):
                raise ValueError("Textová pole úlohy obsahují neplatnou hodnotu.")
            integer_fields = ("display_order", "section_order")
            if any(
                item.get(field) is not None
                and (type(item.get(field)) is not int or abs(item[field]) > 1000000)
                for field in integer_fields
            ):
                raise ValueError("Pořadí úloh musí být celé číslo.")
            precopy_lines = item.get("precopy_lines")
            if type(precopy_lines) is not int or not 1 <= precopy_lines <= 1000:
                raise ValueError("Počet předvyplněných řádků musí být od 1 do 1000.")
            if not isinstance(item.get("active"), bool) or not isinstance(item.get("required"), bool):
                raise ValueError("Stav aktivní/povinné úlohy není platný.")

            imported_ids.add(assignment_id)
            values = {
                field: item.get(field)
                for field in fields
                if field not in ("title", "teacher_code", "precopy_lines", "active", "required")
            }
            imported.append(
                (
                    assignment_id,
                    title.strip(),
                    teacher_code,
                    values["description"],
                    values["section"],
                    values["display_order"],
                    values["section_order"],
                    values["help_text"],
                    values["test_input_run"],
                    values["test_input_submit"],
                    values["test_call_run"],
                    values["test_call_submit"],
                    precopy_lines,
                    int(item["active"]),
                    int(item["required"]),
                )
            )
    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("python.teacher_dashboard"))

    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing_ids = {
            row["id"]
            for row in conn.execute("SELECT id FROM assignments").fetchall()
        }
        for values in imported:
            assignment_id = values[0]
            if assignment_id in existing_ids:
                conn.execute(
                    """
                    UPDATE assignments SET
                        title = ?, teacher_code = ?, description = ?, section = ?,
                        display_order = ?, section_order = ?, help_text = ?,
                        test_input_run = ?, test_input_submit = ?, test_call_run = ?,
                        test_call_submit = ?, precopy_lines = ?, active = ?, required = ?
                    WHERE id = ?
                    """,
                    values[1:] + (assignment_id,),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO assignments
                        (id, title, teacher_code, description, section, display_order,
                         section_order, help_text, test_input_run, test_input_submit,
                         test_call_run, test_call_submit, precopy_lines, active, required)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
        conn.commit()
        added = len(imported_ids - existing_ids)
        flash(
            f"Import Pythonu dokončen: {added} nových a "
            f"{len(imported) - added} aktualizovaných úloh.",
            "success",
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("python.teacher_dashboard"))


@bp.route("/teacher/set_active", methods=["POST"])
@teacher_required
def teacher_set_active():
    active_ids = {int(i) for i in request.form.getlist("active") if i.isdigit()}
    required_ids = {int(i) for i in request.form.getlist("required") if i.isdigit()}
    conn = get_db_connection()
    ids = [r["id"] for r in conn.execute("SELECT id FROM assignments").fetchall()]
    conn.executemany(
        "UPDATE assignments SET active = ?, required = ? WHERE id = ?",
        [(1 if i in active_ids else 0, 1 if i in required_ids else 0, i) for i in ids],
    )
    conn.commit()
    conn.close()
    flash("Aktivní a povinná cvičení byla uložena.")
    return redirect(url_for("python.teacher_dashboard"))


@bp.route("/teacher/wall", methods=["GET", "POST"])
@teacher_required
def teacher_wall():
    if request.method == "POST":
        cid = int(request.form["class_id"])
        # vymažeme staré záznamy
        with get_db_connection() as conn:
            conn.execute("DELETE FROM class_wall_sections WHERE class_id = ?", (cid,))
            # vložíme nové, v pořadí, jaké checkboxy vrátily
            for idx, sec in enumerate(request.form.getlist("sections")):
                conn.execute(
                    "INSERT INTO class_wall_sections(class_id, section, section_order) VALUES (?, ?, ?)",
                    (cid, sec, idx)
                )
            conn.commit()
        flash("Nástěnka byla uložena.", "success")
        return redirect(url_for("python.teacher_wall", class_id=cid))

    # GET: načteme všechna data
    with get_db_connection() as conn:
        classes = conn.execute("SELECT id, name FROM classes ORDER BY name").fetchall()
        sections = [r["section"] for r in conn.execute(
            "SELECT DISTINCT section FROM assignments ORDER BY section"
        ).fetchall()]
        selected = int(request.args.get("class_id", classes[0]["id"]))
        pins = conn.execute(
            "SELECT section FROM class_wall_sections WHERE class_id = ? ORDER BY section_order",
            (selected,)
        ).fetchall()
        pinned = [r["section"] for r in pins]

    return render_template(
        "python/teacher_wall.html",
        classes=classes,
        sections=sections,
        selected_class=selected,
        pinned=pinned
    )

@bp.route('/teacher/create', methods=['GET', 'POST'])
@teacher_required
def teacher_create():
    if request.method == 'POST':
        title           = request.form['title']
        description     = request.form['description']
        section         = request.form['section']
        display_order   = int(request.form.get('display_order', 0))
        help_text       = request.form.get('help_text', '')
        # pokud nebylo pole vůbec odesláno, vrátí se ''
        teacher_code    = request.form.get('teacher_code', '')
        precopy_lines   = int(request.form.get('precopy_lines', 1))
        test_call_run   = request.form.get('test_call_run', '')
        test_call_submit= request.form.get('test_call_submit', '')

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO assignments
              (title, description, section, display_order,
               help_text, teacher_code, precopy_lines,
               test_call_run, test_call_submit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title, description, section, display_order,
            help_text, teacher_code, precopy_lines,
            test_call_run, test_call_submit
        ))
        conn.commit()
        conn.close()
        flash('Cvičení bylo vytvořeno.', 'success')
        return redirect(url_for('python.teacher_dashboard'))

    # GET
    return render_template('python/teacher_create.html')

# File: app.py

@bp.route("/teacher/edit/<int:assignment_id>", methods=["GET", "POST"])
@teacher_required
def teacher_edit(assignment_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not row:
        conn.close()
        flash("Cvičení nenalezeno.", "danger")
        return redirect(url_for("python.teacher_dashboard"))
    assignment = dict(row)

    if request.method == "POST":
        title            = request.form["title"]
        description      = request.form["description"]
        teacher_code     = request.form.get("teacher_code", "")
        section          = request.form.get("section", "")
        display_order    = int(request.form.get("display_order", 0))
        # zachovej původní section_order, pokud není v POSTu
        section_order    = int(request.form.get(
                              "section_order",
                              assignment.get("section_order", 0)
                          ))
        help_text        = request.form.get("help_text", "")
        precopy_lines    = int(request.form.get("precopy_lines", 1))
        test_call_run    = request.form.get("test_call_run", "")
        test_call_submit = request.form.get("test_call_submit", "")

        conn.execute("""
            UPDATE assignments
            SET title             = ?,
                description       = ?,
                teacher_code      = ?,
                section           = ?,
                display_order     = ?,
                section_order     = ?,
                help_text         = ?,
                precopy_lines     = ?,
                test_call_run     = ?,
                test_call_submit  = ?
            WHERE id = ?
        """, (
            title, description, teacher_code,
            section, display_order, section_order,
            help_text, precopy_lines,
            test_call_run, test_call_submit,
            assignment_id
        ))
        conn.commit()
        conn.close()
        flash("Cvičení upraveno.", "success")
        return redirect(url_for("python.teacher_dashboard"))

    conn.close()
    return render_template("python/teacher_edit.html", assignment=assignment)

@bp.route("/teacher/delete/<int:assignment_id>", methods=["POST"])
@teacher_required
def teacher_delete(assignment_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    conn.commit()
    conn.close()
    flash("Úkol byl smazán.")
    return redirect(url_for("python.teacher_dashboard"))


# -------------------------------------------------------
# Nová routa: Přiřazení úkolů třídám s deadliny (pro učitele)
# -------------------------------------------------------
@bp.route("/teacher/assign_tasks", methods=["GET", "POST"])
@teacher_required
def teacher_assign_tasks():
    conn = get_db_connection()
    # Načteme všechny úlohy a třídy pro výběr
    assignments = conn.execute(
    "SELECT id, title, section FROM assignments ORDER BY COALESCE(section_order,0), COALESCE(display_order,0), title"
    ).fetchall()
    secs = conn.execute("SELECT DISTINCT section FROM assignments ORDER BY section").fetchall()
    sections = [row['section'] for row in secs]
    classes = conn.execute("SELECT id, name FROM classes ORDER BY name").fetchall()
    if request.method == "POST":
        selected_assignment_ids = request.form.getlist("assignment_ids")
        selected_class_ids = request.form.getlist("class_ids")
        raw = request.form.get("deadline")  # např. "2025-07-25T15:00"
        local = datetime.fromisoformat(raw)
        tz = pytz.timezone("Europe/Prague")
        local = tz.localize(local)
        utc = local.astimezone(pytz.utc)
        deadline = utc.strftime("%Y-%m-%d %H:%M:%S")
        for aid in selected_assignment_ids:
            for cid in selected_class_ids:
                conn.execute(
                    "INSERT INTO class_assignments (assignment_id, class_id, deadline) VALUES (?, ?, ?)",
                    (aid, cid, deadline)
                )
        conn.commit()
        conn.close()
        flash("Úkoly byly přiřazeny třídám.")
        return redirect(url_for("python.teacher_dashboard"))
    conn.close()
    return render_template(
    "python/teacher_assign.html",
    assignments=assignments,
    classes=classes,
    sections=sections
)
# File: app.py

@bp.route("/teacher/assigned")
@teacher_required
def teacher_assigned():
    """Zobrazí seznam všech cvičení přiřazených třídám (id, název, třída, deadline)."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT
          ca.id           AS id,
          ca.assignment_id,
          ca.class_id,
          a.title         AS exercise,
          c.name          AS class_name,
          ca.deadline
        FROM class_assignments ca
        JOIN assignments a ON ca.assignment_id = a.id
        JOIN classes c     ON ca.class_id      = c.id
        ORDER BY ca.deadline DESC
    """).fetchall()
    conn.close()
    return render_template("python/teacher_assigned.html", rows=rows)

@bp.route("/teacher/assigned/<int:ca_id>/edit", methods=["GET", "POST"])
@teacher_required
def teacher_assigned_edit(ca_id):
    conn = get_db_connection()
    # načtu záznam přiřazení
    ca = conn.execute("""
        SELECT ca.id, ca.deadline, a.title AS exercise, c.name AS class_name
          FROM class_assignments ca
          JOIN assignments a ON ca.assignment_id = a.id
          JOIN classes c     ON ca.class_id = c.id
         WHERE ca.id = ?
    """, (ca_id,)).fetchone()
    if not ca:
        conn.close()
        flash("Přiřazení nenalezeno.")
        return redirect(url_for("python.teacher_assigned"))

    if request.method == "POST":
        new_deadline = request.form["deadline"]
        conn.execute(
            "UPDATE class_assignments SET deadline = ? WHERE id = ?",
            (new_deadline, ca_id)
        )
        conn.commit()
        conn.close()
        flash("Deadline byl upraven.")
        return redirect(url_for("python.teacher_assigned"))

    conn.close()
    return render_template("python/teacher_assigned_edit.html", ca=ca)

@bp.route("/teacher/unassign/<int:ca_id>", methods=["POST"])
@teacher_required
def teacher_unassign(ca_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM class_assignments WHERE id = ?", (ca_id,))
    conn.commit()
    conn.close()
    flash("Přiřazení bylo odstraněno.")
    return redirect(url_for("python.teacher_assigned"))

@bp.route("/teacher/assignment_status/<int:assignment_id>/<int:class_id>")
@teacher_required
def teacher_assignment_status(assignment_id, class_id):
    conn = get_db_connection()
    # Zjistíme název cvičení, název třídy a deadline
    meta = conn.execute("""
        SELECT a.title    AS exercise,
               ca.deadline AS deadline,
               c.name     AS class_name
        FROM class_assignments ca
        JOIN assignments a ON ca.assignment_id = a.id
        JOIN classes c     ON ca.class_id      = c.id
        WHERE ca.assignment_id = ? AND ca.class_id = ?
    """, (assignment_id, class_id)).fetchone()

    # Získáme pro všechny studenty třídy datum prvního úspěšného odevzdání (pokud existuje)
    rows = conn.execute("""
        SELECT st.name,
               st.email,
               sub.submission_time
        FROM students st
        LEFT JOIN (
          SELECT student_email,
                 MIN(submission_time) AS submission_time
          FROM submissions
          WHERE assignment_id = ?
            AND result LIKE '%Test prošel!%'
          GROUP BY student_email
        ) sub
          ON st.email = sub.student_email
        WHERE st.class_id = ?
        ORDER BY st.name
    """, (assignment_id, class_id)).fetchall()
    conn.close()

    return render_template("python/teacher_assignment_status.html",
                           meta=meta,
                           rows=rows)


@bp.route("/teacher/assigned_grouped")
@teacher_required
def teacher_assigned_grouped():
    tz = pytz.timezone("Europe/Prague")
    now_local = datetime.now(tz)
    conn = get_db_connection()

    groups = conn.execute("""
        SELECT DISTINCT class_id, deadline
          FROM class_assignments
         ORDER BY deadline DESC
    """).fetchall()

    data = []
    for g in groups:
        class_id      = g["class_id"]
        deadline_iso  = g["deadline"]  # uložený UTC string

        # 1) Parsujeme jako UTC a převedeme do lokální zóny
        dt_deadline_utc = datetime.fromisoformat(deadline_iso).replace(tzinfo=pytz.utc)
        dt_deadline     = dt_deadline_utc.astimezone(tz)
        overdue         = now_local > dt_deadline

        # 2) Načteme přiřazené assignmenty
        asgs = conn.execute("""
            SELECT assignment_id
              FROM class_assignments
             WHERE class_id = ? AND deadline = ?
        """, (class_id, deadline_iso)).fetchall()
        assignment_ids = [r["assignment_id"] for r in asgs]
        total          = len(assignment_ids)

        cls = conn.execute("SELECT name FROM classes WHERE id = ?", (class_id,)).fetchone()
        class_name = cls["name"] if cls else "–"

        students = conn.execute("""
            SELECT name, email
              FROM students
             WHERE class_id = ?
             ORDER BY name
        """, (class_id,)).fetchall()

        students_data = []
        for st in students:
            email = st["email"]

            # a) počet úspěšných
            cnt = 0
            if total:
                ph = ",".join("?" for _ in assignment_ids)
                cnt = conn.execute(f"""
                    SELECT COUNT(DISTINCT assignment_id) AS cnt
                      FROM submissions
                     WHERE student_email = ?
                       AND assignment_id IN ({ph})
                       AND result LIKE '%Test prošel!%'
                """, [email] + assignment_ids).fetchone()["cnt"] or 0

            # b) čas prvního úspěchu (UTC→lokálně)
            comp_dt = None
            if total:
                ph = ",".join("?" for _ in assignment_ids)
                comp_iso = conn.execute(f"""
                    SELECT MIN(submission_time) AS comp
                      FROM submissions
                     WHERE student_email = ?
                       AND assignment_id IN ({ph})
                       AND result LIKE '%Test prošel!%'
                """, [email] + assignment_ids).fetchone()["comp"]
                if comp_iso:
                    comp_dt = datetime.fromisoformat(comp_iso).replace(tzinfo=pytz.utc).astimezone(tz)

            passed = (cnt == total and total > 0)
            late   = passed and comp_dt and comp_dt > dt_deadline

            # c) počet úloh dokončených v termínu
            on_time_count = 0
            if total:
                ph = ",".join("?" for _ in assignment_ids)
                subquery = f"""
                    SELECT COUNT(*) AS cnt FROM (
                        SELECT assignment_id,
                               MIN(datetime(submission_time, 'utc','localtime')) AS first_success
                          FROM submissions
                         WHERE student_email = ?
                           AND assignment_id IN ({ph})
                           AND result LIKE '%Test prošel!%'
                         GROUP BY assignment_id
                        HAVING first_success <= ?
                    )
                """
                deadline_str = dt_deadline.strftime("%Y-%m-%d %H:%M:%S")
                params = [email] + assignment_ids + [deadline_str]
                on_time_count = conn.execute(subquery, params).fetchone()["cnt"] or 0

            students_data.append({
                "name":            st["name"],
                "email":           email,
                "passed":          cnt,
                "on_time":         passed and comp_dt and comp_dt <= dt_deadline,
                "on_time_count":   on_time_count,
                "completion_time": comp_dt,
                "late":            late
            })

        data.append({
            "class_id":   class_id,
            "class_name": class_name,
            "deadline":   dt_deadline,
            "overdue":    overdue,
            "total":      total,
            "students":   students_data
        })

    conn.close()
    return render_template("python/teacher_assigned_grouped.html", data=data)

@bp.route("/student/assignment/<int:assignment_id>", methods=["GET", "POST"])
@login_required
def student_assignment(assignment_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not row:
        conn.close()
        return "Úkol nenalezen.", 404
    if not row["active"] and session.get("role") != "teacher":
        conn.close()
        return "Úkol není pro studenty aktivní.", 404
    assignment = dict(row)

    teacher_code      = assignment.get("teacher_code", "")
    precopy           = assignment.get("precopy_lines", 1)
    lines             = teacher_code.splitlines()
    initial           = lines[:precopy]
    default_code      = "\n".join(initial) + "\n    pass\n" if initial else ""

    if request.method == "GET":
        latest_submission = conn.execute(
            "SELECT student_code FROM submissions "
            "WHERE assignment_id = ? AND student_email = ? "
            "ORDER BY submission_time DESC, id DESC LIMIT 1",
            (assignment_id, session["username"]),
        ).fetchone()
        if latest_submission is None:
            student_code = default_code
        else:
            student_code = latest_submission["student_code"] or ""
    else:
        student_code = request.form.get("student_code", "").expandtabs(4)

    # příprava
    match            = re.search(r"def\s+(\w+)\s*\(", teacher_code)
    function_name    = match.group(1) if match else "funkce"
    test_call_run    = assignment.get("test_call_run") or ""
    test_call_submit = assignment.get("test_call_submit") or ""
    help_key         = f"help_viewed_{assignment_id}"
    help_shown       = session.get(help_key, False)

    result = None
    teacher_output = None
    student_output = None
    used_test_call = ""
    submit_clicked = False

    if request.method == "POST":
        action = request.form.get("action")

        # --- HELP ---
        if action == "help":
            session[help_key] = True
            flash("Nápověda byla zobrazena. Při odevzdání se zaznamená její použití.", "info")
            conn.close()
            return redirect(url_for("python.student_assignment", assignment_id=assignment_id))

        # --- RUN (nezapisovat cokoliv do DB) ---
        if action == "run":
            call = test_call_run.strip()
            snippet = "\n" + call
            teacher_output = run_python_code(teacher_code + snippet)
            student_output = run_python_code(student_code   + snippet)
            result = (
                f"Výstup při spuštění:<br>"
                f"<pre>{student_output}</pre><br>"
                f"Použito volání:<br><pre>{call}</pre>"
            )

        # --- SUBMIT (uložit) ---
        elif action == "submit":
            submit_clicked = True
            # pokud student kód nezměnil
            if student_code.strip() == default_code.strip():
                result = "Úkol nezkoušen"
                conn.execute(
                    "INSERT INTO submissions "
                    "(assignment_id, student_email, student_code, result, teacher_output, student_output, help_used) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (assignment_id, session["username"], student_code, result, "", "", 0)
                )
                conn.commit()
            else:
                # 1) načteme všechna testovací volání
                calls = [c.strip() for c in test_call_submit.split(";") if c.strip()]
                test_results = []
                for call in calls:
                    snippet = "\n" + call
                    t_out = run_python_code(teacher_code + snippet)
                    s_out = run_python_code(student_code   + snippet)
                    passed = (t_out == s_out)
                    test_results.append({
                        "call": call,
                        "teacher_output": t_out,
                        "student_output": s_out,
                        "passed": passed
                    })

                # 2) vyhodnocení
                failed = [r for r in test_results if not r["passed"]]
                if not failed:
                    # vše projde -> úspěch, vybereme náhodně jedno volání k zobrazení
                    chosen = random.choice(test_results)
                    used_test_call = chosen["call"]
                    teacher_output = chosen["teacher_output"]
                    student_output = chosen["student_output"]
                    result = "Test prošel!"
                else:
                    # alespoň jedno neprošlo -> selhání, vybereme náhodně z neúspěšných
                    chosen = random.choice(failed)
                    used_test_call = chosen["call"]
                    teacher_output = chosen["teacher_output"]
                    student_output = chosen["student_output"]
                    result = (
                        "Test selhal.<br>"
                        f"Testovací volání: <pre>{used_test_call}</pre><br>"
                        f"Výstup učitele: <pre>{teacher_output}</pre><br>"
                        f"Výstup studenta: <pre>{student_output}</pre>"
                    )

                help_used = 1 if help_shown else 0
                # 3) uložení záznamu
                conn.execute(
                    "INSERT INTO submissions "
                    "(assignment_id, student_email, student_code, result, teacher_output, student_output, help_used) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (assignment_id, session["username"], student_code,
                     result, teacher_output, student_output, help_used)
                )
                conn.commit()

    # --- hledání dalšího úkolu ve stejné sekci ---
    next_assignment_id = None
    all_in_sec = conn.execute(
        "SELECT id FROM assignments WHERE section = ? "
        "ORDER BY COALESCE(section_order,0), COALESCE(display_order,0), title",
        (assignment["section"],)
    ).fetchall()
    ids = [r["id"] for r in all_in_sec]
    if assignment_id in ids:
        idx = ids.index(assignment_id)
        for nid in ids[idx+1:]:
            subs = conn.execute(
                "SELECT result FROM submissions WHERE assignment_id = ? AND student_email = ?",
                (nid, session["username"])
            ).fetchall()
            if not any("Test prošel!" in s["result"] for s in subs):
                next_assignment_id = nid
                break

    conn.close()
    return render_template(
        "python/student_assignment.html",
        assignment=assignment,
        student_code=student_code,
        student_output=student_output,
        teacher_output=teacher_output,
        result=result,
        help_shown=help_shown,
        used_test_call=used_test_call,
        test_call_run=test_call_run,
        test_call_submit=test_call_submit,
        next_assignment_id=next_assignment_id,
        submit_clicked=submit_clicked
    )

@bp.route("/teacher/manage_students", methods=["GET", "POST"])
@teacher_required
def teacher_manage_students():
    conn = get_db_connection()
    if request.method == "POST":
        student_email = request.form["student_email"]
        class_id = request.form.get("class_id")
        conn.execute("UPDATE students SET class_id = ? WHERE email = ?", (class_id, student_email))
        conn.commit()
        flash("Student byl přiřazen do třídy.")
    students = conn.execute("SELECT * FROM students").fetchall()
    classes = conn.execute("SELECT * FROM classes").fetchall()
    conn.close()
    return render_template("python/teacher_manage_students.html", students=students, classes=classes)

@bp.route("/teacher/create_class", methods=["GET", "POST"])
@teacher_required
def teacher_create_class():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        conn = get_db_connection()
        conn.execute("INSERT INTO classes (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
        conn.close()
        flash("Třída vytvořena.")
        return redirect(url_for("python.teacher_manage_students"))
    return render_template("python/teacher_create_class.html")

@bp.route("/teacher/student/<int:student_id>")
@teacher_required
def teacher_student_details(student_id):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        flash("Student nenalezen.")
        return redirect(url_for("python.teacher_manage_students"))
    submissions = conn.execute("""
        SELECT s.*, a.title as assignment_title
        FROM submissions s 
        JOIN assignments a ON s.assignment_id = a.id 
        WHERE s.student_email = ? AND s.result LIKE '%Test prošel!%'
        ORDER BY s.submission_time DESC
    """, (student["email"],)).fetchall()
    conn.close()
    return render_template("python/teacher_student_details.html", student=student, submissions=submissions)

@bp.route("/teacher/statistics", methods=["GET"])
@teacher_required
def teacher_statistics():
    conn = get_db_connection()
    
    # Získání filtrů z GET parametrů jako seznamů
    selected_class_ids       = request.args.getlist("class_id")
    selected_student_emails  = request.args.getlist("student_email")
    selected_sections        = request.args.getlist("section")
    selected_assignment_ids  = request.args.getlist("assignment_id")
    
    # Sestavení dotazu na assignments – filtrujeme podle id a sekcí
    assignment_query = "SELECT * FROM assignments"
    assignment_conditions = []
    assignment_params = []
    if selected_assignment_ids:
        placeholders = ",".join("?" for _ in selected_assignment_ids)
        assignment_conditions.append("id IN (" + placeholders + ")")
        assignment_params.extend(selected_assignment_ids)
    if selected_sections:
        placeholders = ",".join("?" for _ in selected_sections)
        assignment_conditions.append("section IN (" + placeholders + ")")
        assignment_params.extend(selected_sections)
    if assignment_conditions:
        assignment_query += " WHERE " + " AND ".join(assignment_conditions)
    assignment_query += " ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), section, title"
    assignments = conn.execute(assignment_query, tuple(assignment_params)).fetchall()
    
    # Jen studenti, kteří skutečně něco odevzdali
    all_students = [
        {"email": r["email"], "name": r["name"] or r["email"], "class_id": r["class_id"]}
        for r in conn.execute(
            "SELECT sub.email AS email, st.name AS name, st.class_id AS class_id FROM "
            "(SELECT DISTINCT student_email AS email FROM submissions) sub "
            "LEFT JOIN students st ON st.email = sub.email ORDER BY sub.email"
        ).fetchall()
    ]
    if selected_class_ids:
        all_students = [s for s in all_students if str(s["class_id"]) in selected_class_ids]
    students = all_students
    if selected_student_emails:
        students = [s for s in students if s["email"] in selected_student_emails]
    
    # Sestavení statistik pro každé assignment a studenta
    stats = {}
    for assignment in assignments:
        a_id = assignment["id"]
        stats[a_id] = {}
        for student in students:
            s_email = student["email"]
            subs = conn.execute(
                "SELECT * FROM submissions WHERE assignment_id = ? AND student_email = ?",
                (a_id, s_email)
            ).fetchall()
            if subs:
                failures = sum(1 for sub in subs if "Test prošel!" not in sub["result"])
                success_no_help = 1 if any("Test prošel!" in sub["result"] and sub["help_used"] == 0 for sub in subs) else 0
                success_with_help = 0
                if not success_no_help and any("Test prošel!" in sub["result"] and sub["help_used"] == 1 for sub in subs):
                    success_with_help = 1
                if success_no_help:
                    cell_color = "green"
                elif success_with_help:
                    cell_color = "blue"
                else:
                    cell_color = "red"
            else:
                failures = success_no_help = success_with_help = 0
                cell_color = "gray"
            stats[a_id][s_email] = {
                "color": cell_color,
                "success_no_help": success_no_help,
                "success_with_help": success_with_help,
                "failures": failures
            }
    
    # Agregované statistiky + průměrný čas řešení (pojednání jen odevzdaných)
    assignment_stats = {}
    for assignment in assignments:
        a_id = assignment["id"]
        total_success_no_help   = sum(stats[a_id][s["email"]]["success_no_help"]   for s in students)
        total_success_with_help = sum(stats[a_id][s["email"]]["success_with_help"] for s in students)
        total_failures          = sum(stats[a_id][s["email"]]["failures"]          for s in students)
        total_success = total_success_no_help + total_success_with_help
        total_attempts = total_success + total_failures
        ratio = f"{(total_success/total_attempts*100):.0f}%" if total_attempts > 0 else "N/A"
        
        # průměrný čas řešení – bereme pro každého studenta jeho poslední submit
        avg_row = conn.execute("""
            SELECT AVG(latest) AS avg_time FROM (
              SELECT MAX(time_taken) AS latest
              FROM submissions
              WHERE assignment_id = ?
                AND (result LIKE 'Test prošel!%' OR result LIKE 'Test selhal.%')
              GROUP BY student_email
            )
        """, (a_id,)).fetchone()
        avg_time = int(avg_row["avg_time"]) if avg_row and avg_row["avg_time"] is not None else 0

        assignment_stats[a_id] = {
            "success_no_help": total_success_no_help,
            "success_with_help": total_success_with_help,
            "failures": total_failures,
            "ratio": ratio,
            "avg_time": avg_time
        }
    
    # Pro dropdowny
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    if selected_sections:
        placeholders = ",".join("?" for _ in selected_sections)
        assignments_filter = conn.execute(
            "SELECT id, title, section FROM assignments "
            "WHERE section IN (" + placeholders + ") "
            "ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), section, title",
            tuple(selected_sections)
        ).fetchall()
    else:
        assignments_filter = conn.execute(
            "SELECT id, title, section FROM assignments "
            "ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), section, title"
        ).fetchall()
    sections_all = conn.execute(
        "SELECT DISTINCT section FROM assignments "
        "WHERE section IS NOT NULL AND section <> '' ORDER BY section"
    ).fetchall()
    
    # Celkové metriky
    global_success  = sum(v["success_no_help"] + v["success_with_help"] for v in assignment_stats.values())
    global_failures = sum(v["failures"] for v in assignment_stats.values())
    total_attempts  = global_success + global_failures
    global_ratio    = f"{(global_success/total_attempts*100):.0f}%" if total_attempts > 0 else "N/A"
    
    # NOVINKA: globální průměrný čas pro všechny aktuálně vyfiltrované úlohy
    filtered_ids = [a["id"] for a in assignments]
    if filtered_ids:
        ph = ",".join("?" for _ in filtered_ids)
        row = conn.execute(
            f"SELECT AVG(time_taken) AS avg_time FROM submissions "
            f"WHERE assignment_id IN ({ph}) "
            f"  AND (result LIKE 'Test prošel!%' OR result LIKE 'Test selhal.%')",
            tuple(filtered_ids)
        ).fetchone()
        global_avg_time = int(row["avg_time"]) if row and row["avg_time"] is not None else 0
    else:
        global_avg_time = 0

    conn.close()
    return render_template("python/teacher_statistics.html",
        assignments=assignments,
        students=students,
        all_students=all_students,
        stats=stats,
        assignment_stats=assignment_stats,
        classes=classes,
        all_assignments=assignments_filter,
        sections_all=sections_all,
        selected_class_ids=selected_class_ids,
        selected_student_emails=selected_student_emails,
        selected_sections=selected_sections,
        selected_assignment_ids=selected_assignment_ids,
        global_success=global_success,
        global_failures=global_failures,
        global_ratio=global_ratio,
        global_avg_time=global_avg_time
    )

@bp.route("/teacher/submissions")
@teacher_required
def teacher_submissions():
    conn = get_db_connection()
    # Získání filtrů jako seznamů
    selected_class_ids = request.args.getlist("class_id")
    selected_student_emails = request.args.getlist("student_email")
    selected_sections = request.args.getlist("section")
    selected_assignment_ids = request.args.getlist("assignment_id")
    last_only = request.args.get("last_only") == "1"
    
    # Sestavení dotazu na odevzdání
    query = (
        "SELECT s.*, a.title as assignment_title, a.section as assignment_section "
        "FROM submissions s JOIN assignments a ON s.assignment_id = a.id"
    )
    conditions = []
    params = []
    if selected_class_ids:
        query += " JOIN students st ON s.student_email = st.email"
        placeholders = ",".join("?" for _ in selected_class_ids)
        conditions.append(f"st.class_id IN ({placeholders})")
        params.extend(selected_class_ids)
    if selected_student_emails:
        placeholders = ",".join("?" for _ in selected_student_emails)
        conditions.append(f"s.student_email IN ({placeholders})")
        params.extend(selected_student_emails)
    if selected_sections:
        placeholders = ",".join("?" for _ in selected_sections)
        conditions.append(f"a.section IN ({placeholders})")
        params.extend(selected_sections)
    if selected_assignment_ids:
        placeholders = ",".join("?" for _ in selected_assignment_ids)
        conditions.append(f"s.assignment_id IN ({placeholders})")
        params.extend(selected_assignment_ids)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY s.submission_time DESC, s.id DESC"
    submissions = conn.execute(query, tuple(params)).fetchall()
    if last_only:
        seen = set()
        latest = []
        for sub in submissions:
            key = (sub["student_email"], sub["assignment_id"])
            if key not in seen:
                seen.add(key)
                latest.append(sub)
        submissions = latest
    
    # Pro nabídku filtrů načteme všechna data z tabulek
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    # Jen studenti, kteří skutečně něco odevzdali
    all_students = conn.execute(
        "SELECT sub.email AS email, st.name AS name, st.class_id AS class_id FROM "
        "(SELECT DISTINCT student_email AS email FROM submissions) sub "
        "LEFT JOIN students st ON st.email = sub.email ORDER BY sub.email"
    ).fetchall()
    # Pokud byl vybrán filtr pro třídu, omezíme nabídku studentů
    if selected_class_ids:
        all_students = [s for s in all_students if str(s["class_id"]) in selected_class_ids]
    # Všechny sekce a úkoly
    sections_all = conn.execute("SELECT DISTINCT section FROM assignments ORDER BY section").fetchall()
    all_assignments = conn.execute(
        "SELECT id, title, section FROM assignments ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), section, title"
    ).fetchall()
    # Pokud byl vybrán filtr pro sekci, omezíme nabídku úkolů
    if selected_sections:
        all_assignments = [a for a in all_assignments if a["section"] in selected_sections]
    conn.close()
    return render_template("python/teacher_submissions.html",
                           submissions=submissions,
                           classes=classes,
                           all_students=all_students,
                           sections=sections_all,
                           all_assignments=all_assignments,
                           selected_class_ids=selected_class_ids,
                           selected_student_emails=selected_student_emails,
                           selected_sections=selected_sections,
                           selected_assignment_ids=selected_assignment_ids,
                           last_only=last_only)

# ROUTA PRO ŘAZENÍ SEKCIÍ
@bp.route("/teacher/order_sections", methods=["GET", "POST"])
@teacher_required
def teacher_order_sections():
    conn = get_db_connection()
    if request.method == "POST":
        # Načteme unikátní sekce z assignments (bez prázdných)
        sections = conn.execute(
            "SELECT section FROM assignments WHERE section <> '' GROUP BY section"
        ).fetchall()
        for row in sections:
            section = row["section"]
            new_order = request.form.get(f"order_{section}")
            if new_order is not None:
                try:
                    new_order_int = int(new_order)
                    # Aktualizace všech assignments, které mají tuto sekci
                    conn.execute(
                        "UPDATE assignments SET section_order = ? WHERE section = ?",
                        (new_order_int, section)
                    )
                except ValueError:
                    pass
        conn.commit()
        flash("Pořadí sekcí bylo uloženo.")
        conn.close()
        return redirect(url_for("python.teacher_order_sections"))
    else:
        # Načteme unikátní sekce z assignments s jejich uloženým pořadím.
        # Pokud section_order je NULL, použijeme 0.
        sections = conn.execute(
            "SELECT section, MIN(COALESCE(section_order, 0)) AS section_order FROM assignments WHERE section <> '' GROUP BY section ORDER BY section_order ASC"
        ).fetchall()
        conn.close()
        return render_template("python/teacher_order_sections.html", sections=sections)
      



@bp.route("/student")
@login_required
def student_dashboard():
    conn = get_db_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE email = ?", (session["username"],)
    ).fetchone()

    now = datetime.now()
    assigned = []
    if student and student["class_id"]:
        rows = conn.execute("""
            SELECT
              ca.id         AS ca_id,
              a.id          AS assignment_id,
              a.title       AS title,
              a.section     AS section,
              ca.deadline   AS deadline
            FROM class_assignments ca
            JOIN assignments a ON ca.assignment_id = a.id
            WHERE ca.class_id = ? AND a.active = 1
            ORDER BY ca.deadline
        """, (student["class_id"],)).fetchall()
        for r in rows:
            dt = datetime.fromisoformat(r["deadline"])
            assigned.append({
                "ca_id":        r["ca_id"],
                "assignment_id":r["assignment_id"],
                "title":        r["title"],
                "section":      r["section"],
                "deadline":     r["deadline"],
                "overdue":      now > dt
            })

    # fetch pinned sections for nástěnka
    pinned = []
    if student and student["class_id"]:
        pins = conn.execute(
            "SELECT section FROM class_wall_sections WHERE class_id = ? ORDER BY section_order",
            (student["class_id"],)
        ).fetchall()
        pinned = [r["section"] for r in pins]

    student_submissions = conn.execute(
        "SELECT * FROM submissions WHERE student_email = ? ORDER BY submission_time DESC",
        (session["username"],)
    ).fetchall()
    assignments = conn.execute(
        "SELECT * FROM assignments WHERE active = 1 "
        "ORDER BY COALESCE(section_order,0), COALESCE(display_order,0), title"
    ).fetchall()
    conn.close()

    grouped = group_assignments(assignments)
    ordered_sections = sorted(
        grouped.keys(),
        key=lambda s: min((a["section_order"] or 0) for a in grouped[s])
    )
    class_set = bool(student and student["class_id"])

    return render_template(
        "python/student_dashboard.html",
        assigned=assigned,
        pinned=pinned,
        student_submissions=student_submissions,
        grouped=grouped,
        ordered_sections=ordered_sections,
        class_set=class_set,
        now=now
    )

# ROUTA PRO STUDENTOVÁ ODEVZDÁNÍ (pro daný úkol)
@bp.route("/student/submissions/<int:assignment_id>")
@login_required
def student_submissions(assignment_id):
    conn = get_db_connection()
    # Načteme úkol, abychom získali jeho název
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not assignment:
        conn.close()
        return "Úkol nenalezen.", 404
    assignment_title = assignment["title"]
    # Načteme všechna odevzdání studenta pro daný úkol, řazená podle času (nejnovější nahoře)
    submissions = conn.execute(
        "SELECT * FROM submissions WHERE assignment_id = ? AND student_email = ? ORDER BY submission_time DESC",
        (assignment_id, session["username"])
    ).fetchall()
    conn.close()
    return render_template("python/student_submissions.html", 
                           submissions=submissions, 
                           assignment_id=assignment_id, 
                           assignment_title=assignment_title)

@bp.route("/teacher/submission_cell")
@teacher_required
def teacher_submission_cell():
    assignment_id = request.args.get("assignment_id")
    student_email = request.args.get("student_email")
    conn = get_db_connection()
    submissions = conn.execute(
        "SELECT * FROM submissions WHERE assignment_id = ? AND student_email = ? ORDER BY submission_time DESC",
        (assignment_id, student_email)
    ).fetchall()
    conn.close()
    return render_template("python/teacher_submission_cell.html",
                           submissions=submissions,
                           assignment_id=assignment_id,
                           student_email=student_email)

@bp.route("/manage_classes", methods=["GET", "POST"])
@teacher_required
def manage_classes():
    conn = get_db_connection()
    if request.method == "POST":
        # Odebrání třídy – očekáváme, že formulář posílá id třídy
        class_id = request.form.get("class_id")
        if class_id:
            # U studentů v dané třídě nastavíme class_id = NULL
            conn.execute("UPDATE students SET class_id = NULL WHERE class_id = ?", (class_id,))
            # Odstraníme třídu
            conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
            conn.commit()
            flash("Třída byla odstraněna a žáci již nemají přiřazenou třídu.")
            return redirect(url_for("python.manage_classes"))
    # Dotaz na seznam tříd s počtem žáků
    classes = conn.execute("""
        SELECT c.id, c.name, c.description, COUNT(s.id) as student_count
        FROM classes c LEFT JOIN students s ON c.id = s.class_id
        GROUP BY c.id, c.name, c.description
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return render_template("python/manage_classes.html", classes=classes)

# -----------------------------
# Změna třídy – stránka pro studenty
# -----------------------------
@bp.route("/change_class", methods=["GET", "POST"])
@login_required
def change_class():
    # Tato stránka je určena pouze pro studenty
    if session.get("role") != "student":
        flash("Tuto akci mohou provádět pouze studenti.")
        return redirect(url_for("python.student_dashboard"))
    
    conn = get_db_connection()
    # Zjistíme aktuálního studenta
    student = conn.execute("SELECT * FROM students WHERE email = ?", (session["username"],)).fetchone()
    
    # Pokud student již má nastavenou třídu, nebude moci měnit svůj výběr
    if student["class_id"] is not None:
        flash("Třída již byla nastavena a nelze ji změnit.")
        conn.close()
        return redirect(url_for("python.student_dashboard"))
    
    # Načteme seznam tříd
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    
    if request.method == "POST":
        class_id = request.form.get("class_id")
        if class_id:
            conn.execute("UPDATE students SET class_id = ? WHERE email = ?", (class_id, session["username"]))
            conn.commit()
            flash("Třída byla úspěšně nastavena.")
        else:
            flash("Prosím, vyberte třídu.")
        conn.close()
        return redirect(url_for("python.student_dashboard"))
    
    conn.close()
    return render_template("python/change_class.html", classes=classes)
