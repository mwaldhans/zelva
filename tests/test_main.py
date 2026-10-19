from io import BytesIO
import json
import sqlite3
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
import pytz

from zelva.app import _is_allowed_login_email, create_app
from zelva.python_course import AZ_BOARD_SIZE, _az_connected, _az_question_payload, init_db


def test_login_email_accepts_root_and_subdomains() -> None:
    assert _is_allowed_login_email("student@gymnzidlo.cz")
    assert _is_allowed_login_email("student@class.gymnzidlo.cz")
    assert _is_allowed_login_email("student@a.class.gymnzidlo.cz")
    assert _is_allowed_login_email("student@one.two.three.gymnzidlo.cz")
    assert _is_allowed_login_email("student@gymkren.cz")
    assert _is_allowed_login_email("student@class.gymkren.cz")
    assert _is_allowed_login_email("student@CLASS.GYMKREN.CZ")
    assert not _is_allowed_login_email("student@gymnzidlo.cz.evil.test")
    assert not _is_allowed_login_email("student@gymkren.cz.evil.test")
    assert not _is_allowed_login_email("student@other.cz")
    assert not _is_allowed_login_email("student@one..gymnzidlo.cz")


def test_home_page_is_available() -> None:
    app = create_app()
    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 302
    assert response.location.startswith("/login")


def test_azkviz_question_answer_options_are_shuffled_together(monkeypatch) -> None:
    def reverse_choices(choices):
        choices.reverse()

    monkeypatch.setattr("zelva.python_course.random.shuffle", reverse_choices)
    question = _az_question_payload({
        "id": 5,
        "question": "Která odpověď je správně?",
        "options": json.dumps(["špatně 1", "správně", "špatně 2"]),
        "answer": 1,
    })

    assert question["options"] == ["špatně 2", "správně", "špatně 1"]
    assert question["options"][question["answer"]] == "správně"


def test_hub_shows_azkviz_as_third_main_section(tmp_path: Path) -> None:
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(tmp_path / "python.db"),
    })
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {
            "sub": "student@gymnzidlo.cz",
            "email": "student@gymnzidlo.cz",
            "name": "Student",
        }

    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert html.index("<h2>Želva</h2>") < html.index("<h2>Programování v Pythonu</h2>")
    assert html.index("<h2>Programování v Pythonu</h2>") < html.index("<h2>Kvinta kvíz</h2>")
    assert "/python/azkviz" in html


def test_teacher_can_play_azkviz_against_student(tmp_path: Path) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    teacher = app.test_client()
    student = app.test_client()

    with teacher.session_transaction() as session:
        email = app.config["ADMIN_EMAIL"]
        session["user"] = {
            "sub": email,
            "email": email,
            "name": "Učitel",
            "picture": "https://lh3.googleusercontent.com/teacher-photo",
        }
    with student.session_transaction() as session:
        session["user"] = {
            "sub": "student@gymnzidlo.cz",
            "email": "student@gymnzidlo.cz",
            "name": "Student",
            "picture": "https://lh3.googleusercontent.com/student-photo",
        }

    page = teacher.get("/python/azkviz")
    assert page.status_code == 200
    page_html = page.get_data(as_text=True)
    assert "Kvinta kvíz" in page_html
    assert "První hráč" in page_html
    assert "Druhý hráč" in page_html
    assert 'id="player-a-turn"' in page_html
    assert "clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%)" in page_html
    assert '<dialog id="question-modal"' in page_html
    assert page_html.index('<p id="answer-clock"') > page_html.index(
        '<dialog id="question-modal"'
    )
    assert page_html.index('<p id="answer-clock"') < page_html.index(
        '<h2 id="question-text"'
    )
    assert '<dialog id="reaction-modal"' in page_html
    assert "reactionModal.showModal()" in page_html
    assert 'id="winner-banner"' in page_html
    assert "game.winner_name" in page_html
    assert "questionModal.showModal()" in page_html
    question_click_flow = page_html.split(
        "if (currentGame.question && !questionModal.open)", 1
    )[1].split("row.appendChild(cell)", 1)[0]
    assert question_click_flow.index("questionModal.showModal()") < (
        question_click_flow.index("await send(")
    )
    assert "polling || answerSubmitting || questionStarting" in page_html
    assert "questionModal.close()" in page_html
    assert 'id="answer-result"' in page_html
    assert "playCorrectSound()" in page_html
    assert "playWrongSound()" in page_html
    assert "timeoutSoundKey !== lastTimeoutSoundKey" in page_html
    assert '"az-answer-result alert alert-danger"' in page_html
    assert "waitForQuestionClose(3000)" in page_html
    assert 'id="forfeit-game"' in page_html
    assert 'id="regular-content"' in page_html
    assert 'id="nickname-panel"' in page_html
    assert 'id="standings"' in page_html
    assert "nicknamePanel.hidden = lobbyView || game.status === \"playing\"" in page_html

    waiting = teacher.post("/python/azkviz/match")
    assert waiting.status_code == 200
    assert waiting.json["status"] == "waiting"
    paired = student.post("/python/azkviz/match")
    assert paired.status_code == 200
    assert paired.json["id"] == waiting.json["id"]
    assert paired.json["status"] == "playing"
    assert paired.json["player_a_picture"] == "https://lh3.googleusercontent.com/teacher-photo"
    assert paired.json["player_b_picture"] == "https://lh3.googleusercontent.com/student-photo"
    assert teacher.get(f"/python/azkviz/game/{paired.json['id']}").json["player_b_picture"] == (
        "https://lh3.googleusercontent.com/student-photo"
    )

    with sqlite3.connect(python_db) as conn:
        teacher_student_record = conn.execute(
            "SELECT COUNT(*) FROM students WHERE email = ?",
            (app.config["ADMIN_EMAIL"],),
        ).fetchone()[0]
    assert teacher_student_record == 0


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
    assert 'class="chip status-success"' in html
    assert "Hotový úkol" in html
    assert "AZkvíz" not in html

    theme = client.get("/static/python-theme.css").get_data(as_text=True)
    assert ".python-course .card.status-success" in theme


def test_azkviz_matches_players_and_records_winner_stats(tmp_path: Path) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    player_a = app.test_client()
    player_b = app.test_client()

    for client, email, name in (
        (player_a, "a@gymnzidlo.cz", "Alice"),
        (player_b, "b@gymnzidlo.cz", "Bob"),
    ):
        with client.session_transaction() as session:
            session["user"] = {"sub": email, "email": email, "name": name}

    waiting = player_a.post("/python/azkviz/match")
    assert waiting.status_code == 200
    assert waiting.json["status"] == "waiting"
    assert waiting.json["board_size"] == AZ_BOARD_SIZE == 4
    assert len(waiting.json["board"]) == 10
    game_id = waiting.json["id"]

    matched = player_b.post("/python/azkviz/match")
    assert matched.status_code == 200
    assert matched.json["id"] == game_id
    assert matched.json["status"] == "playing"
    assert not matched.json["my_turn"]
    assert matched.json["question"] is None
    assert matched.json["my_name"] == "Bob"
    assert matched.json["opponent_name"] == "Alice"
    player_a_state = player_a.get(f"/python/azkviz/game/{game_id}").json
    assert player_a_state["my_name"] == "Alice"
    assert player_a_state["opponent_name"] == "Bob"

    outsider = app.test_client()
    with outsider.session_transaction() as session:
        session["user"] = {
            "sub": "outsider@gymnzidlo.cz",
            "email": "outsider@gymnzidlo.cz",
            "name": "Outsider",
        }
    assert outsider.get(f"/python/azkviz/game/{game_id}").status_code == 403

    def question_answer(client):
        state = client.get(f"/python/azkviz/game/{game_id}").json
        assert state["my_turn"]
        conn = sqlite3.connect(python_db)
        question_payload = conn.execute(
            "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
        ).fetchone()[0]
        conn.close()
        assert question_payload
        return state, json.loads(question_payload)["answer"]

    state, correct_answer = question_answer(player_a)
    assert state["question"] is not None
    _az_start_question(player_a, game_id, 9)
    no_cell = player_a.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={"answer": correct_answer},
    )
    assert no_cell.status_code == 400
    assert player_a.get(f"/python/azkviz/game/{game_id}").json["my_turn"]

    wrong = (correct_answer + 1) % len(state["question"]["options"])
    _az_start_question(player_a, game_id, 9)
    result = player_a.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={"answer": wrong, "cell": 9},
    )
    assert result.status_code == 200
    assert result.json["correct"] is False
    assert result.json["game"]["board"] == [None] * 9 + ["X"]
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["my_turn"]

    assert not _az_connected(
        [None, "a@gymnzidlo.cz", None, None, "a@gymnzidlo.cz",
         None, None, None, "a@gymnzidlo.cz", None],
        "a@gymnzidlo.cz",
    )

    for move_index, (cell, gray_cell) in enumerate(zip((0, 1, 3, 6), (8, 7, 2, 5))):
        state_b, answer_b = question_answer(player_b)
        wrong_b = (answer_b + 1) % len(state_b["question"]["options"])
        _az_start_question(player_b, game_id, gray_cell)
        wrong_result = player_b.post(
            f"/python/azkviz/game/{game_id}/answer",
            json={"answer": wrong_b, "cell": gray_cell},
        )
        assert wrong_result.status_code == 200
        assert wrong_result.json["game"]["board"][gray_cell] == "X"

        _, answer_a = question_answer(player_a)
        _az_start_question(player_a, game_id, cell)
        result_a = player_a.post(
            f"/python/azkviz/game/{game_id}/answer",
            json={"answer": answer_a, "cell": cell},
        )
        assert result_a.status_code == 200
        assert result_a.json["correct"] is True
        assert result_a.json["game"]["board"][cell] == "A"
        if move_index < 3:
            assert result_a.json["game"]["status"] == "playing"
        else:
            assert result_a.json["game"]["status"] == "finished"
            assert result_a.json["game"]["winner"] == "you"
            assert result_a.json["game"]["winner_name"] == "Alice"

    with sqlite3.connect(python_db) as conn:
        stored = conn.execute(
            "SELECT status, winner_email FROM az_games WHERE id = ?", (game_id,)
        ).fetchone()
    assert stored == ("finished", "a@gymnzidlo.cz")

    stats_a = player_a.get("/python/azkviz")
    assert stats_a.status_code == 200
    assert "výher" in stats_a.get_data(as_text=True)
    assert "Bob" in stats_a.get_data(as_text=True)
    stats_b = player_b.get("/python/azkviz").get_data(as_text=True)
    assert "Prohra" in stats_b
    assert "Alice" in stats_b
    lost_game = player_b.get(f"/python/azkviz/game/{game_id}").json
    assert lost_game["winner"] == "opponent"
    assert lost_game["winner_name"] == "Alice"


def test_azkviz_question_timeout_grays_locked_cell_and_uses_prague_time(
    tmp_path: Path,
) -> None:
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")

    game = player_a.post("/python/azkviz/match", json={"mode": "random"}).json
    game_id = game["id"]
    player_b.post("/python/azkviz/match", json={"mode": "random"})
    with sqlite3.connect(tmp_path / "p.db") as conn:
        created_at, updated_at = conn.execute(
            "SELECT created_at, updated_at FROM az_games WHERE id = ?", (game_id,)
        ).fetchone()
    prague = datetime.now(pytz.timezone("Europe/Prague"))
    assert datetime.fromisoformat(created_at).utcoffset() == prague.utcoffset()
    assert datetime.fromisoformat(updated_at).utcoffset() == prague.utcoffset()

    started = _az_start_question(player_a, game_id, 4)
    assert started["question_cell"] == 4
    assert started["answer_timeout_seconds"] == 20
    assert datetime.fromisoformat(started["question_started_at"]).utcoffset() == (
        prague.utcoffset()
    )
    cannot_switch = player_a.post(
        f"/python/azkviz/game/{game_id}/question/start", json={"cell": 5}
    )
    assert cannot_switch.status_code == 409

    old_start = (
        datetime.now(pytz.timezone("Europe/Prague")) - timedelta(seconds=21)
    ).isoformat(sep=" ", timespec="milliseconds")
    with sqlite3.connect(tmp_path / "p.db") as conn:
        conn.execute(
            "UPDATE az_games SET question_started_at = ? WHERE id = ?",
            (old_start, game_id),
        )

    expired = player_a.get(f"/python/azkviz/game/{game_id}").json
    assert expired["board"][4] == "X"
    assert expired["my_turn"] is False
    assert expired["question_cell"] is None
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["my_turn"] is True


def test_azkviz_lobby_nicknames_and_leaderboard(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")
    player_a.get("/python/azkviz")
    player_b.get("/python/azkviz")

    assert player_a.post(
        "/python/azkviz/nickname", data={"nickname": "Alpha"}
    ).status_code == 302
    duplicate = player_b.post(
        "/python/azkviz/nickname", data={"nickname": "alpha"}
    )
    assert duplicate.status_code == 302
    assert "už je obsazená" in player_b.get("/python/azkviz").get_data(as_text=True)
    player_b.post("/python/azkviz/nickname", data={"nickname": "Beta"})

    with player_a.session_transaction() as session:
        session["user"] = {
            **session["user"],
            "picture": "https://lh3.googleusercontent.com/alpha-photo",
        }
    with sqlite3.connect(tmp_path / "p.db") as conn:
        conn.executemany(
            """
            INSERT INTO az_games
                (player_a_email, player_a_name, player_b_email, player_b_name,
                 status, turn_email, board, winner_email)
            VALUES (?, 'Alpha', ?, 'Opponent', 'finished', NULL, ?, ?)
            """,
            [
                ("a@gymnzidlo.cz", "c@gymnzidlo.cz", json.dumps([None] * 10), "a@gymnzidlo.cz"),
                ("d@gymnzidlo.cz", "a@gymnzidlo.cz", json.dumps([None] * 10), "d@gymnzidlo.cz"),
            ],
        )
    waiting = player_a.post(
        "/python/azkviz/match", json={"mode": "lobby"}
    ).json
    lobby = player_b.get("/python/azkviz/lobby").json
    assert lobby["players"] == [{
        "game_id": waiting["id"],
        "nickname": "Alpha",
        "picture": "https://lh3.googleusercontent.com/alpha-photo",
        "games": 2,
        "wins": 1,
    }]
    page_html = player_b.get("/python/azkviz").get_data(as_text=True)
    assert "az-lobby-avatar" in page_html
    assert "safePlayerPicture(player.picture)" in page_html
    assert 'label: "Odehráno"' in page_html
    assert 'label: "Výhry"' in page_html
    matched = player_b.post(
        "/python/azkviz/match",
        json={"mode": "selected", "game_id": waiting["id"]},
    ).json
    assert matched["status"] == "playing"
    assert matched["my_name"] == "Beta"
    assert matched["opponent_name"] == "Alpha"

    with sqlite3.connect(tmp_path / "p.db") as conn:
        conn.execute(
            "UPDATE az_games SET status = 'finished', winner_email = ? WHERE id = ?",
            ("a@gymnzidlo.cz", waiting["id"]),
        )
    html = player_a.get("/python/azkviz").get_data(as_text=True)
    assert html.index("Alpha") < html.index("Beta")
    assert "Žebříček hráčů" in html


def test_azkviz_player_can_forfeit_and_award_opponent_the_win(
    tmp_path: Path,
) -> None:
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")

    waiting = player_a.post("/python/azkviz/match", json={"mode": "random"}).json
    matched = player_b.post("/python/azkviz/match", json={"mode": "random"}).json
    game_id = matched["id"]
    assert waiting["id"] == game_id
    assert matched["status"] == "playing"

    forfeited = player_a.post(f"/python/azkviz/game/{game_id}/forfeit")
    assert forfeited.status_code == 200
    assert forfeited.json["game"]["status"] == "finished"
    assert forfeited.json["game"]["winner"] == "opponent"
    assert forfeited.json["game"]["winner_name"]
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["winner"] == "you"
    assert player_a.post(f"/python/azkviz/game/{game_id}/forfeit").status_code == 409

    with sqlite3.connect(tmp_path / "p.db") as conn:
        stored = conn.execute(
            """
            SELECT status, winner_email, turn_email, current_question,
                   challenge_active, challenge_cell, challenge_started_at,
                   question_started_at, question_cell
            FROM az_games WHERE id = ?
            """,
            (game_id,),
        ).fetchone()
    assert stored == (
        "finished", "b@gymnzidlo.cz", None, None, 0, None, None, None, None
    )
    assert "Prohra" in player_a.get("/python/azkviz").get_data(as_text=True)
    assert "Výhra" in player_b.get("/python/azkviz").get_data(as_text=True)


def test_azkviz_abandons_games_after_ten_inactive_minutes(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")
    game = player_a.post("/python/azkviz/match", json={"mode": "random"}).json
    player_b.post("/python/azkviz/match", json={"mode": "random"})

    stale_time = (
        datetime.now(pytz.timezone("Europe/Prague")) - timedelta(minutes=11)
    ).isoformat(sep=" ", timespec="milliseconds")
    with sqlite3.connect(tmp_path / "p.db") as conn:
        conn.execute(
            "UPDATE az_games SET updated_at = ? WHERE id = ?",
            (stale_time, game["id"]),
        )

    expired = player_a.get(f"/python/azkviz/game/{game['id']}").json
    assert expired["status"] == "abandoned"
    replacement = player_a.post(
        "/python/azkviz/match", json={"mode": "random"}
    ).json
    assert replacement["id"] != game["id"]
    with sqlite3.connect(tmp_path / "p.db") as conn:
        status = conn.execute(
            "SELECT status FROM az_games WHERE id = ?", (game["id"],)
        ).fetchone()[0]
    assert status == "abandoned"


def test_azkviz_gray_cell_reaction_and_early_press(tmp_path: Path) -> None:
    python_db = tmp_path / "p.db"
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")

    game = player_a.post("/python/azkviz/match").json
    game_id = game["id"]
    assert player_b.post("/python/azkviz/match").json["status"] == "playing"

    state_a = player_a.get(f"/python/azkviz/game/{game_id}").json
    with sqlite3.connect(python_db) as conn:
        question = json.loads(
            conn.execute(
                "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
            ).fetchone()[0]
        )
    _az_start_question(player_a, game_id, 0)
    failed = player_a.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={"answer": (question["answer"] + 1) % len(question["options"]), "cell": 0},
    )
    assert failed.status_code == 200
    assert failed.json["game"]["board"][0] == "X"
    assert state_a["my_turn"]
    assert not player_a.get(f"/python/azkviz/game/{game_id}").json["my_turn"]
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["my_turn"]

    # Only the player whose turn it is may start the shared gray-cell challenge.
    denied_challenge = player_a.post(
        f"/python/azkviz/game/{game_id}/challenge", json={"cell": 0}
    )
    assert denied_challenge.status_code == 409
    assert "je na tahu" in denied_challenge.json["error"]
    challenge = player_b.post(
        f"/python/azkviz/game/{game_id}/challenge", json={"cell": 0}
    )
    assert challenge.status_code == 200
    assert challenge.json["challenge"]["cell"] == 0
    assert isinstance(challenge.json["challenge"]["server_now_ms"], (int, float))
    assert challenge.json["question"] is None
    assert player_a.get(f"/python/azkviz/game/{game_id}").json["challenge"] is not None
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["challenge"] is not None
    with sqlite3.connect(python_db) as conn:
        during_challenge_question = json.loads(
            conn.execute(
                "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
            ).fetchone()[0]
        )
    bypass = player_b.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={"answer": during_challenge_question["answer"], "cell": 2},
    )
    assert bypass.status_code == 409
    assert player_a.get(f"/python/azkviz/game/{game_id}").json["challenge"]["frames"] == (
        challenge.json["challenge"]["frames"]
    )

    with sqlite3.connect(python_db) as conn:
        conn.execute(
            "UPDATE az_games SET challenge_started_at = ? WHERE id = ?",
            (
                challenge.json["challenge"]["started_at"]
                - challenge.json["challenge"]["target_ms"]
                - 100,
                game_id,
            ),
        )
    reaction_b = player_b.post(f"/python/azkviz/game/{game_id}/challenge/react")
    reaction_a = player_a.post(f"/python/azkviz/game/{game_id}/challenge/react")
    assert reaction_b.status_code == reaction_a.status_code == 200
    assert reaction_b.json["correct"] is True
    assert reaction_a.json["correct"] is True
    assert reaction_a.json["game"]["board"][0] == "B"
    assert reaction_a.json["game"]["status"] == "playing"
    assert reaction_a.json["game"]["winner"] is None
    assert reaction_a.json["game"]["winner_name"] is None
    assert reaction_a.json["game"]["challenge"] is None
    assert player_a.get(f"/python/azkviz/game/{game_id}").json["my_turn"] == (
        reaction_a.json["game"]["board"][0] == "B"
    )
    assert player_b.get(f"/python/azkviz/game/{game_id}").json["my_turn"] == (
        reaction_a.json["game"]["board"][0] == "A"
    )

    # The next player creates another gray cell and loses immediately on an early key press.
    with sqlite3.connect(python_db) as conn:
        current = json.loads(
            conn.execute(
                "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
            ).fetchone()[0]
        )
    current_turn = (
        player_a
        if player_a.get(f"/python/azkviz/game/{game_id}").json["my_turn"]
        else player_b
    )
    _az_start_question(current_turn, game_id, 1)
    missed = current_turn.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={"answer": (current["answer"] + 1) % len(current["options"]), "cell": 1},
    )
    assert missed.status_code == 200
    assert missed.json["game"]["board"][1] == "X"
    challenge_turn = player_b if current_turn is player_a else player_a
    early_challenge = challenge_turn.post(
        f"/python/azkviz/game/{game_id}/challenge", json={"cell": 1}
    )
    assert early_challenge.status_code == 200
    early = challenge_turn.post(f"/python/azkviz/game/{game_id}/challenge/react")
    assert early.status_code == 200
    assert early.json["correct"] is False
    assert early.json["game"]["status"] == "playing"
    assert early.json["game"]["winner"] is None
    assert early.json["game"]["winner_name"] is None
    assert early.json["game"]["board"][1] == (
        "A" if challenge_turn is player_b else "B"
    )
    assert challenge_turn.get(f"/python/azkviz/game/{game_id}").json["my_turn"]
    assert not current_turn.get(f"/python/azkviz/game/{game_id}").json["my_turn"]


def test_azkviz_reaction_winner_only_claims_cell(tmp_path: Path) -> None:
    python_db = tmp_path / "p.db"
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")

    waiting = player_a.post("/python/azkviz/match").json
    player_b.post("/python/azkviz/match")
    game_id = waiting["id"]

    board = ["X"] + ["a@gymnzidlo.cz"] * 8 + ["b@gymnzidlo.cz"]
    with sqlite3.connect(python_db) as conn:
        conn.execute(
            """
            UPDATE az_games
            SET board = ?, challenge_cell = 0, challenge_started_at = ?,
                challenge_target_ms = 100, challenge_frames = '[]',
                challenge_reactions = ?, challenge_active = 1
            WHERE id = ?
            """,
            (
                json.dumps(board),
                0,
                json.dumps({"a@gymnzidlo.cz": 20}),
                game_id,
            ),
        )

    finished = player_a.get(f"/python/azkviz/game/{game_id}")
    assert finished.status_code == 200
    assert finished.json["board"] == ["A"] * 9 + ["B"]
    assert finished.json["status"] == "finished"
    assert finished.json["winner"] == "you"

    second = player_a.post("/python/azkviz/match").json
    player_b.post("/python/azkviz/match")
    board = ["X", None, None, None, None, None, None, None, None, "b@gymnzidlo.cz"]
    with sqlite3.connect(python_db) as conn:
        conn.execute(
            """
            UPDATE az_games
            SET board = ?, challenge_cell = 0, challenge_started_at = ?,
                challenge_target_ms = 100, challenge_frames = '[]',
                challenge_reactions = ?, challenge_active = 1
            WHERE id = ?
            """,
            (json.dumps(board), 0, json.dumps({"a@gymnzidlo.cz": 20}), second["id"]),
        )
    finished = player_a.get(f"/python/azkviz/game/{second['id']}")
    assert finished.json["status"] == "playing"
    assert finished.json["winner"] is None
    assert finished.json["my_turn"] is False
    assert player_b.get(f"/python/azkviz/game/{second['id']}").json["my_turn"]


def test_azkviz_gray_cell_prevents_full_board_draw(tmp_path: Path) -> None:
    python_db = tmp_path / "p.db"
    app = _python_app(tmp_path)
    player_a = app.test_client()
    player_b = app.test_client()
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")

    game = player_a.post("/python/azkviz/match").json
    player_b.post("/python/azkviz/match")
    game_id = game["id"]
    nearly_full_board = [
        "a@gymnzidlo.cz", "b@gymnzidlo.cz", "a@gymnzidlo.cz",
        "b@gymnzidlo.cz", "a@gymnzidlo.cz", "b@gymnzidlo.cz",
        "a@gymnzidlo.cz", "b@gymnzidlo.cz", "a@gymnzidlo.cz", None,
    ]
    with sqlite3.connect(python_db) as conn:
        conn.execute(
            "UPDATE az_games SET board = ?, turn_email = ? WHERE id = ?",
            (json.dumps(nearly_full_board), "a@gymnzidlo.cz", game_id),
        )
        question = json.loads(
            conn.execute(
                "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
            ).fetchone()[0]
        )

    _az_start_question(player_a, game_id, 9)
    response = player_a.post(
        f"/python/azkviz/game/{game_id}/answer",
        json={
            "answer": (question["answer"] + 1) % len(question["options"]),
            "cell": 9,
        },
    )
    assert response.status_code == 200
    assert response.json["game"]["board"][-1] == "X"
    assert response.json["game"]["status"] == "playing"
    assert response.json["game"]["winner"] is None
    challenge = player_b.post(
        f"/python/azkviz/game/{game_id}/challenge", json={"cell": 9}
    )
    assert challenge.status_code == 200
    assert challenge.json["challenge"]["cell"] == 9


def test_azkviz_abandons_active_games_with_old_board_shape(tmp_path: Path) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    with sqlite3.connect(python_db) as conn:
        conn.execute(
            """
            INSERT INTO az_games
                (player_a_email, player_a_name, player_b_email, player_b_name,
                 status, turn_email, board, question_index)
            VALUES (?, ?, ?, ?, 'playing', ?, ?, ?)
            """,
            (
                "a@gymnzidlo.cz", "Alice", "b@gymnzidlo.cz", "Bob",
                "a@gymnzidlo.cz", json.dumps([None] * 9), 0,
            ),
        )

    init_db(str(python_db))

    with sqlite3.connect(python_db) as conn:
        status = conn.execute(
            "SELECT status FROM az_games WHERE player_a_email = ?",
            ("a@gymnzidlo.cz",),
        ).fetchone()[0]
    assert status == "abandoned"


def test_admin_can_manage_azkviz_questions_and_inflight_question_is_unchanged(
    tmp_path: Path,
) -> None:
    python_db = tmp_path / "python.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(python_db),
    })
    app.config["PYTHON_TEACHER_EMAILS"] = ["teacher@gymnzidlo.cz"]
    admin = app.test_client()
    player_a = app.test_client()
    player_b = app.test_client()
    teacher = app.test_client()

    with admin.session_transaction() as session:
        email = app.config["ADMIN_EMAIL"]
        session["user"] = {"sub": email, "email": email, "name": "Admin"}
    for client, email, name in (
        (player_a, "a@gymnzidlo.cz", "Alice"),
        (player_b, "b@gymnzidlo.cz", "Bob"),
    ):
        with client.session_transaction() as session:
            session["user"] = {"sub": email, "email": email, "name": name}
    with teacher.session_transaction() as session:
        session["user"] = {
            "sub": "teacher@gymnzidlo.cz",
            "email": "teacher@gymnzidlo.cz",
            "name": "Teacher",
        }

    editor_url = "/python/admin/azkviz/questions"
    assert admin.get(editor_url).status_code == 200
    assert teacher.get(editor_url).status_code == 302
    assert player_a.get(editor_url).status_code == 302

    created = admin.post(editor_url, data={
        "action": "create",
        "question": "Kolik je 2 + 2?",
        "options": "3\n4\n5",
        "answer": "1",
        "active": "1",
    })
    assert created.status_code == 302
    with sqlite3.connect(python_db) as conn:
        question_id = conn.execute(
            "SELECT id FROM az_questions WHERE question = ?",
            ("Kolik je 2 + 2?",),
        ).fetchone()[0]
        defaults = conn.execute(
            "SELECT id, question, options, answer FROM az_questions WHERE id <> ?",
            (question_id,),
        ).fetchall()

    for default_id, text, options_json, answer in defaults:
        disabled = admin.post(editor_url, data={
            "action": "update",
            "question_id": str(default_id),
            "question": text,
            "options": "\n".join(json.loads(options_json)),
            "answer": str(answer),
        })
        assert disabled.status_code == 302

    # The selected question is stored in the game so edits do not change a live turn.
    waiting = player_a.post("/python/azkviz/match")
    paired = player_b.post("/python/azkviz/match")
    assert paired.json["id"] == waiting.json["id"]
    game_id = waiting.json["id"]
    state = player_a.get(f"/python/azkviz/game/{game_id}").json
    with sqlite3.connect(python_db) as conn:
        current = json.loads(conn.execute(
            "SELECT current_question FROM az_games WHERE id = ?", (game_id,)
        ).fetchone()[0])
    assert current["id"] == question_id
    original_text = current["question"]
    edited = admin.post(editor_url, data={
        "action": "update",
        "question_id": str(question_id),
        "question": "Změněná otázka?",
        "options": "3\n4\n5",
        "answer": "1",
        "active": "1",
    })
    assert edited.status_code == 302
    state = player_a.get(f"/python/azkviz/game/{game_id}").json
    assert state["question"]["text"] == original_text

    deactivate_last = admin.post(editor_url, data={
        "action": "update",
        "question_id": str(question_id),
        "question": "Kolik je 2 + 2?",
        "options": "3\n4\n5",
        "answer": "1",
    })
    assert deactivate_last.status_code == 302
    assert "Musí zůstat alespoň jedna aktivní otázka." in admin.get(editor_url).get_data(as_text=True)

    invalid = admin.post(editor_url, data={
        "action": "update",
        "question_id": str(question_id),
        "question": "Neplatná otázka?",
        "options": "jen jedna",
        "answer": "0",
        "active": "1",
    })
    assert invalid.status_code == 302
    with sqlite3.connect(python_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM az_questions WHERE question = ?",
            ("Neplatná otázka?",),
        ).fetchone()[0] == 0


def test_admin_can_delete_all_azkviz_questions(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    admin = app.test_client()
    player_a = app.test_client()
    player_b = app.test_client()
    _login(admin, app.config["ADMIN_EMAIL"])
    _login(player_a, "a@gymnzidlo.cz")
    _login(player_b, "b@gymnzidlo.cz")
    url = "/python/admin/azkviz/questions"

    response = admin.post(url, data={"action": "delete_all"})
    assert response.status_code == 302
    with sqlite3.connect(app.config["PYTHON_DATABASE"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM az_questions").fetchone()[0] == 0

    init_db(app.config["PYTHON_DATABASE"])
    with sqlite3.connect(app.config["PYTHON_DATABASE"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM az_questions").fetchone()[0] == 0

    assert admin.get(url).status_code == 200
    assert player_a.post("/python/azkviz/match").status_code == 200
    assert player_b.post("/python/azkviz/match").status_code == 409

def test_azkviz_question_export_import_merges_by_id(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    admin = app.test_client()
    _login(admin, app.config["ADMIN_EMAIL"])
    export_url = "/python/admin/azkviz/questions/export"
    import_url = "/python/admin/azkviz/questions/import"

    exported = admin.get(export_url)
    assert exported.status_code == 200
    payload = json.loads(exported.data)
    assert payload["area"] == "azkviz"
    assert payload["items"]
    first_id = payload["items"][0]["id"]
    payload["items"][0]["question"] = "Upravená exportovaná otázka?"
    existing_ids = {item["id"] for item in payload["items"]}
    added_id = max(existing_ids) + 100
    payload["items"].append({
        "id": added_id,
        "question": "Nová importovaná otázka?",
        "options": ["Ano", "Ne"],
        "answer": 0,
        "active": True,
    })
    response = admin.post(
        import_url,
        data={"file": (BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), "az.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with sqlite3.connect(tmp_path / "p.db") as conn:
        questions = conn.execute(
            "SELECT question FROM az_questions WHERE id IN (?, ?) ORDER BY id",
            (first_id, added_id),
        ).fetchall()
    assert questions == [
        ("Upravená exportovaná otázka?",),
        ("Nová importovaná otázka?",),
    ]

    payload["area"] = "python"
    wrong_area = admin.post(
        import_url,
        data={"file": (BytesIO(json.dumps(payload).encode("utf-8")), "python.json")},
        content_type="multipart/form-data",
    )
    assert wrong_area.status_code == 302
    with sqlite3.connect(tmp_path / "p.db") as conn:
        assert conn.execute(
            "SELECT question FROM az_questions WHERE id = ?", (first_id,)
        ).fetchone()[0] == "Upravená exportovaná otázka?"


def test_azkviz_import_accepts_utf8_bom(tmp_path: Path) -> None:
    app = _python_app(tmp_path)
    admin = app.test_client()
    _login(admin, app.config["ADMIN_EMAIL"])

    exported = admin.get("/python/admin/azkviz/questions/export")
    uploaded = b"\xef\xbb\xbf" + exported.data
    response = admin.post(
        "/python/admin/azkviz/questions/import",
        data={"file": (BytesIO(uploaded), "azkviz-bom.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Import otázek dokončen" in response.get_data(as_text=True)


def test_azkviz_import_adds_foreign_question_when_numeric_id_collides(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    source_app = _python_app(source_dir)
    target_app = _python_app(target_dir)
    source_admin = source_app.test_client()
    target_admin = target_app.test_client()
    for client in (source_admin, target_admin):
        _login(client, client.application.config["ADMIN_EMAIL"])

    original_target = target_admin.get(
        "/python/admin/azkviz/questions/export"
    )
    target_questions = json.loads(original_target.data)["items"]
    target_admin.post(
        "/python/admin/azkviz/questions",
        data={
            "action": "create",
            "question": "Místní otázka se shodným číselným ID?",
            "options": "A\nB",
            "answer": "0",
            "active": "1",
        },
    )
    with sqlite3.connect(target_dir / "p.db") as conn:
        target_collision = conn.execute(
            "SELECT id, question FROM az_questions "
            "WHERE question = ?",
            ("Místní otázka se shodným číselným ID?",),
        ).fetchone()

    source_admin.post(
        "/python/admin/azkviz/questions",
        data={
            "action": "create",
            "question": "Cizí otázka z jiné databáze?",
            "options": "První\nDruhá",
            "answer": "1",
            "active": "1",
        },
    )
    source_export = source_admin.get("/python/admin/azkviz/questions/export")
    payload = json.loads(source_export.data)
    foreign_item = next(
        item for item in payload["items"]
        if item["question"] == "Cizí otázka z jiné databáze?"
    )
    assert foreign_item["id"] == target_collision[0]
    upload = BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    for _ in range(2):
        response = target_admin.post(
            "/python/admin/azkviz/questions/import",
            data={"file": (BytesIO(upload.getvalue()), "foreign-azkviz.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Import otázek dokončen" in response.get_data(as_text=True)

    target_database = target_dir / "p.db"
    with sqlite3.connect(target_database) as conn:
        count = conn.execute("SELECT COUNT(*) FROM az_questions").fetchone()[0]
        target_question_after_import = conn.execute(
            "SELECT question FROM az_questions WHERE id = ?", (target_collision[0],)
        ).fetchone()[0]
        imported_count = conn.execute(
            "SELECT COUNT(*) FROM az_questions WHERE question = ?",
            ("Cizí otázka z jiné databáze?",),
        ).fetchone()[0]
    assert count == len(target_questions) + 2
    assert target_question_after_import == target_collision[1]
    assert imported_count == 1


def test_turtle_content_export_import_merges_independently(tmp_path: Path) -> None:
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "zelva.db"),
        "PYTHON_DATABASE": str(tmp_path / "python.db"),
    })
    admin = app.test_client()
    _login(admin, app.config["ADMIN_EMAIL"])
    created = admin.post("/api/custom-patterns", json={
        "id": "new_turtle_pattern",
        "name": "Původní vlastní vzor",
        "category": "Testovací",
        "commands": ["forward(10)"],
    })
    assert created.status_code == 201

    exported = admin.get("/admin/content/turtle/export")
    assert exported.status_code == 200
    payload = json.loads(exported.data)
    assert payload["area"] == "zelva"
    payload["custom_patterns"]["new_turtle_pattern"]["name"] = "Aktualizovaný vlastní vzor"
    payload["custom_patterns"]["another_turtle_pattern"] = {
        "name": "Nový vlastní vzor",
        "category": "Testovací",
        "commands": ["left(90)"],
        "initial_lines": 1,
        "initial_text": "",
        "hint": "",
    }
    payload["overrides"]["square"] = {
        "name": "Upravený čtverec",
        "commands": ["forward(20)"],
    }
    imported = admin.post(
        "/admin/content/turtle/import",
        data={"file": (BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), "zelva.json")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 302
    content = admin.get("/api/pattern-overrides").json
    assert content["custom_patterns"]["new_turtle_pattern"]["name"] == "Aktualizovaný vlastní vzor"
    assert content["custom_patterns"]["another_turtle_pattern"]["name"] == "Nový vlastní vzor"
    assert content["overrides"]["square"]["name"] == "Upravený čtverec"
    assert content["overrides"]["square"]["commands"] == ["forward(20)"]


def test_python_content_export_import_merges_assignments(tmp_path: Path) -> None:
    python_db = tmp_path / "p.db"
    app = _python_app(tmp_path)
    teacher = app.test_client()
    _login(teacher, app.config["ADMIN_EMAIL"])
    with sqlite3.connect(python_db) as conn:
        conn.execute(
            """
            INSERT INTO assignments (id, title, description, teacher_code, section)
            VALUES (42, 'Původní úloha', 'Původní popis', 'def solve():\\n    return 1', 'Základy')
            """
        )
        conn.execute(
            "INSERT INTO assignments (id, title, teacher_code, section) VALUES (43, 'Zachovaná úloha', '', 'Další')"
        )
        conn.commit()

    exported = teacher.get("/python/teacher/content/export")
    assert exported.status_code == 200
    payload = json.loads(exported.data)
    assert payload["area"] == "python"
    item = next(item for item in payload["items"] if item["id"] == 42)
    item["title"] = "Aktualizovaná úloha"
    payload["items"].append({
        "id": 100,
        "title": "Nová úloha",
        "description": "Přidaná importem",
        "teacher_code": "",
        "section": "Import",
        "display_order": 0,
        "section_order": 0,
        "help_text": "",
        "test_input_run": None,
        "test_input_submit": None,
        "test_call_run": "",
        "test_call_submit": "",
        "precopy_lines": 1,
        "active": True,
        "required": False,
    })
    imported = teacher.post(
        "/python/teacher/content/import",
        data={"file": (BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), "python.json")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 302
    with sqlite3.connect(python_db) as conn:
        rows = conn.execute(
            "SELECT id, title FROM assignments WHERE id IN (42, 43, 100) ORDER BY id"
        ).fetchall()
    assert rows == [
        (42, "Aktualizovaná úloha"),
        (43, "Zachovaná úloha"),
        (100, "Nová úloha"),
    ]


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


def test_ai_review_requires_configuration(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "AI_API_KEY": ""})
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"sub": "student-1", "email": "student@gymnzidlo.cz"}

    empty = client.post("/api/ai-review", json={"code": "  "})
    assert empty.status_code == 400

    too_long = client.post("/api/ai-review", json={"code": "forward(1)\n" * 1000})
    assert too_long.status_code == 400

    unconfigured = client.post("/api/ai-review", json={"code": "forward(100)"})
    assert unconfigured.status_code == 503


def test_ai_review_returns_model_feedback(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": " Pěkné řešení. "}}]}).encode("utf-8")

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        captured["auth"] = http_request.get_header("Authorization")
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("zelva.ai_review.urllib.request.urlopen", fake_urlopen)
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "AI_API_KEY": "secret",
        "AI_API_URL": "https://ai.example/v1/chat/completions",
        "AI_MODEL": "test-model",
    })
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"sub": "student-1", "email": "student@gymnzidlo.cz"}

    response = client.post(
        "/api/ai-review",
        json={"code": "forward(100)", "pattern_name": "Čtverec", "is_match": False, "match_percent": 40},
    )

    assert response.status_code == 200
    assert response.json == {"review": "Pěkné řešení."}
    assert captured["url"] == "https://ai.example/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["model"] == "test-model"
    assert "forward(100)" in captured["body"]["messages"][1]["content"]
    assert "40 % shoda" in captured["body"]["messages"][1]["content"]


def test_ai_review_handles_unreachable_service(tmp_path: Path, monkeypatch) -> None:
    def failing_urlopen(http_request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("zelva.ai_review.urllib.request.urlopen", failing_urlopen)
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "AI_API_KEY": "secret"})
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"sub": "student-1", "email": "student@gymnzidlo.cz"}

    response = client.post("/api/ai-review", json={"code": "forward(100)"})

    assert response.status_code == 502
    assert "error" in response.json


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


def _az_start_question(client, game_id: int, cell: int):
    response = client.post(
        f"/python/azkviz/game/{game_id}/question/start",
        json={"cell": cell},
    )
    assert response.status_code == 200
    return response.json


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
