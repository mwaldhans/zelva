# -*- coding: utf-8 -*-
"""Programov?n? v Pythonu - sada ?loh, odevzd?v?n? a p?ehledy pro u?itele.

P?ihl??en? ?e?? hlavn? aplikace (Google OAuth); tento blueprint z p?ihl??en?ho
u?ivatele jen odvod? roli (u?itel/student).
"""
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

import pytz
from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, session, url_for,
)

bp = Blueprint("python", __name__, url_prefix="/python")


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


@bp.route("/teacher")
@teacher_required
def teacher_dashboard():
    conn = get_db_connection()
    # Řadíme úlohy podle section_order (s využitím COALESCE), display_order a názvu
    assignments = conn.execute("SELECT * FROM assignments ORDER BY COALESCE(section_order, 0), COALESCE(display_order, 0), title").fetchall()
    conn.close()
    grouped = group_assignments(assignments)
    return render_template("python/teacher_dashboard.html", grouped=grouped)


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
    
    # Načtení studentů – podle filtrů tříd nebo emailů, pokud jsou zadány, jinak všechny
    student_query = "SELECT * FROM students"
    student_conditions = []
    student_params = []
    if selected_class_ids:
        placeholders = ",".join("?" for _ in selected_class_ids)
        student_conditions.append("class_id IN (" + placeholders + ")")
        student_params.extend(selected_class_ids)
    if selected_student_emails:
        placeholders = ",".join("?" for _ in selected_student_emails)
        student_conditions.append("email IN (" + placeholders + ")")
        student_params.extend(selected_student_emails)
    if student_conditions:
        student_query += " WHERE " + " AND ".join(student_conditions)
    student_query += " ORDER BY email"
    students = conn.execute(student_query, tuple(student_params)).fetchall()
    if not selected_class_ids and not selected_student_emails:
        students = conn.execute("SELECT * FROM students ORDER BY email").fetchall()
    
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
    query += " ORDER BY s.submission_time DESC"
    submissions = conn.execute(query, tuple(params)).fetchall()
    
    # Pro nabídku filtrů načteme všechna data z tabulek
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    # Všechny studenty
    all_students = conn.execute("SELECT * FROM students ORDER BY email").fetchall()
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
                           selected_assignment_ids=selected_assignment_ids)

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
            WHERE ca.class_id = ?
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
        "SELECT * FROM assignments ORDER BY COALESCE(section_order,0), COALESCE(display_order,0), title"
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
