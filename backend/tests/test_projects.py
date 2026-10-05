"""
3D Reel Studio — Projects Persistence Integration Tests
Phase 3: Project Session Persistence
"""

from fastapi.testclient import TestClient


def test_create_project_success(client: TestClient) -> None:
    """
    Verify creating a project returns HTTP 201 with project ID, draft status, and timestamps.
    """
    response = client.post("/api/v1/projects", json={"name": "Cyberpunk Superhero Reel"})
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "project" in data
    project = data["project"]
    assert project["name"] == "Cyberpunk Superhero Reel"
    assert project["status"] == "draft"
    assert project["id"].startswith("PROJ-")
    assert "created_at" in project
    assert "updated_at" in project


def test_create_project_validation_empty_name(client: TestClient) -> None:
    """
    Verify creating a project with empty or whitespace-only name fails validation with HTTP 422.
    """
    # Whitespace only
    response = client.post("/api/v1/projects", json={"name": "   "})
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"

    # Empty string
    res_empty = client.post("/api/v1/projects", json={"name": ""})
    assert res_empty.status_code == 422


def test_create_multiple_and_list_projects(client: TestClient) -> None:
    """
    Verify listing projects returns all created projects ordered newest first.
    """
    client.post("/api/v1/projects", json={"name": "Alpha Reel"})
    client.post("/api/v1/projects", json={"name": "Beta Reel"})
    client.post("/api/v1/projects", json={"name": "Gamma Reel"})

    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "projects" in data
    assert isinstance(data["projects"], list)
    assert data["count"] >= 3
    # Check that newest created project is at the top
    assert data["projects"][0]["name"] == "Gamma Reel"


def test_get_project_detail_success(client: TestClient) -> None:
    """
    Verify retrieving complete project state by ID.
    """
    create_res = client.post("/api/v1/projects", json={"name": "Detailed Studio Project"})
    assert create_res.status_code == 201
    project_id = create_res.json()["project"]["id"]

    get_res = client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["success"] is True
    project = data["project"]
    assert project["id"] == project_id
    assert project["name"] == "Detailed Studio Project"
    assert "media_files" in project
    assert "transformation_jobs" in project
    assert isinstance(project["media_files"], list)
    assert isinstance(project["transformation_jobs"], list)


def test_get_nonexistent_project_404(client: TestClient) -> None:
    """
    Verify querying a non-existent project returns structured 404 error.
    """
    response = client.get("/api/v1/projects/PROJ-DOESNOTEXIST99")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"
    assert "not found" in data["error"]["message"].lower()


def test_patch_project_success(client: TestClient) -> None:
    """
    Verify updating project name and status via PATCH.
    """
    create_res = client.post("/api/v1/projects", json={"name": "Initial Draft Name"})
    project_id = create_res.json()["project"]["id"]

    # Update name and status
    patch_res = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Finalized Comic Reel", "status": "uploaded"}
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["success"] is True
    assert data["project"]["name"] == "Finalized Comic Reel"
    assert data["project"]["status"] == "uploaded"

    # Verify retrieval reflects updates
    get_res = client.get(f"/api/v1/projects/{project_id}")
    assert get_res.json()["project"]["name"] == "Finalized Comic Reel"
    assert get_res.json()["project"]["status"] == "uploaded"


def test_patch_project_invalid_status(client: TestClient) -> None:
    """
    Verify updating project with an invalid status fails with HTTP 422.
    """
    create_res = client.post("/api/v1/projects", json={"name": "Status Test Project"})
    project_id = create_res.json()["project"]["id"]

    patch_res = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"status": "invalid_random_status"}
    )
    assert patch_res.status_code == 422
    data = patch_res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"
