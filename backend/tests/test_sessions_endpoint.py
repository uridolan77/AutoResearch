from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.conftest import make_evaluator


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


def test_create_session_requires_target_and_evaluator(db_factory) -> None:
    Sm = db_factory
    for client in _client(Sm):
        r = client.post("/sessions", json={"folder_path": "/tmp/repo"})
    assert r.status_code == 422


def test_start_session_enqueues_loop(db_factory, tmp_path) -> None:
    Sm = db_factory
    db = Sm()
    ev = make_evaluator(db)
    db.close()

    with (
        patch("app.api.routes.sessions.GitService") as git_cls,
        patch("app.api.routes.sessions.celery_app.send_task") as send_task,
    ):
        git_cls.return_value.ensure_repo.return_value = None
        git_cls.return_value.create_session_branch.return_value = ("session-x", tmp_path)

        for client in _client(Sm):
            r = client.post(
                "/sessions",
                json={
                    "name": "s1",
                    "folder_path": str(tmp_path),
                    "target_file": "draft.md",
                    "program_md": "x",
                    "evaluator_id": ev.id,
                },
            )
            assert r.status_code == 201
            sid = r.json()["id"]

            s = client.post(f"/sessions/{sid}/start")
            assert s.status_code == 202

    send_task.assert_called_with("autoresearch.loop", args=[sid])


def test_patch_program_updates_program_md(db_factory) -> None:
    Sm = db_factory
    from tests.conftest import make_session

    db = Sm()
    s = make_session(db)
    db.close()

    for client in _client(Sm):
        r = client.patch(f"/sessions/{s.id}/program", json={"program_md": "new"})
    assert r.status_code == 200
    assert r.json()["program_md"] == "new"

