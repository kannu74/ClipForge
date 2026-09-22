def test_health(client):
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_hardware_report_shape(client):
    resp = client.get("/api/system/hardware")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "cpu_cores_logical",
        "ram_total_mb",
        "gpu",
        "ffmpeg_available",
        "ollama_reachable",
        "recommended_quality_mode",
    ):
        assert key in body
    assert body["cpu_cores_logical"] >= 1
