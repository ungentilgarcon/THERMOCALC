from datetime import datetime, timedelta, timezone
from app.models.schemas import AdminState, ZigbeeController, ZigbeeEndpoint
from app.services import admin_state as admin_state_service
from app.services import runtime_measurements as runtime_measurements_service
from app.services.zigbee import build_controller_topology
from app.services import zigbee2mqtt as zigbee2mqtt_service
from app.services.zigbee2mqtt import build_broker_config, map_bridge_devices, prepare_new_thermostat_pairing, should_refresh_controller
from app.services.zigbee2mqtt import publish_thermostat_setpoint


def test_build_broker_config_parses_mqtt_url() -> None:
    controller = ZigbeeController(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1884",
        mqtt_username="user",
        mqtt_password="pass",
        base_topic="custom-z2m",
    )

    config = build_broker_config(controller)

    assert config.host == "broker.local"
    assert config.port == 1884
    assert config.username == "user"
    assert config.base_topic == "custom-z2m"


def test_map_bridge_devices_classifies_roles() -> None:
    controller = ZigbeeController(controller_id="bridge-a", label="Bridge A", provider_type="zigbee2mqtt")
    payload = [
        {
            "friendly_name": "trv26-salon-1",
            "ieee_address": "0x1",
            "model_id": "TRV26",
            "definition": {"exposes": [{"name": "occupied_heating_setpoint"}, {"name": "local_temperature"}]},
        },
        {
            "friendly_name": "capteur-salon",
            "ieee_address": "0x2",
            "model_id": "SNZB-02",
            "definition": {"exposes": [{"name": "temperature"}, {"name": "humidity"}]},
        },
        {
            "friendly_name": "relais-chaudiere",
            "ieee_address": "0x3",
            "model_id": "MINI-L2",
            "definition": {"exposes": [{"name": "state"}]},
        },
    ]

    devices = map_bridge_devices(controller, payload)

    assert [item.role for item in devices] == ["thermostat", "detector", "receiver"]


def test_sync_thermostat_devices_updates_assignments(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    state = AdminState()
    admin_state_service.save_admin_state(state)
    admin_state_service.add_or_update_zigbee_device(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        role="thermostat",
        friendly_name="TRV salon",
        model="TRV26",
        ieee_address="0x111",
        owner_name="Alice",
        zone_label="Salon",
        surface_m2=24.0,
        enabled=True,
    )

    loaded = admin_state_service.load_admin_state()

    assert any(item.trv_id == "trv26-salon-1" and item.surface_m2 == 24.0 for item in loaded.thermostats)


def test_build_controller_topology_groups_nodes_and_links() -> None:
    devices = [
        ZigbeeEndpoint(device_id="sensor-1", controller_id="bridge-a", role="detector", friendly_name="Capteur", model="", ieee_address=""),
        ZigbeeEndpoint(device_id="trv-1", controller_id="bridge-a", role="thermostat", friendly_name="TRV", model="", ieee_address=""),
        ZigbeeEndpoint(device_id="relay-1", controller_id="bridge-a", role="receiver", friendly_name="Relais", model="", ieee_address=""),
    ]
    pairings = [
        type("Pairing", (), {"relation_type": "detector-to-thermostat", "source_device_id": "sensor-1", "target_device_id": "trv-1", "notes": "auto"})(),
        type("Pairing", (), {"relation_type": "thermostat-to-receiver", "source_device_id": "trv-1", "target_device_id": "relay-1", "notes": "auto"})(),
    ]

    topology = build_controller_topology(devices, pairings)

    assert len(topology["detectors"]) == 1
    assert len(topology["thermostats"]) == 1
    assert len(topology["receivers"]) == 1
    assert len(topology["links"]) == 2
    assert "<svg" in topology["svg"]


def test_should_refresh_controller_respects_interval() -> None:
    controller = ZigbeeController(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        auto_discovery_enabled=True,
        discovery_interval_minutes=15,
        last_discovery_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
    )

    assert should_refresh_controller(controller, datetime(2026, 3, 10, 10, 16, tzinfo=timezone.utc)) is True
    assert should_refresh_controller(controller, datetime(2026, 3, 10, 10, 10, tzinfo=timezone.utc)) is False


def test_refresh_controller_inventory_preserves_business_metadata(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_or_update_controller(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
        auto_discovery_enabled=True,
        discovery_interval_minutes=30,
        enabled=True,
    )
    admin_state_service.add_or_update_zigbee_device(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        role="thermostat",
        friendly_name="TRV Salon",
        model="TRV26",
        ieee_address="0x1",
        owner_name="Alice",
        zone_label="Salon",
        surface_m2=25.0,
        enabled=True,
    )

    discovered = [
        ZigbeeEndpoint(
            device_id="trv26-salon-1",
            controller_id="bridge-a",
            role="thermostat",
            friendly_name="TRV Salon Renomme",
            model="TRV26",
            ieee_address="0x1",
            owner_name="",
            zone_label="",
            surface_m2=None,
            enabled=True,
        )
    ]
    monkeypatch.setattr(zigbee2mqtt_service, "discover_devices", lambda controller: discovered)

    state = admin_state_service.load_admin_state()
    controller = state.controllers[0]
    count, status = zigbee2mqtt_service.refresh_controller_inventory(controller)
    refreshed = admin_state_service.load_admin_state()
    refreshed_device = refreshed.zigbee_devices[0]

    assert count == 1
    assert status.startswith("Discovery OK")
    assert refreshed_device.owner_name == "Alice"
    assert refreshed_device.zone_label == "Salon"
    assert refreshed_device.surface_m2 == 25.0


def test_prepare_new_thermostat_pairing_creates_placeholder_assignment(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)
    admin_state_service.save_admin_state(AdminState())
    controller = ZigbeeController(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
    )
    monkeypatch.setattr(zigbee2mqtt_service, "set_permit_join", lambda controller, seconds: None)

    message = prepare_new_thermostat_pairing(
        controller=controller,
        duration_seconds=90,
        expected_device_id="trv26-salon-2",
        friendly_name="TRV Salon 2",
        owner_name="Alice",
        zone_label="Salon 2",
        surface_m2=18.0,
    )
    state = admin_state_service.load_admin_state()

    assert "pre-affectee" in message
    assert any(item.device_id == "trv26-salon-2" for item in state.zigbee_devices)
    assert any(item.trv_id == "trv26-salon-2" and item.surface_m2 == 18.0 for item in state.thermostats)


def test_test_broker_connectivity_reports_failure_without_broker(monkeypatch) -> None:
    controller = ZigbeeController(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
    )

    class FakeClient:
        def connect(self, host, port, keepalive=15):
            raise RuntimeError("broker down")

        def loop_start(self):
            return None

        def loop_stop(self):
            return None

        def disconnect(self):
            return None

    monkeypatch.setattr(zigbee2mqtt_service, "_build_client", lambda broker: FakeClient())

    success, message = zigbee2mqtt_service.test_broker_connectivity(controller)

    assert success is False
    assert "broker down" in message


def test_extract_measurement_reads_trv26_payload() -> None:
    measurement = runtime_measurements_service.extract_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={
            "occupied_heating_setpoint": 20.5,
            "local_temperature": 19.1,
            "pi_heating_demand": 47,
            "battery": 62,
            "running_state": "heat",
            "preset": "manual",
            "error_status": 0,
            "last_seen": "2026-03-10T08:15:00Z",
        },
    )

    assert measurement is not None
    assert measurement["trv_id"] == "trv26-salon-1"
    assert measurement["controller_id"] == "bridge-a"
    assert measurement["valve_open_percent"] == 47
    assert measurement["battery_percent"] == 62
    assert measurement["running_state"] == "heat"
    assert measurement["preset"] == "manual"
    assert measurement["error_status"] == 0


def test_publish_thermostat_setpoint_uses_device_set_topic(monkeypatch) -> None:
    controller = ZigbeeController(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
        base_topic="custom-z2m",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def connect(self, host, port, keepalive=30):
            captured["connect"] = (host, port, keepalive)

        def loop_start(self):
            return None

        def publish(self, topic, payload, qos=0):
            captured["topic"] = topic
            captured["payload"] = payload
            captured["qos"] = qos

        def loop_stop(self):
            return None

        def disconnect(self):
            return None

    monkeypatch.setattr(zigbee2mqtt_service, "_build_client", lambda broker: FakeClient())

    publish_thermostat_setpoint(controller, "trv26-salon-1", 21.5)

    assert captured["connect"] == ("broker.local", 1883, 30)
    assert captured["topic"] == "custom-z2m/trv26-salon-1/set"
    assert '"occupied_heating_setpoint": 21.5' in str(captured["payload"])
    assert '"preset": "manual"' in str(captured["payload"])


def test_compute_duty_cycle_percent_uses_recent_history(monkeypatch) -> None:
    monkeypatch.setattr(runtime_measurements_service, "TRV26_DUTY_CYCLE_WINDOW_HOURS", 24)
    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    history = [
        {"captured_at": "2026-03-10T08:00:00+00:00", "running_state": "heat", "valve_open_percent": 60},
        {"captured_at": "2026-03-10T10:00:00+00:00", "running_state": "idle", "valve_open_percent": 0},
        {"captured_at": "2026-03-10T11:00:00+00:00", "running_state": "heat", "valve_open_percent": 50},
    ]

    duty_cycle = runtime_measurements_service.compute_duty_cycle_percent(history, now=now)

    assert duty_cycle == 75.0


def test_build_realtime_payload_uses_recent_snapshots(tmp_path, monkeypatch) -> None:
    runtime_file = tmp_path / "runtime_measurements.json"
    monkeypatch.setattr(runtime_measurements_service, "RUNTIME_MEASUREMENTS_PATH", runtime_file)
    monkeypatch.setattr(runtime_measurements_service, "REALTIME_MEASUREMENT_MAX_AGE_MINUTES", 180)

    state = AdminState.model_validate(
        {
            "thermostats": [
                {
                    "trv_id": "trv26-salon-1",
                    "zone_label": "Salon",
                    "owner_name": "Alice",
                    "surface_m2": 25.0,
                }
            ]
        }
    )

    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={
            "occupied_heating_setpoint": 21,
            "local_temperature": 19,
            "pi_heating_demand": 60,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        },
    )

    payload = runtime_measurements_service.build_realtime_payload(state)

    assert payload is not None
    assert payload.samples[0].owner_name == "Alice"
    assert payload.samples[0].valve_open_percent == 60


def test_build_realtime_payload_ignores_stale_snapshots(tmp_path, monkeypatch) -> None:
    runtime_file = tmp_path / "runtime_measurements.json"
    monkeypatch.setattr(runtime_measurements_service, "RUNTIME_MEASUREMENTS_PATH", runtime_file)
    monkeypatch.setattr(runtime_measurements_service, "REALTIME_MEASUREMENT_MAX_AGE_MINUTES", 30)
    runtime_measurements_service._RUNTIME_SNAPSHOTS.clear()

    state = AdminState.model_validate(
        {
            "thermostats": [
                {
                    "trv_id": "trv26-salon-1",
                    "zone_label": "Salon",
                    "owner_name": "Alice",
                    "surface_m2": 25.0,
                }
            ]
        }
    )

    runtime_file.write_text(
        '{"measurements":[{"trv_id":"trv26-salon-1","controller_id":"bridge-a","target_temperature_c":21,"current_temperature_c":19,"valve_open_percent":60,"captured_at":"2026-03-10T08:15:00+00:00","raw_payload":{}}]}',
        encoding="utf-8",
    )

    assert runtime_measurements_service.build_realtime_payload(state) is None


def test_load_sample_payload_prefers_realtime_measurements(tmp_path, monkeypatch) -> None:
    from app.api import routes

    sample_file = tmp_path / "sample_data.json"
    runtime_file = tmp_path / "runtime_measurements.json"
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(routes, "SAMPLE_DATA_PATH", sample_file)
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)
    monkeypatch.setattr(runtime_measurements_service, "RUNTIME_MEASUREMENTS_PATH", runtime_file)
    monkeypatch.setattr(runtime_measurements_service, "REALTIME_MEASUREMENT_MAX_AGE_MINUTES", 180)
    runtime_measurements_service._RUNTIME_SNAPSHOTS.clear()

    sample_file.write_text(
        '{"month_label":"2026-03","samples":[{"trv_id":"trv26-salon-1","zone_label":"Salon","owner_name":"Alice","surface_m2":25.0,"target_temperature_c":19.0,"current_temperature_c":19.0,"valve_open_percent":0.0,"captured_at":"2026-03-01T08:00:00+00:00"}]}',
        encoding="utf-8",
    )
    admin_state_service.save_admin_state(
        AdminState.model_validate(
            {
                "thermostats": [
                    {
                        "trv_id": "trv26-salon-1",
                        "zone_label": "Salon",
                        "owner_name": "Alice",
                        "surface_m2": 25.0,
                    }
                ]
            }
        )
    )
    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={
            "occupied_heating_setpoint": 21,
            "local_temperature": 18,
            "pi_heating_demand": 55,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        },
    )

    payload = routes.load_sample_payload()

    assert payload.samples[0].target_temperature_c == 21
    assert payload.samples[0].current_temperature_c == 18


def test_build_trv26_telemetry_exposes_battery_and_duty_cycle(tmp_path, monkeypatch) -> None:
    runtime_file = tmp_path / "runtime_measurements.json"
    monkeypatch.setattr(runtime_measurements_service, "RUNTIME_MEASUREMENTS_PATH", runtime_file)
    monkeypatch.setattr(runtime_measurements_service, "TRV26_DUTY_CYCLE_WINDOW_HOURS", 24)
    runtime_measurements_service._RUNTIME_SNAPSHOTS.clear()

    state = AdminState.model_validate(
        {
            "thermostats": [
                {
                    "trv_id": "trv26-salon-1",
                    "zone_label": "Salon",
                    "owner_name": "Alice",
                    "surface_m2": 25.0,
                }
            ],
            "zigbee_devices": [
                {
                    "device_id": "trv26-salon-1",
                    "controller_id": "bridge-a",
                    "role": "thermostat",
                    "friendly_name": "TRV Salon",
                }
            ],
        }
    )

    runtime_file.write_text(
        '{"measurements":[{"trv_id":"trv26-salon-1","controller_id":"bridge-a","target_temperature_c":21,"current_temperature_c":19,"valve_open_percent":55,"battery_percent":9,"running_state":"heat","preset":"manual","error_status":0,"needs_battery_replacement":true,"captured_at":"2026-03-10T11:00:00+00:00","history":[{"captured_at":"2026-03-10T08:00:00+00:00","running_state":"heat","valve_open_percent":60,"battery_percent":9,"preset":"manual","error_status":0},{"captured_at":"2026-03-10T10:00:00+00:00","running_state":"idle","valve_open_percent":0,"battery_percent":9,"preset":"manual","error_status":0},{"captured_at":"2026-03-10T11:00:00+00:00","running_state":"heat","valve_open_percent":55,"battery_percent":9,"preset":"manual","error_status":0}],"raw_payload":{}}]}',
        encoding="utf-8",
    )

    telemetry = runtime_measurements_service.build_trv26_telemetry(state)

    assert telemetry[0]["friendly_name"] == "TRV Salon"
    assert telemetry[0]["battery_percent"] == 9
    assert telemetry[0]["needs_battery_replacement"] is True
    assert telemetry[0]["running_state"] == "heat"
    assert telemetry[0]["preset"] == "manual"
    assert telemetry[0]["history_points"] == 3


def test_low_battery_alert_sent_once_per_low_battery_episode(tmp_path, monkeypatch) -> None:
    runtime_file = tmp_path / "runtime_measurements.json"
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(runtime_measurements_service, "RUNTIME_MEASUREMENTS_PATH", runtime_file)
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)
    runtime_measurements_service._RUNTIME_SNAPSHOTS.clear()
    admin_state_service.save_admin_state(
        AdminState.model_validate(
            {
                "thermostats": [
                    {
                        "trv_id": "trv26-salon-1",
                        "zone_label": "Salon",
                        "owner_name": "Alice",
                        "surface_m2": 25.0,
                    }
                ]
            }
        )
    )

    calls: list[tuple[str, int, str, str]] = []

    def fake_alert(device_id: str, battery_percent: int, owner_name: str = "", zone_label: str = "") -> bool:
        calls.append((device_id, battery_percent, owner_name, zone_label))
        return True

    monkeypatch.setattr(runtime_measurements_service.notifications, "send_low_battery_alert", fake_alert)

    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={"occupied_heating_setpoint": 21, "local_temperature": 18, "pi_heating_demand": 50, "battery": 9, "last_seen": datetime.now(timezone.utc).isoformat()},
    )
    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={"battery": 8, "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={"battery": 25, "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    runtime_measurements_service.record_runtime_measurement(
        device_id="trv26-salon-1",
        controller_id="bridge-a",
        payload={"battery": 7, "timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert calls == [
        ("trv26-salon-1", 9, "Alice", "Salon"),
        ("trv26-salon-1", 7, "Alice", "Salon"),
    ]