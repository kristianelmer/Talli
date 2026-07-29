from fastapi import Query
from fastapi.testclient import TestClient

from talli_backend.main import ApiProblem, REQUEST_ID_PATTERN, app, create_app
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
    assert schema["components"]["schemas"]["SystemBoundaryStatus"]["properties"]["status"][
        "const"
    ] == "AVAILABLE"


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


def _assert_problem(response, *, status: int, code: str, request_id: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["status"] == status
    assert response.json()["code"] == code
    assert response.json()["requestId"] == request_id


def test_framework_failures_are_normalized_as_correlated_problem_details() -> None:
    test_app = create_app()

    @test_app.get("/validation-probe")
    async def validation_probe(required: int = Query()) -> dict[str, int]:
        return {"required": required}

    client = TestClient(test_app)
    for method, path, status, code, request_id in [
        ("GET", "/missing", 404, "RESOURCE_NOT_FOUND", "request-404"),
        (
            "POST",
            "/api/v1/system-boundary/tracer",
            405,
            "METHOD_NOT_ALLOWED",
            "request-405",
        ),
        ("GET", "/validation-probe", 422, "REQUEST_VALIDATION_FAILED", "request-422"),
    ]:
        response = client.request(method, path, headers={"X-Request-ID": request_id})
        _assert_problem(response, status=status, code=code, request_id=request_id)


def test_declared_and_unexpected_failures_are_safe_correlated_problem_details() -> None:
    test_app = create_app()

    @test_app.get("/declared-failure")
    async def declared_failure() -> None:
        raise ApiProblem(
            status=503,
            code="BOUNDARY_UNAVAILABLE",
            title="Backend boundary unavailable",
            detail="The backend boundary is temporarily unavailable.",
        )

    @test_app.get("/unexpected-failure")
    async def unexpected_failure() -> None:
        raise RuntimeError("database password=super-secret")

    client = TestClient(test_app, raise_server_exceptions=False)
    declared = client.get(
        "/declared-failure",
        headers={"X-Request-ID": "request-declared"},
    )
    unexpected = client.get(
        "/unexpected-failure",
        headers={"X-Request-ID": "request-unexpected"},
    )

    _assert_problem(
        declared,
        status=503,
        code="BOUNDARY_UNAVAILABLE",
        request_id="request-declared",
    )
    _assert_problem(
        unexpected,
        status=500,
        code="INTERNAL_SERVER_ERROR",
        request_id="request-unexpected",
    )
    assert declared.json()["detail"] == "The backend boundary is temporarily unavailable."
    assert unexpected.json()["detail"] == "An unexpected error occurred."
    assert "super-secret" not in unexpected.text
