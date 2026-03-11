import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from app.core.config import DEFAULT_ZIGBEE2MQTT_BASE_TOPIC, ZIGBEE_CONNECTIVITY_TIMEOUT_SECONDS, ZIGBEE_DISCOVERY_TIMEOUT_SECONDS
from app.models.schemas import ZigbeeController, ZigbeeEndpoint
from app.services.admin_state import add_or_update_zigbee_device, load_admin_state, update_controller_discovery_status


@dataclass
class Zigbee2MQTTBrokerConfig:
    host: str
    port: int
    username: str
    password: str
    base_topic: str


def _build_client(broker: Zigbee2MQTTBrokerConfig) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if broker.username:
        client.username_pw_set(broker.username, broker.password)
    return client


def _normalize_broker_url(endpoint_url: str) -> str:
    if endpoint_url.startswith("mqtt://"):
        return endpoint_url
    return f"mqtt://{endpoint_url}"


def build_broker_config(controller: ZigbeeController) -> Zigbee2MQTTBrokerConfig:
    parsed = urlparse(_normalize_broker_url(controller.endpoint_url or "localhost:1883"))
    return Zigbee2MQTTBrokerConfig(
        host=parsed.hostname or "localhost",
        port=parsed.port or 1883,
        username=controller.mqtt_username,
        password=controller.mqtt_password,
        base_topic=controller.base_topic or DEFAULT_ZIGBEE2MQTT_BASE_TOPIC,
    )


def _map_device_role(device: dict) -> str | None:
    definition = device.get("definition") or {}
    model = str(device.get("model_id") or definition.get("model") or "")
    exposes = definition.get("exposes") or []
    expose_names = {str(item.get("name") or item.get("property") or "").lower() for item in exposes if isinstance(item, dict)}

    if "TRV" in model.upper() or "occupied_heating_setpoint" in expose_names or "local_temperature" in expose_names:
        return "thermostat"
    if "contact" in expose_names or "occupancy" in expose_names or "temperature" in expose_names:
        return "detector"
    if "state" in expose_names or "switch" in model.lower() or "relay" in model.lower():
        return "receiver"
    return None


def map_bridge_devices(controller: ZigbeeController, payload: list[dict]) -> list[ZigbeeEndpoint]:
    discovered: list[ZigbeeEndpoint] = []
    for item in payload:
        if item.get("type") in {"Coordinator", "Router"}:
            continue
        role = _map_device_role(item)
        if role is None:
            continue
        friendly_name = str(item.get("friendly_name") or item.get("ieee_address") or "device")
        discovered.append(
            ZigbeeEndpoint(
                device_id=friendly_name,
                controller_id=controller.controller_id,
                role=role,
                friendly_name=friendly_name,
                model=str(item.get("model_id") or ""),
                ieee_address=str(item.get("ieee_address") or ""),
                owner_name="",
                zone_label="",
                surface_m2=None,
                enabled=not bool(item.get("disabled", False)),
            )
        )
    return discovered


def discover_devices(controller: ZigbeeController) -> list[ZigbeeEndpoint]:
    broker = build_broker_config(controller)
    topic = f"{broker.base_topic}/bridge/devices"
    payload_holder: dict[str, str] = {}
    ready = Event()

    def on_connect(client: mqtt.Client, _userdata, _flags, rc, _properties=None) -> None:
        if rc != 0:
            ready.set()
            return
        client.subscribe(topic)

    def on_message(_client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        payload_holder["payload"] = message.payload.decode("utf-8")
        ready.set()

    client = _build_client(broker)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker.host, broker.port, keepalive=30)
    client.loop_start()
    ready.wait(timeout=ZIGBEE_DISCOVERY_TIMEOUT_SECONDS)
    client.loop_stop()
    client.disconnect()

    raw_payload = payload_holder.get("payload")
    if not raw_payload:
        raise RuntimeError("Aucune reponse recue sur le topic bridge/devices")
    return map_bridge_devices(controller, json.loads(raw_payload))


def set_permit_join(controller: ZigbeeController, seconds: int) -> None:
    broker = build_broker_config(controller)
    topic = f"{broker.base_topic}/bridge/request/permit_join"
    client = _build_client(broker)
    client.connect(broker.host, broker.port, keepalive=30)
    client.loop_start()
    client.publish(topic, json.dumps({"value": True, "time": seconds}), qos=1)
    client.loop_stop()
    client.disconnect()


def test_broker_connectivity(controller: ZigbeeController) -> tuple[bool, str]:
    broker = build_broker_config(controller)
    state_topic = f"{broker.base_topic}/bridge/state"
    connected = Event()
    state_ready = Event()
    bridge_state: dict[str, str] = {}
    error: dict[str, str] = {}

    def on_connect(client: mqtt.Client, _userdata, _flags, rc, _properties=None) -> None:
        if rc != 0:
            error["message"] = f"Connexion MQTT refusee: code {rc}"
            connected.set()
            return
        client.subscribe(state_topic)
        connected.set()

    def on_message(_client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        bridge_state["value"] = message.payload.decode("utf-8")
        state_ready.set()

    client = _build_client(broker)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(broker.host, broker.port, keepalive=15)
        client.loop_start()
        if not connected.wait(timeout=ZIGBEE_CONNECTIVITY_TIMEOUT_SECONDS):
            return False, "Broker MQTT injoignable"
        if error:
            return False, error["message"]
        state_ready.wait(timeout=ZIGBEE_CONNECTIVITY_TIMEOUT_SECONDS)
        if bridge_state.get("value"):
            return True, f"Broker joignable, bridge state={bridge_state['value']}"
        return True, "Broker joignable, bridge state non remonte"
    except Exception as exc:
        return False, f"Echec connectivite MQTT: {exc}"
    finally:
        with contextlib.suppress(Exception):
            client.loop_stop()
            client.disconnect()


def prepare_new_thermostat_pairing(
    controller: ZigbeeController,
    duration_seconds: int,
    expected_device_id: str = "",
    friendly_name: str = "",
    owner_name: str = "",
    zone_label: str = "",
    surface_m2: float | None = None,
) -> str:
    set_permit_join(controller, seconds=duration_seconds)
    if expected_device_id.strip():
        add_or_update_zigbee_device(
            device_id=expected_device_id.strip(),
            controller_id=controller.controller_id,
            role="thermostat",
            friendly_name=friendly_name.strip() or expected_device_id.strip(),
            model="TRV26",
            ieee_address="",
            owner_name=owner_name.strip(),
            zone_label=zone_label.strip(),
            surface_m2=surface_m2,
            enabled=True,
        )
        return f"Permit join actif {duration_seconds}s et tete pre-affectee: {expected_device_id.strip()}"
    return f"Permit join actif {duration_seconds}s pour nouvelle tete"


def should_refresh_controller(controller: ZigbeeController, now: datetime | None = None) -> bool:
    if controller.provider_type != "zigbee2mqtt" or not controller.enabled or not controller.auto_discovery_enabled:
        return False
    current_time = now or datetime.now(timezone.utc)
    if controller.last_discovery_at is None:
        return True
    return current_time >= controller.last_discovery_at + timedelta(minutes=controller.discovery_interval_minutes)


def refresh_controller_inventory(controller: ZigbeeController) -> tuple[int, str]:
    discovered_devices = discover_devices(controller)
    state = load_admin_state()
    existing_devices = {item.device_id.lower(): item for item in state.zigbee_devices}
    thermostat_assignments = {item.trv_id.lower(): item for item in state.thermostats}

    for device in discovered_devices:
        existing = existing_devices.get(device.device_id.lower())
        assignment = thermostat_assignments.get(device.device_id.lower())
        add_or_update_zigbee_device(
            device_id=device.device_id,
            controller_id=device.controller_id,
            role=device.role,
            friendly_name=device.friendly_name,
            model=device.model,
            ieee_address=device.ieee_address,
            owner_name=(existing.owner_name if existing and existing.owner_name else (assignment.owner_name if assignment else "")),
            zone_label=(existing.zone_label if existing and existing.zone_label else (assignment.zone_label if assignment else "")),
            surface_m2=(existing.surface_m2 if existing and existing.surface_m2 else (assignment.surface_m2 if assignment else None)),
            enabled=device.enabled,
        )

    status = f"Discovery OK: {len(discovered_devices)} devices"
    update_controller_discovery_status(controller.controller_id, datetime.now(timezone.utc), status)
    return len(discovered_devices), status


def refresh_due_controllers() -> list[str]:
    state = load_admin_state()
    messages: list[str] = []
    for controller in state.controllers:
        if not should_refresh_controller(controller):
            continue
        try:
            count, status = refresh_controller_inventory(controller)
            messages.append(f"{controller.controller_id}:{count}")
            update_controller_discovery_status(controller.controller_id, datetime.now(timezone.utc), status)
        except Exception as exc:
            update_controller_discovery_status(
                controller.controller_id,
                datetime.now(timezone.utc),
                f"Discovery KO: {exc}",
            )
    return messages