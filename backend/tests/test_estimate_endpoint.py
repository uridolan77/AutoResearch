from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from app.main import app

    return TestClient(app)


def test_estimate_requires_folder_and_target() -> None:
    client = _client()
    r = client.post("/sessions/estimate", json={})
    assert r.status_code == 422


def test_estimate_returns_numeric_fields(tmp_path) -> None:
    f = tmp_path / "draft.md"
    f.write_text("hello\n", encoding="utf-8")
    client = _client()
    r = client.post(
        "/sessions/estimate",
        json={"program_md": "x", "folder_path": str(tmp_path), "target_file": "draft.md"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimated_input_tokens"] > 0
    assert body["estimated_max_output_tokens"] > 0
    assert body["estimated_total_tokens"] == body["estimated_input_tokens"] + body["estimated_max_output_tokens"]

