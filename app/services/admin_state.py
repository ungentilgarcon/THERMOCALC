import json
from pathlib import Path

from app.core.config import ADMIN_STATE_PATH, GENERATED_REPORTS_DIR
from app.models.schemas import (
    AdminState,
    AllocationInput,
    Occupant,
    PdfScheduleConfig,
    ThermostatAssignment,
    ZigbeeController,
    ZigbeeEndpoint,
    ZigbeePairingLink,
)



def ensure_admin_state_file() -> None:
    if ADMIN_STATE_PATH.exists():
        return
    ADMIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    default_state = AdminState()
    ADMIN_STATE_PATH.write_text(default_state.model_dump_json(indent=2), encoding="utf-8")



def load_admin_state() -> AdminState:
    ensure_admin_state_file()
    content = json.loads(ADMIN_STATE_PATH.read_text(encoding="utf-8"))
    return AdminState.model_validate(content)



def save_admin_state(state: AdminState) -> AdminState:
    state = sync_thermostat_assignments(state)
    ADMIN_STATE_PATH.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state



def add_occupant(owner_name: str, notes: str = "") -> AdminState:
    normalized_name = owner_name.strip()
    state = load_admin_state()
    existing = next((item for item in state.occupants if item.owner_name.lower() == normalized_name.lower()), None)
    if existing is None:
        state.occupants.append(Occupant(owner_name=normalized_name, notes=notes.strip()))
    else:
        existing.notes = notes.strip()
    state.occupants.sort(key=lambda item: item.owner_name.lower())
    return save_admin_state(state)


def remove_occupant(owner_name: str) -> AdminState:
    normalized_name = owner_name.strip().lower()
    state = load_admin_state()
    state.occupants = [item for item in state.occupants if item.owner_name.lower() != normalized_name]
    state.thermostats = [item for item in state.thermostats if item.owner_name.lower() != normalized_name]
    return save_admin_state(state)



def add_or_update_thermostat(trv_id: str, zone_label: str, owner_name: str, surface_m2: float) -> AdminState:
    normalized_trv_id = trv_id.strip()
    state = load_admin_state()
    normalized_owner_name = owner_name.strip()
    if not any(item.owner_name.lower() == normalized_owner_name.lower() for item in state.occupants):
        state.occupants.append(Occupant(owner_name=normalized_owner_name, notes=""))
    assignment = ThermostatAssignment(
        trv_id=normalized_trv_id,
        zone_label=zone_label.strip(),
        owner_name=normalized_owner_name,
        surface_m2=surface_m2,
    )
    for index, item in enumerate(state.thermostats):
        if item.trv_id == normalized_trv_id:
            state.thermostats[index] = assignment
            break
    else:
        state.thermostats.append(assignment)
    for index, item in enumerate(state.zigbee_devices):
        if item.device_id.lower() == normalized_trv_id.lower() and item.role == "thermostat":
            state.zigbee_devices[index] = item.model_copy(
                update={
                    "owner_name": normalized_owner_name,
                    "zone_label": zone_label.strip(),
                    "surface_m2": surface_m2,
                }
            )
    state.occupants.sort(key=lambda item: item.owner_name.lower())
    state.thermostats.sort(key=lambda item: item.trv_id.lower())
    return save_admin_state(state)


def remove_thermostat(trv_id: str) -> AdminState:
    normalized_trv_id = trv_id.strip().lower()
    state = load_admin_state()
    state.thermostats = [item for item in state.thermostats if item.trv_id.lower() != normalized_trv_id]
    return save_admin_state(state)



def update_schedule(enabled: bool, day_of_month: int, hour: int, minute: int) -> AdminState:
    state = load_admin_state()
    state.schedule = PdfScheduleConfig(
        enabled=enabled,
        day_of_month=day_of_month,
        hour=hour,
        minute=minute,
        output_dir=state.schedule.output_dir,
        last_generated_month=state.schedule.last_generated_month,
    )
    return save_admin_state(state)



def mark_report_generated(month_label: str) -> AdminState:
    state = load_admin_state()
    state.schedule.last_generated_month = month_label
    return save_admin_state(state)


def add_or_update_controller(
    controller_id: str,
    label: str,
    provider_type: str,
    endpoint_url: str = "",
    mqtt_username: str = "",
    mqtt_password: str = "",
    base_topic: str = "zigbee2mqtt",
    auto_discovery_enabled: bool = False,
    discovery_interval_minutes: int = 15,
    last_discovery_at=None,
    last_discovery_status: str = "",
    notes: str = "",
    enabled: bool = True,
) -> AdminState:
    state = load_admin_state()
    existing = next((item for item in state.controllers if item.controller_id.lower() == controller_id.strip().lower()), None)
    controller = ZigbeeController(
        controller_id=controller_id.strip(),
        label=label.strip(),
        provider_type=provider_type,
        endpoint_url=endpoint_url.strip() or (existing.endpoint_url if existing else ""),
        mqtt_username=mqtt_username.strip() or (existing.mqtt_username if existing else ""),
        mqtt_password=mqtt_password.strip() or (existing.mqtt_password if existing else ""),
        base_topic=base_topic.strip() or (existing.base_topic if existing else "zigbee2mqtt"),
        auto_discovery_enabled=auto_discovery_enabled,
        discovery_interval_minutes=discovery_interval_minutes,
        last_discovery_at=last_discovery_at if last_discovery_at is not None else (existing.last_discovery_at if existing else None),
        last_discovery_status=last_discovery_status or (existing.last_discovery_status if existing else ""),
        notes=notes.strip(),
        enabled=enabled,
    )
    for index, item in enumerate(state.controllers):
        if item.controller_id.lower() == controller.controller_id.lower():
            state.controllers[index] = controller
            break
    else:
        state.controllers.append(controller)
    state.controllers.sort(key=lambda item: item.controller_id.lower())
    return save_admin_state(state)


def remove_controller(controller_id: str) -> AdminState:
    normalized_controller_id = controller_id.strip().lower()
    state = load_admin_state()
    state.controllers = [item for item in state.controllers if item.controller_id.lower() != normalized_controller_id]
    removed_devices = {
        item.device_id.lower()
        for item in state.zigbee_devices
        if item.controller_id.lower() == normalized_controller_id
    }
    state.zigbee_devices = [item for item in state.zigbee_devices if item.controller_id.lower() != normalized_controller_id]
    state.zigbee_pairings = [
        item
        for item in state.zigbee_pairings
        if item.controller_id.lower() != normalized_controller_id
        and item.source_device_id.lower() not in removed_devices
        and item.target_device_id.lower() not in removed_devices
    ]
    return save_admin_state(state)


def add_or_update_zigbee_device(
    device_id: str,
    controller_id: str,
    role: str,
    friendly_name: str,
    model: str = "",
    ieee_address: str = "",
    owner_name: str = "",
    zone_label: str = "",
    surface_m2: float | None = None,
    enabled: bool = True,
) -> AdminState:
    state = load_admin_state()
    normalized_owner_name = owner_name.strip()
    if normalized_owner_name and not any(item.owner_name.lower() == normalized_owner_name.lower() for item in state.occupants):
        state.occupants.append(Occupant(owner_name=normalized_owner_name, notes=""))
    device = ZigbeeEndpoint(
        device_id=device_id.strip(),
        controller_id=controller_id.strip(),
        role=role,
        friendly_name=friendly_name.strip(),
        model=model.strip(),
        ieee_address=ieee_address.strip(),
        owner_name=normalized_owner_name,
        zone_label=zone_label.strip(),
        surface_m2=surface_m2,
        enabled=enabled,
    )
    for index, item in enumerate(state.zigbee_devices):
        if item.device_id.lower() == device.device_id.lower():
            state.zigbee_devices[index] = device
            break
    else:
        state.zigbee_devices.append(device)
    state.occupants.sort(key=lambda item: item.owner_name.lower())
    state.zigbee_devices.sort(key=lambda item: item.device_id.lower())
    return save_admin_state(state)


def remove_zigbee_device(device_id: str) -> AdminState:
    normalized_device_id = device_id.strip().lower()
    state = load_admin_state()
    state.zigbee_devices = [item for item in state.zigbee_devices if item.device_id.lower() != normalized_device_id]
    state.zigbee_pairings = [
        item
        for item in state.zigbee_pairings
        if item.source_device_id.lower() != normalized_device_id and item.target_device_id.lower() != normalized_device_id
    ]
    return save_admin_state(state)


def add_or_update_zigbee_pairing(
    link_id: str,
    controller_id: str,
    source_device_id: str,
    target_device_id: str,
    relation_type: str,
    notes: str = "",
    enabled: bool = True,
) -> AdminState:
    state = load_admin_state()
    pairing = ZigbeePairingLink(
        link_id=link_id.strip(),
        controller_id=controller_id.strip(),
        source_device_id=source_device_id.strip(),
        target_device_id=target_device_id.strip(),
        relation_type=relation_type,
        notes=notes.strip(),
        enabled=enabled,
    )
    for index, item in enumerate(state.zigbee_pairings):
        if item.link_id.lower() == pairing.link_id.lower():
            state.zigbee_pairings[index] = pairing
            break
    else:
        state.zigbee_pairings.append(pairing)
    state.zigbee_pairings.sort(key=lambda item: item.link_id.lower())
    return save_admin_state(state)


def remove_zigbee_pairing(link_id: str) -> AdminState:
    normalized_link_id = link_id.strip().lower()
    state = load_admin_state()
    state.zigbee_pairings = [item for item in state.zigbee_pairings if item.link_id.lower() != normalized_link_id]
    return save_admin_state(state)


def update_controller_discovery_status(controller_id: str, last_discovery_at, status: str) -> AdminState:
    state = load_admin_state()
    for index, item in enumerate(state.controllers):
        if item.controller_id.lower() == controller_id.strip().lower():
            state.controllers[index] = item.model_copy(
                update={
                    "last_discovery_at": last_discovery_at,
                    "last_discovery_status": status,
                }
            )
            break
    return save_admin_state(state)


def sync_thermostat_assignments(state: AdminState) -> AdminState:
    assignments_by_trv = {item.trv_id.lower(): item for item in state.thermostats}
    synced_assignments: list[ThermostatAssignment] = []
    touched_trvs: set[str] = set()

    for device in state.zigbee_devices:
        if device.role != "thermostat":
            continue
        if not device.owner_name or not device.zone_label:
            continue
        existing = assignments_by_trv.get(device.device_id.lower())
        surface_m2 = device.surface_m2 or (existing.surface_m2 if existing else 1.0)
        synced_assignments.append(
            ThermostatAssignment(
                trv_id=device.device_id,
                zone_label=device.zone_label,
                owner_name=device.owner_name,
                surface_m2=surface_m2,
            )
        )
        touched_trvs.add(device.device_id.lower())

    for assignment in state.thermostats:
        if assignment.trv_id.lower() in touched_trvs:
            continue
        synced_assignments.append(assignment)

    synced_assignments.sort(key=lambda item: item.trv_id.lower())
    state.thermostats = synced_assignments
    return state



def apply_assignments_to_payload(payload: AllocationInput, state: AdminState) -> AllocationInput:
    assignments = {assignment.trv_id: assignment for assignment in state.thermostats}
    remapped_samples = []
    for sample in payload.samples:
        assignment = assignments.get(sample.trv_id)
        if assignment is None:
            remapped_samples.append(sample)
            continue
        remapped_samples.append(
            sample.model_copy(
                update={
                    "zone_label": assignment.zone_label,
                    "owner_name": assignment.owner_name,
                    "surface_m2": assignment.surface_m2,
                }
            )
        )
    return payload.model_copy(update={"samples": remapped_samples})



def list_generated_reports() -> list[Path]:
    GENERATED_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(GENERATED_REPORTS_DIR.glob("*.pdf"), reverse=True)
