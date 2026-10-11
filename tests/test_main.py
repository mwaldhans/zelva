from pathlib import Path
import sqlite3

from zelva.app import _is_allowed_login_email, create_app


def test_login_email_accepts_root_and_subdomains() -> None:
    assert _is_allowed_login_email("student@gymnzidlo.cz")
    assert _is_allowed_login_email("student@class.gymnzidlo.cz")
    assert _is_allowed_login_email("student@a.class.gymnzidlo.cz")
    assert _is_allowed_login_email("student@one.two.three.gymnzidlo.cz")
    assert not _is_allowed_login_email("student@gymnzidlo.cz.evil.test")
    assert not _is_allowed_login_email("student@other.cz")
    assert not _is_allowed_login_email("student@one..gymnzidlo.cz")


def test_home_page_is_available() -> None:
    app = create_app()
    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 302
    assert response.location.startswith("/login")


def test_health_api_is_available() -> None:
    app = create_app()
    client = app.test_client()
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "service": "zelva-web"}


def test_progress_api_persists_solution(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    client = app.test_client()

    with client.session_transaction() as session:
        session["user"] = {"sub": "student-1", "email": "student@gymnzidlo.cz"}

    save_response = client.put(
        "/api/progress/square",
        json={
            "solution_text": "forward(100)\nleft(90)",
            "solved": True,
            "score": 0.95,
        },
    )

    assert save_response.status_code == 200
    assert save_response.json["pattern_id"] == "square"
    assert save_response.json["solved"] is True

    load_response = client.get("/api/progress")
    assert load_response.status_code == 200
    assert len(load_response.json["items"]) == 1
    assert load_response.json["items"][0]["pattern_id"] == "square"
    assert load_response.json["items"][0]["solution_text"] == "forward(100)\nleft(90)"


def test_progress_api_recreates_missing_unique_index(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE user_progress (
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
    connection.execute(
        "INSERT INTO user_progress (user_id, pattern_id, solution_text, solved, score, user_name, user_email, time_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("student-1", "square", "forward(100)", 1, 0.8, "Student", "student@gymnzidlo.cz", 5),
    )
    connection.execute(
        "INSERT INTO user_progress (user_id, pattern_id, solution_text, solved, score, user_name, user_email, time_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("student-1", "square", "forward(200)", 0, 0.4, "Student", "student@gymnzidlo.cz", 7),
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "DATABASE": str(db_path)})
    client = app.test_client()

    with client.session_transaction() as session:
        session["user"] = {"sub": "student-1", "email": "student@gymnzidlo.cz"}

    response = client.put(
        "/api/progress/square",
        json={
            "solution_text": "forward(150)",
            "solved": True,
            "score": 0.9,
            "time_seconds": 9,
        },
    )

    assert response.status_code == 200
    assert response.json["pattern_id"] == "square"
    assert response.json["solved"] is True


def test_progress_is_isolated_per_browser_client(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    client_a = app.test_client()
    client_b = app.test_client()

    with client_a.session_transaction() as session:
        session["user"] = {"sub": "student-a", "email": "a@gymnzidlo.cz"}
    with client_b.session_transaction() as session:
        session["user"] = {"sub": "student-b", "email": "b@gymnzidlo.cz"}

    response_a = client_a.put(
        "/api/progress/square",
        json={
            "solution_text": "fd(100)",
            "solved": True,
            "score": 1.0,
        },
    )
    assert response_a.status_code == 200

    load_b = client_b.get("/api/progress")
    assert load_b.status_code == 200
    assert load_b.json["items"] == []

    load_a = client_a.get("/api/progress")
    assert load_a.status_code == 200
    assert len(load_a.json["items"]) == 1
    assert load_a.json["items"][0]["pattern_id"] == "square"


def test_python_dashboard_marks_successful_assignments(tmp_path: Path) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    client = app.test_client()
    email = "student@gymnzidlo.cz"
    with client.session_transaction() as session:
        session["user"] = {"sub": email, "email": email, "name": "Student"}

    conn = sqlite3.connect(python_db)
    conn.execute(
        "INSERT INTO assignments (id, title, description, teacher_code, section) "
        "VALUES (1, 'Hotový úkol', '', '', 'Základy')"
    )
    conn.execute(
        "INSERT INTO submissions "
        "(assignment_id, student_email, student_code, result, help_used) "
        "VALUES (1, ?, '', 'Test prošel!', 0)",
        (email,),
    )
    conn.commit()
    conn.close()

    response = client.get("/python/student")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "card assignment-card status-success" in html
    assert "Hotový úkol" in html

    theme = client.get("/static/python-theme.css").get_data(as_text=True)
    assert ".python-course .card.status-success" in theme


def test_student_assignment_prefills_latest_submission(tmp_path: Path) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    client = app.test_client()
    email = "student@gymnzidlo.cz"
    with client.session_transaction() as session:
        session["user"] = {"sub": email, "email": email, "name": "Student"}

    conn = sqlite3.connect(python_db)
    conn.execute(
        "INSERT INTO assignments (id, title, teacher_code, section) "
        "VALUES (1, 'Testovací úkol', 'def solve():\n    return 1', 'Základy')"
    )
    conn.executemany(
        "INSERT INTO submissions "
        "(assignment_id, student_email, student_code, result, submission_time) "
        "VALUES (1, ?, ?, 'Test selhal.', ?)",
        [
            (email, "def solve():\n    return 2", "2026-10-10 10:00:00"),
            (email, "def solve():\n    return 3", "2026-10-11 10:00:00"),
            ("other@gymnzidlo.cz", "def solve():\n    return 4", "2026-10-12 10:00:00"),
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/python/student/assignment/1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert (
        '<textarea name="student_code" id="student_code" rows="10"\n'
        '                  class="form-control border-0 p-0">def solve():\n'
        "    return 3</textarea>"
    ) in html


def test_admin_patterns_persist_in_sqlite(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    client = app.test_client()

    with client.session_transaction() as session:
        session["user"] = {"sub": "admin-1", "email": "waldhans.m@gymnzidlo.cz"}

    override_response = client.put(
        "/api/pattern-overrides/square",
        json={"name": "Upraveny ctverec", "commands": ["forward(10)", "left(90)"]},
    )

    assert override_response.status_code == 200
    assert override_response.json["override"]["name"] == "Upraveny ctverec"

    custom_response = client.post(
        "/api/custom-patterns",
        json={
            "id": "moje_uloha",
            "name": "Moje uloha",
            "category": "Testy",
            "commands": ["forward(20)"],
        },
    )

    assert custom_response.status_code == 201

    second_custom_response = client.post(
        "/api/custom-patterns",
        json={
            "id": "druha_uloha",
            "name": "Druha uloha",
            "category": "Testy",
            "commands": ["forward(30)"],
        },
    )

    assert second_custom_response.status_code == 201

    delete_custom_response = client.delete("/api/custom-patterns/moje_uloha")
    assert delete_custom_response.status_code == 200

    remaining_patterns_response = client.get("/api/pattern-overrides")
    assert "moje_uloha" not in remaining_patterns_response.json["custom_patterns"]

    delete_builtin_response = client.delete("/api/custom-patterns/square")
    assert delete_builtin_response.status_code == 200

    patterns_response = client.get("/api/pattern-overrides")
    assert "square" in patterns_response.json["deleted_patterns"]

    connection = sqlite3.connect(str(tmp_path / "test.db"))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {"pattern_overrides", "custom_patterns"}.issubset(tables)

def _python_app(tmp_path: Path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "z.db"),
        "PYTHON_DATABASE": str(tmp_path / "p.db"),
    })


def _login(client, email: str) -> None:
    with client.session_transaction() as session:
        session["user"] = {"sub": email, "email": email, "name": "Test"}


def test_hub_offers_turtle_and_python(tmp_path: Path) -> None:
    client = _python_app(tmp_path).test_client()
    _login(client, "student@gymnzidlo.cz")

    html = client.get("/").get_data(as_text=True)
    assert 'href="/zelva"' in html
    assert 'href="/python/"' in html
    turtle_html = client.get("/zelva").get_data(as_text=True)
    assert "Rozcestn&#237;k" in turtle_html
    assert 'href="/" ' in turtle_html or 'href="/">Rozcestn&#237;k' in turtle_html


def test_python_course_student_and_teacher_roles(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    client = app.test_client()

    assert client.get("/python/").status_code == 302
    assert "/login" in client.get("/python/").location

    _login(client, "student@gymnzidlo.cz")
    assert client.get("/python/").location.endswith("/python/student")
    student_page = client.get("/python/student")
    assert student_page.status_code == 200
    assert "python-site-header" in student_page.get_data(as_text=True)
    assert "Logo Gymnázium Židlochovice" in student_page.get_data(as_text=True)
    theme = client.get("/static/python-theme.css").get_data(as_text=True)
    assert ".python-course.bg-light" in theme
    assert "background: var(--python-panel)" in theme
    assert "border: 1px solid var(--python-border)" in theme
    assert client.get("/python/teacher").status_code == 302

    conn = sqlite3.connect(tmp_path / "p.db")
    assert conn.execute("SELECT COUNT(*) FROM students WHERE email='student@gymnzidlo.cz'").fetchone()[0] == 1
    conn.close()

    teacher = app.test_client()
    _login(teacher, app.config["ADMIN_EMAIL"])
    assert teacher.get("/python/").location.endswith("/python/teacher")
    for path in ("/python/teacher", "/python/teacher/create", "/python/teacher/statistics",
                 "/python/teacher/manage_students", "/python/teacher/assigned",
                 "/python/teacher/submissions"):
        assert teacher.get(path).status_code == 200, path
