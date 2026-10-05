"""
3D Reel Studio — Health & Root Endpoint Tests
Phase 2: FastAPI Backend Foundation
"""

from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient) -> None:
    """
    Verify root endpoint returns HTTP 200, success=True, and docs link.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "3D Reel Studio API is running" in data["message"]
    assert data["docs"] == "/docs"


def test_health_endpoint(client: TestClient) -> None:
    """
    Verify GET /api/v1/health returns HTTP 200 and standard health payload.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "healthy"
    assert data["service"] == "3D Reel Studio API"
    assert data["version"] == "1.0.0"


def test_readiness_endpoint(client: TestClient) -> None:
    """
    Verify GET /api/v1/health/ready returns HTTP 200 and readiness status.
    """
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "ready"
    assert data["service"] == "3D Reel Studio API"
    assert data["version"] == "1.0.0"


def test_docs_and_openapi(client: TestClient) -> None:
    """
    Verify Swagger UI (/docs) and OpenAPI schema (/openapi.json) are accessible.
    """
    docs_res = client.get("/docs")
    assert docs_res.status_code == 200
    assert "swagger-ui" in docs_res.text.lower() or "html" in docs_res.text.lower()

    openapi_res = client.get("/openapi.json")
    assert openapi_res.status_code == 200
    openapi_data = openapi_res.json()
    assert openapi_data["info"]["title"] == "3D Reel Studio API"
    assert openapi_data["info"]["version"] == "1.0.0"
