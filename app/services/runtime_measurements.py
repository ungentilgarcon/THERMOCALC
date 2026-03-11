import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from app.core.config import (
    LOW_BATTERY_THRESHOLD_PERCENT,
    REALTIME_MEASUREMENT_MAX_AGE_MINUTES,
    REALTIME_MQTT_ENABLED,
    RUNTIME_MEASUREMENTS_PATH,
    TRV26_DUTY_CYCLE_WINDOW_HOURS,
    TRV26_HISTORY_RETENTION_HOURS,
)
from app.models.schemas import AdminState, AllocationInput, ThermostatSample, ZigbeeController
from app.services.admin_state import load_admin_state
from app.services import notifications
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


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _trim_history(history: list[dict[str, object]]) -> list[dict[str, object]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TRV26_HISTORY_RETENTION_HOURS)
    trimmed: list[dict[str, object]] = []
    for item in history:
        captured_at = _parse_timestamp(item.get("captured_at"))
        if captured_at >= cutoff:
            trimmed.append(
                {
                    "captured_at": captured_at.isoformat(),
                    "running_state": _coerce_text(item.get("running_state")),
                    "valve_open_percent": _coerce_float(item.get("valve_open_percent")) or 0.0,
                    "battery_percent": _coerce_int(item.get("battery_percent")),
                    "preset": _coerce_text(item.get("preset")),
                    "error_status": _coerce_int(item.get("error_status")),
                }
            )
    return trimmed


def _is_active_sample(sample: dict[str, object]) -> bool:
    running_state = _coerce_text(sample.get("running_state")).lower()
    valve_open_percent = _coerce_float(sample.get("valve_open_percent")) or 0.0
    return running_state == "heat" or valve_open_percent > 5.0


def compute_duty_cycle_percent(history: list[dict[str, object]], now: datetime | None = None) -> float | None:
    if not history:
        return None
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(hours=TRV26_DUTY_CYCLE_WINDOW_HOURS)
    samples = []
    for item in history:
        captured_at = _parse_timestamp(item.get("captured_at"))
        if captured_at >= cutoff:
            samples.append(
                {
                    "captured_at": captured_at,
                    "running_state": item.get("running_state"),
                    "valve_open_percent": item.get("valve_open_percent"),
                }
            )
    samples.sort(key=lambda item: item["captured_at"])
    if not samples:
        return None
    if len(samples) == 1:
        return 100.0 if _is_active_sample(samples[0]) else 0.0

    total_seconds = 0.0
    active_seconds = 0.0
    for index, item in enumerate(samples):
        segment_start = max(item["captured_at"], cutoff)
        next_time = samples[index + 1]["captured_at"] if index + 1 < len(samples) else current_time
        if next_time <= segment_start:
            continue
        segment_seconds = (next_time - segment_start).total_seconds()
        total_seconds += segment_seconds
        if _is_active_sample(item):
            active_seconds += segment_seconds
    if total_seconds <= 0:
        return None
    return round((active_seconds / total_seconds) * 100, 1)


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
    battery_percent = _coerce_int(payload.get("battery"))
    running_state = _coerce_text(payload.get("running_state"))
    preset = _coerce_text(payload.get("preset"))
    error_status = _coerce_int(payload.get("error_status"))
    captured_at = _parse_timestamp(payload.get("last_seen") or payload.get("timestamp"))
    if all(
        value is None or value == ""
        for value in [target_temperature, current_temperature, valve_open_percent, battery_percent, running_state, preset, error_status]
    ):
        return None
    normalized_valve = max(0.0, min(100.0, valve_open_percent)) if valve_open_percent is not None else None
    return {
        "trv_id": device_id,
        "controller_id": controller_id,
        "target_temperature_c": target_temperature,
        "current_temperature_c": current_temperature,
        "valve_open_percent": normalized_valve,
        "battery_percent": battery_percent,
        "running_state": running_state,
        "preset": preset,
        "error_status": error_status,
        "needs_battery_replacement": battery_percent is not None and battery_percent < LOW_BATTERY_THRESHOLD_PERCENT,
        "captured_at": captured_at.isoformat(),
        "history": [
            {
                "captured_at": captured_at.isoformat(),
                "running_state": running_state,
                "valve_open_percent": normalized_valve,
                "battery_percent": battery_percent,
                "preset": preset,
                "error_status": error_status,
            }
        ],
        "raw_payload": payload,
    }


def record_runtime_measurement(device_id: str, payload: dict[str, object], controller_id: str = "") -> bool:
    measurement = extract_measurement(device_id=device_id, payload=payload, controller_id=controller_id)
    if measurement is None:
        return False
    with _STORE_LOCK:
        existing = _RUNTIME_SNAPSHOTS.get(device_id.lower(), {})
        for field in [
            "target_temperature_c",
            "current_temperature_c",
            "valve_open_percent",
            "battery_percent",
            "running_state",
            "preset",
            "error_status",
        ]:
            if measurement.get(field) in {None, ""}:
                measurement[field] = existing.get(field)
        measurement["needs_battery_replacement"] = (
            measurement.get("battery_percent") is not None
            and int(measurement["battery_percent"]) < LOW_BATTERY_THRESHOLD_PERCENT
        )
        history = list(existing.get("history") or [])
        history.extend(measurement.get("history") or [])
        measurement["history"] = _trim_history(history)
        previous_alert = _coerce_text(existing.get("battery_alert_sent_at"))
        battery_percent = measurement.get("battery_percent")
        if measurement.get("needs_battery_replacement"):
            measurement["battery_alert_sent_at"] = previous_alert
        else:
            measurement["battery_alert_sent_at"] = ""
        _RUNTIME_SNAPSHOTS[device_id.lower()] = measurement

    if measurement.get("needs_battery_replacement") and not _coerce_text(measurement.get("battery_alert_sent_at")):
        owner_name = _coerce_text(payload.get("owner_name"))
        zone_label = _coerce_text(payload.get("zone_label"))
        if not owner_name or not zone_label:
            state = load_admin_state()
            assignment = next((item for item in state.thermostats if item.trv_id.lower() == device_id.lower()), None)
            owner_name = owner_name or (assignment.owner_name if assignment else "")
            zone_label = zone_label or (assignment.zone_label if assignment else "")
        if notifications.send_low_battery_alert(device_id=device_id, battery_percent=int(battery_percent), owner_name=owner_name, zone_label=zone_label):
            with _STORE_LOCK:
                _RUNTIME_SNAPSHOTS[device_id.lower()]["battery_alert_sent_at"] = datetime.now(timezone.utc).isoformat()
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
                running_state=_coerce_text(measurement.get("running_state")),
                duty_cycle_percent=compute_duty_cycle_percent(list(measurement.get("history") or [])),
                captured_at=captured_at,
            )
        )

    if not samples:
        return None
    month_label = max(sample.captured_at for sample in samples).strftime("%Y-%m")
    return AllocationInput(month_label=month_label, samples=samples)


def build_trv26_telemetry(state: AdminState) -> list[dict[str, object]]:
    measurements = get_runtime_measurements()
    device_index = {item.device_id.lower(): item for item in state.zigbee_devices if item.role == "thermostat"}
    telemetry: list[dict[str, object]] = []

    seen_ids: set[str] = set()
    for assignment in state.thermostats:
        trv_id = assignment.trv_id.lower()
        seen_ids.add(trv_id)
        measurement = measurements.get(trv_id, {})
        device = device_index.get(trv_id)
        duty_cycle_percent = compute_duty_cycle_percent(list(measurement.get("history") or []))
        battery_percent = _coerce_int(measurement.get("battery_percent"))
        telemetry.append(
            {
                "trv_id": assignment.trv_id,
                "friendly_name": device.friendly_name if device else assignment.trv_id,
                "owner_name": assignment.owner_name or (device.owner_name if device else ""),
                "zone_label": assignment.zone_label or (device.zone_label if device else ""),
                "controller_id": measurement.get("controller_id") or (device.controller_id if device else ""),
                "battery_percent": battery_percent,
                "battery_status": "A remplacer" if battery_percent is not None and battery_percent < LOW_BATTERY_THRESHOLD_PERCENT else "OK",
                "needs_battery_replacement": bool(measurement.get("needs_battery_replacement")),
                "running_state": _coerce_text(measurement.get("running_state")) or "inconnu",
                "preset": _coerce_text(measurement.get("preset")) or "inconnu",
                "error_status": _coerce_int(measurement.get("error_status")),
                "duty_cycle_percent": duty_cycle_percent,
                "captured_at": _parse_timestamp(measurement.get("captured_at")) if measurement.get("captured_at") else None,
                "history_points": len(list(measurement.get("history") or [])),
            }
        )

    for device_id, device in device_index.items():
        if device_id in seen_ids:
            continue
        measurement = measurements.get(device_id, {})
        battery_percent = _coerce_int(measurement.get("battery_percent"))
        telemetry.append(
            {
                "trv_id": device.device_id,
                "friendly_name": device.friendly_name,
                "owner_name": device.owner_name,
                "zone_label": device.zone_label,
                "controller_id": device.controller_id,
                "battery_percent": battery_percent,
                "battery_status": "A remplacer" if battery_percent is not None and battery_percent < LOW_BATTERY_THRESHOLD_PERCENT else "OK",
                "needs_battery_replacement": bool(measurement.get("needs_battery_replacement")),
                "running_state": _coerce_text(measurement.get("running_state")) or "inconnu",
                "preset": _coerce_text(measurement.get("preset")) or "inconnu",
                "error_status": _coerce_int(measurement.get("error_status")),
                "duty_cycle_percent": compute_duty_cycle_percent(list(measurement.get("history") or [])),
                "captured_at": _parse_timestamp(measurement.get("captured_at")) if measurement.get("captured_at") else None,
                "history_points": len(list(measurement.get("history") or [])),
            }
        )

    telemetry.sort(key=lambda item: (not item["needs_battery_replacement"], item["owner_name"], item["zone_label"], item["trv_id"]))
    return telemetry


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