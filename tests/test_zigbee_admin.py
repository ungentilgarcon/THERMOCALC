from pathlib import Path

from app.models.schemas import AdminState
from app.services import admin_state as admin_state_service


def test_admin_state_loads_existing_file_with_new_zigbee_defaults(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    admin_file.write_text(
        '{"occupants": [], "thermostats": [], "schedule": {"enabled": false, "day_of_month": 1, "hour": 6, "minute": 0, "output_dir": "generated_reports", "last_generated_month": null}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    state = admin_state_service.load_admin_state()

    assert isinstance(state, AdminState)
    assert state.controllers == []
    assert state.zigbee_devices == []
    assert state.zigbee_pairings == []


def test_controller_device_pairing_lifecycle(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.ensure_admin_state_file()
    admin_state_service.add_or_update_controller(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="mock",
        endpoint_url="",
        notes="test",
        enabled=True,
    )
    admin_state_service.add_or_update_zigbee_device(
        device_id="sensor-1",
        controller_id="bridge-a",
        role="detector",
        friendly_name="Capteur salon",
        model="SNZB-02",
        ieee_address="0xabc",
        owner_name="Alice",
        zone_label="Salon",
        enabled=True,
    )
    admin_state_service.add_or_update_zigbee_device(
        device_id="relay-1",
        controller_id="bridge-a",
        role="receiver",
        friendly_name="Relais salon",
        model="MINI-L2",
        ieee_address="0xdef",
        owner_name="",
        zone_label="Salon",
        enabled=True,
    )
    admin_state_service.add_or_update_zigbee_pairing(
        link_id="pair-1",
        controller_id="bridge-a",
        source_device_id="sensor-1",
        target_device_id="relay-1",
        relation_type="detector-to-receiver",
        notes="Auto",
        enabled=True,
    )

    state = admin_state_service.load_admin_state()
    assert len(state.controllers) == 1
    assert len(state.zigbee_devices) == 2
    assert len(state.zigbee_pairings) == 1

    admin_state_service.remove_controller("bridge-a")
    state = admin_state_service.load_admin_state()
    assert state.controllers == []
    assert state.zigbee_devices == []
    assert state.zigbee_pairings == []