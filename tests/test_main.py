from pathlib import Path

from zelva.app import create_app


def test_home_page_is_available() -> None:
    app = create_app()
    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200


def test_health_api_is_available() -> None:
    app = create_app()
    client = app.test_client()
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "service": "zelva-web"}


def test_progress_api_persists_solution(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    client = app.test_client()

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


def test_progress_is_isolated_per_browser_client(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    client_a = app.test_client()
    client_b = app.test_client()

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
