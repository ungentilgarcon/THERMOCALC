import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from app.core.config import REALTIME_MEASUREMENT_MAX_AGE_MINUTES, REALTIME_MQTT_ENABLED, RUNTIME_MEASUREMENTS_PATH
from app.models.schemas import AdminState, AllocationInput, ThermostatSample, ZigbeeController
from app.services.zigbee2mqtt import _build_client, build_broker_config


_STORE_LOCK = Lock()
_RUNTIME_SNAPSHOTS: dict[str, dict[str, object]] = {}


def _coerce_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def ensure_runtime_measurements_file() -> None:
    RUNTIME_MEASUREMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not RUNTIME_MEASUREMENTS_PATH.exists():
        RUNTIME_MEASUREMENTS_PATH.write_text('{"measurements": []}', encoding="utf-8")


def _persist_runtime_measurements() -> None:
    with _STORE_LOCK:
        measurements = sorted(_RUNTIME_SNAPSHOTS.values(), key=lambda item: str(item["trv_id"]))
    ensure_runtime_measurements_file()
    RUNTIME_MEASUREMENTS_PATH.write_text(json.dumps({"measurements": measurements}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_runtime_measurements() -> dict[str, dict[str, object]]:
    ensure_runtime_measurements_file()
    content = json.loads(RUNTIME_MEASUREMENTS_PATH.read_text(encoding="utf-8"))
    measurements = content.get("measurements") or []
    with _STORE_LOCK:
        _RUNTIME_SNAPSHOTS.clear()
        for item in measurements:
            trv_id = str(item.get("trv_id") or "").strip()
            if trv_id:
                _RUNTIME_SNAPSHOTS[trv_id.lower()] = item
        return dict(_RUNTIME_SNAPSHOTS)


def get_runtime_measurements() -> dict[str, dict[str, object]]:
    with _STORE_LOCK:
        if _RUNTIME_SNAPSHOTS:
            return dict(_RUNTIME_SNAPSHOTS)
    return load_runtime_measurements()


def extract_measurement(device_id: str, payload: dict[str, object], controller_id: str = "") -> dict[str, object] | None:
    target_temperature = _coerce_float(
        payload.get("occupied_heating_setpoint")
        or payload.get("current_heating_setpoint")
        or payload.get("target_temperature")
    )
    current_temperature = _coerce_float(
        payload.get("local_temperature")
        or payload.get("current_temperature")
        or payload.get("temperature")
    )
    valve_open_percent = _coerce_float(
        payload.get("pi_heating_demand")
        or payload.get("position")
        or payload.get("valve_open_percent")
    )
    if target_temperature is None or current_temperature is None or valve_open_percent is None:
        return None
    return {
        "trv_id": device_id,
        "controller_id": controller_id,
        "target_temperature_c": target_temperature,
        "current_temperature_c": current_temperature,
        "valve_open_percent": max(0.0, min(100.0, valve_open_percent)),
        "captured_at": _parse_timestamp(payload.get("last_seen") or payload.get("timestamp")).isoformat(),
        "raw_payload": payload,
    }


def record_runtime_measurement(device_id: str, payload: dict[str, object], controller_id: str = "") -> bool:
    measurement = extract_measurement(device_id=device_id, payload=payload, controller_id=controller_id)
    if measurement is None:
        return False
    with _STORE_LOCK:
        _RUNTIME_SNAPSHOTS[device_id.lower()] = measurement
    _persist_runtime_measurements()
    return True


def build_realtime_payload(state: AdminState) -> AllocationInput | None:
    measurements = get_runtime_measurements()
    if not measurements:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=REALTIME_MEASUREMENT_MAX_AGE_MINUTES)
    samples: list[ThermostatSample] = []
    for assignment in state.thermostats:
        measurement = measurements.get(assignment.trv_id.lower())
        if not measurement:
            continue
        captured_at = _parse_timestamp(measurement.get("captured_at"))
        if captured_at < cutoff:
            continue
        samples.append(
            ThermostatSample(
                trv_id=assignment.trv_id,
                zone_label=assignment.zone_label,
                owner_name=assignment.owner_name,
                surface_m2=assignment.surface_m2,
                target_temperature_c=float(measurement["target_temperature_c"]),
                current_temperature_c=float(measurement["current_temperature_c"]),
                valve_open_percent=float(measurement["valve_open_percent"]),
                captured_at=captured_at,
            )
        )

    if not samples:
        return None
    month_label = max(sample.captured_at for sample in samples).strftime("%Y-%m")
    return AllocationInput(month_label=month_label, samples=samples)


@dataclass
class RuntimeSubscription:
    controller_id: str
    signature: tuple[str, int, str, str, str]
    client: object

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.client.loop_stop()
        with contextlib.suppress(Exception):
            self.client.disconnect()


_SUBSCRIPTIONS: dict[str, RuntimeSubscription] = {}


def _build_signature(controller: ZigbeeController) -> tuple[str, int, str, str, str]:
    broker = build_broker_config(controller)
    return (broker.host, broker.port, broker.username, broker.password, broker.base_topic)


def _start_subscription(controller: ZigbeeController) -> RuntimeSubscription:
    broker = build_broker_config(controller)
    client = _build_client(broker)
    telemetry_topic = f"{broker.base_topic}/+"

    def on_connect(mqtt_client, _userdata, _flags, rc, _properties=None) -> None:
        if rc == 0:
            mqtt_client.subscribe(telemetry_topic)

    def on_message(_client, _userdata, message) -> None:
        topic = str(message.topic or "")
        if "/bridge/" in topic:
            return
        device_id = topic.removeprefix(f"{broker.base_topic}/").strip()
        if not device_id or "/" in device_id:
            return
        with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError):
            payload = json.loads(message.payload.decode("utf-8"))
            if isinstance(payload, dict):
                record_runtime_measurement(device_id=device_id, payload=payload, controller_id=controller.controller_id)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker.host, broker.port, keepalive=30)
    client.loop_start()
    return RuntimeSubscription(controller_id=controller.controller_id, signature=_build_signature(controller), client=client)


def sync_runtime_subscriptions(state: AdminState) -> None:
    if not REALTIME_MQTT_ENABLED:
        stop_runtime_subscriptions()
        return

    desired = {
        controller.controller_id: controller
        for controller in state.controllers
        if controller.provider_type == "zigbee2mqtt" and controller.enabled
    }

    for controller_id in list(_SUBSCRIPTIONS):
        if controller_id not in desired:
            _SUBSCRIPTIONS.pop(controller_id).stop()

    for controller_id, controller in desired.items():
        signature = _build_signature(controller)
        existing = _SUBSCRIPTIONS.get(controller_id)
        if existing and existing.signature == signature:
            continue
        if existing:
            existing.stop()
        _SUBSCRIPTIONS[controller_id] = _start_subscription(controller)


def stop_runtime_subscriptions() -> None:
    for controller_id in list(_SUBSCRIPTIONS):
        _SUBSCRIPTIONS.pop(controller_id).stop()