"""
3D Reel Studio — Error Handling and CORS Tests
Phase 2: FastAPI Backend Foundation
"""

from fastapi.testclient import TestClient


def test_not_found_error_structure(client: TestClient) -> None:
    """
    Verify 404 on non-existent route returns the standard JSON error payload.
    """
    response = client.get("/api/v1/non-existent-route-xyz")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]


def test_cors_headers_on_request(client: TestClient) -> None:
    """
    Verify CORS headers are returned properly for cross-origin requests.
    """
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:8080"}
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] in ["*", "http://localhost:8080"]


def test_cors_preflight_options(client: TestClient) -> None:
    """
    Verify CORS preflight OPTIONS request succeeds.
    """
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert "access-control-allow-methods" in response.headers
