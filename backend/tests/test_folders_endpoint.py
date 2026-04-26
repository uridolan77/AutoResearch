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


def test_ingest_missing_path_or_url_returns_422(db_factory) -> None:
    Sm = db_factory
    for client in _client(Sm):
        r = client.post("/folders/ingest", json={})
    assert r.status_code == 422


def test_targets_unknown_folder_returns_404(db_factory) -> None:
    Sm = db_factory
    for client in _client(Sm):
        r = client.get("/folders/00000000-0000-0000-0000-000000000000/targets")
    assert r.status_code == 404

