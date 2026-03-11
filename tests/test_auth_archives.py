from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import AllocationInput, ArchiveAllocationSnapshot, ArchiveRecord, ThermostatSample
from app.services import auth
from app.services.archives import _matches_month_range, _matches_owner
from app.api import routes


def test_admin_login_required(monkeypatch) -> None:
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "secret")

    with TestClient(app) as client:
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"

        failed = client.post("/admin/login", data={"username": "admin", "password": "wrong"})
        assert failed.status_code == 401

        success = client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert success.status_code == 303
        assert success.headers["location"].startswith("/admin")


def test_admin_page_renders_after_login(monkeypatch) -> None:
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "secret")

    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.get("/admin")

    assert response.status_code == 200
    assert "Administration" in response.text
    assert "Choix des poids chauffage / ECS" in response.text


def test_archive_filters_match_expected_owner_and_month() -> None:
    record = ArchiveRecord(
        filename="thermocalc-2026-03.pdf",
        display_name="Mars 2026",
        month_label="2026-03",
        generated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        owners=[ArchiveAllocationSnapshot(owner_name="Alice", share_percent=55.0, total_effort_score=12.0)],
    )

    assert _matches_owner(record, "Alice") is True
    assert _matches_owner(record, "Benoit") is False
    assert _matches_month_range(record, "2026-02", "2026-03") is True
    assert _matches_month_range(record, "2026-04", None) is False


def test_dashboard_shows_payload_source_indicator(monkeypatch) -> None:
    payload = AllocationInput(
        month_label="2026-03",
        samples=[
            ThermostatSample(
                trv_id="trv26-salon-1",
                zone_label="Salon",
                owner_name="Alice",
                surface_m2=25,
                target_temperature_c=21,
                current_temperature_c=19,
                valve_open_percent=60,
                captured_at="2026-03-01T08:15:00Z",
            )
        ],
    )
    source = routes.PayloadSource(
        code="mqtt",
        label="MQTT temps reel",
        detail="Calcul base sur les dernieres mesures TRV26 remontees par Zigbee2MQTT.",
        tone="live",
    )
    monkeypatch.setattr(routes, "load_payload_with_source", lambda: (payload, source))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "MQTT temps reel" in response.text
    assert "dernieres mesures TRV26" in response.text


def test_ecs_page_requires_admin_login() -> None:
    with TestClient(app) as client:
        response = client.get("/ecs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_test_calculations_page_requires_admin_login() -> None:
    with TestClient(app) as client:
        response = client.get("/test-calculs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_test_calculations_page_runs_manual_scenario(monkeypatch) -> None:
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "secret")

    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.post(
            "/test-calculs",
            data={
                "scenario": "manual",
                "month_label": "Scenario validation",
                "trv_id": ["trv-a", "trv-b"],
                "owner_name": ["Alice", "Benoit"],
                "zone_label": ["Salon", "Bureau"],
                "surface_m2": ["20", "12"],
                "target_temperature_c": ["21", "20"],
                "current_temperature_c": ["19", "19.5"],
                "valve_open_percent": ["60", "30"],
                "running_state": ["heat", "idle"],
                "duty_cycle_percent": ["70", "15"],
            },
        )

    assert response.status_code == 200
    assert "Scenario calcule en mode test" in response.text
    assert "Scenario validation" in response.text
    assert "Alice" in response.text
    assert "Benoit" in response.text


def test_test_consumption_page_requires_admin_login() -> None:
    with TestClient(app) as client:
        response = client.get("/test-consommation", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_heating_control_page_requires_admin_login() -> None:
    with TestClient(app) as client:
        response = client.get("/pilotage-chauffage", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_heating_control_page_renders_after_login(monkeypatch) -> None:
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "secret")

    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.get("/pilotage-chauffage")

    assert response.status_code == 200
    assert "Pilotage chauffage" in response.text
    assert "Override temporaire" in response.text
    assert "Profils rapides" in response.text
    assert "HORS-GEL" in response.text


def test_test_consumption_page_runs_manual_scenario(monkeypatch) -> None:
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "secret")

    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.post(
            "/test-consommation",
            data={
                "scenario": "manual",
                "month_label": "Scenario conso",
                "trv_id": ["trv-a", "trv-b"],
                "owner_name": ["Alice", "Benoit"],
                "zone_label": ["Salon", "Bureau"],
                "surface_m2": ["20", "12"],
                "target_temperature_c": ["21", "20"],
                "current_temperature_c": ["19", "19.5"],
                "valve_open_percent": ["60", "30"],
                "running_state": ["heat", "idle"],
                "duty_cycle_percent": ["70", "15"],
                "ecs_owner_name": ["Alice", "Benoit"],
                "ecs_delta_m3": ["1.5", "2.5"],
                "total_bill_amount": "200",
                "bill_amount_label": "EUR",
            },
        )

    assert response.status_code == 200
    assert "Scenario de consommation calcule en mode test" in response.text
    assert "Scenario conso" in response.text
    assert "Montant total combustible" in response.text
    assert "Part finale" in response.text
    assert "Allocation de test" in response.text
    assert "Alice" in response.text
    assert "Benoit" in response.text