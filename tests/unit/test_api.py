from fastapi.testclient import TestClient
from api.app import create_app
from api.auth import verify_api_key

app = create_app()
app.dependency_overrides[verify_api_key] = lambda: None
client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

import uuid

# Define a single test ID to be used across multiple API tests
shared_test_id = f"TEST-INC-{uuid.uuid4().hex[:8]}"

def test_trigger_incident():
    payload = {
        "alert_id": shared_test_id,
        "service": "test-service",
        "severity": "high",
        "description": "High latency on the checkout endpoint, spike to 500ms"
    }
    # Test triggering works and returns 202
    response = client.post("/incidents/trigger", json=payload)
    assert response.status_code == 202
    assert response.json()["incident_id"] == shared_test_id
    assert response.json()["status"] == "pending"

def test_get_all_incidents():
    response = client.get("/incidents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_specific_incident():
    response = client.get(f"/incidents/{shared_test_id}")
    assert response.status_code == 200
    assert response.json()["incident_id"] == shared_test_id

def test_get_nonexistent_report():
    response = client.get("/incidents/FAKE-999/report")
    # Our API returns 404 if the report isn't generated yet or incident doesn't exist
    assert response.status_code == 404
