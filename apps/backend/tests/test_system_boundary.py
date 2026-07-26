from fastapi.testclient import TestClient

from talli_backend.main import REQUEST_ID_PATTERN, app
from talli_backend.openapi import serialize_openapi


def test_tracer_operation_reports_backend_availability() -> None:
    response = TestClient(app).get(
        "/api/v1/system-boundary/tracer",
        headers={"X-Request-ID": "test-request-134"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-134"
    assert response.json() == {
        "apiVersion": "v1",
        "service": "talli-backend",
        "status": "AVAILABLE",
    }


def test_committed_openapi_operation_is_explicit_and_problem_shaped() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/system-boundary/tracer"]["get"]

    assert schema["openapi"].startswith("3.1.")
    assert schema["info"]["version"] == "1.0.0"
    assert operation["operationId"] == "systemBoundaryGetTracerStatus"
    assert operation["responses"]["503"]["content"]["application/problem+json"]
    assert "application/json" not in operation["responses"]["503"]["content"]


def test_served_openapi_bytes_match_the_deterministic_generator() -> None:
    response = TestClient(app).get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.text == serialize_openapi(app)
    assert response.headers["cache-control"] == "no-store"


def test_untrusted_request_ids_are_not_reflected() -> None:
    response = TestClient(app).get(
        "/api/v1/system-boundary/tracer",
        headers={"X-Request-ID": "invalid request id secret"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id secret"
    assert REQUEST_ID_PATTERN.fullmatch(response.headers["X-Request-ID"])
