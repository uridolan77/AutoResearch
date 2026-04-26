from __future__ import annotations

from fastapi.testclient import TestClient


def _client(Sm):
    from app.core.db import get_db
    from app.main import app

    def _override():
        s = Sm()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_create_and_get_evaluator(db_factory) -> None:
    Sm = db_factory
    for client in _client(Sm):
        r = client.post(
            "/evaluators",
            json={
                "name": "e1",
                "type": "command",
                "config": {"image": "alpine", "command": "true", "metric_regex": "(\\d+)"},
                "metric_name": "m",
                "direction": "maximize",
                "timeout_s": 60,
                "baseline_required": True,
                "network_mode": "none",
            },
        )
        assert r.status_code == 201
        eid = r.json()["id"]

        g = client.get(f"/evaluators/{eid}")
        assert g.status_code == 200
        assert g.json()["name"] == "e1"


def test_delete_in_use_evaluator_returns_409(db_factory) -> None:
    Sm = db_factory
    from tests.conftest import make_session

    db = Sm()
    s = make_session(db)
    db.close()

    for client in _client(Sm):
        r = client.delete(f"/evaluators/{s.evaluator_id}")
    assert r.status_code == 409

