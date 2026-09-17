def test_create_and_list_project(client):
    resp = client.post("/api/projects", json={"name": "My Gaming Video", "content_type": "gaming"})
    assert resp.status_code == 201
    project = resp.json()
    assert project["name"] == "My Gaming Video"
    assert project["content_type"] == "gaming"
    assert project["status"] == "created"

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert any(p["id"] == project["id"] for p in projects)


def test_get_missing_project_returns_friendly_error(client):
    resp = client.get("/api/projects/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert "does not exist" not in body["error"].lower() or "doesn't exist" in body["error"].lower()


def test_empty_name_rejected(client):
    resp = client.post("/api/projects", json={"name": "   ", "content_type": "gaming"})
    assert resp.status_code == 400


def test_delete_project(client):
    resp = client.post("/api/projects", json={"name": "Temp", "content_type": "comedy"})
    project_id = resp.json()["id"]
    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 404
