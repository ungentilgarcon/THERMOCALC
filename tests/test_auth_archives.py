from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ArchiveAllocationSnapshot, ArchiveRecord
from app.services import auth
from app.services.archives import _matches_month_range, _matches_owner


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