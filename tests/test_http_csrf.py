"""Same-origin POST guard: Origin or Referer is required."""

from __future__ import annotations


def test_post_missing_origin_and_referer_forbidden(client) -> None:
    response = client.post(
        "/api/parse-workflow",
        json={"workflow_text": "1. Wait for 1 second"},
        environ_base={"HTTP_ORIGIN": "", "HTTP_REFERER": ""},
    )
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["success"] is False
    assert "Origin" in payload["error"] or "Referer" in payload["error"]


def test_post_cross_origin_is_forbidden(client) -> None:
    response = client.post(
        "/api/parse-workflow",
        json={"workflow_text": "1. Wait for 1 second"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert "Cross-origin" in response.get_json()["error"]


def test_post_cross_origin_referer_is_forbidden(client) -> None:
    response = client.post(
        "/api/parse-workflow",
        json={"workflow_text": "1. Wait for 1 second"},
        environ_base={"HTTP_ORIGIN": "", "HTTP_REFERER": "https://evil.example/page"},
    )
    assert response.status_code == 403
    assert "Referer" in response.get_json()["error"]


def test_post_matching_referer_allowed_without_origin(client) -> None:
    response = client.post(
        "/api/parse-workflow",
        json={"workflow_text": "1. Wait for 1 second"},
        environ_base={"HTTP_ORIGIN": "", "HTTP_REFERER": "http://localhost/"},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True
