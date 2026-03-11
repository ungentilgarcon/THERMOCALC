from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import THERMOSTAT_CONTROL_REFRESH_MINUTES
from app.models.schemas import AdminState, ThermostatControlState, ThermostatScheduleEntry
from app.services.admin_state import clear_expired_thermostat_overrides, load_admin_state, update_thermostat_control_state
from app.services.zigbee2mqtt import publish_thermostat_setpoint


WEEKDAY_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


@dataclass(frozen=True)
class DesiredThermostatCommand:
    trv_id: str
    owner_name: str
    zone_label: str
    target_temperature_c: float
    reason: str


def _time_to_minutes(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def _matches_schedule(entry: ThermostatScheduleEntry, current_time: datetime) -> bool:
    if not entry.enabled:
        return False
    entry_weekday = entry.weekday
    current_weekday = current_time.weekday()
    current_minutes = current_time.hour * 60 + current_time.minute
    start_minutes = _time_to_minutes(entry.start_time)
    end_minutes = _time_to_minutes(entry.end_time)
    if start_minutes < end_minutes:
        return entry_weekday == current_weekday and start_minutes <= current_minutes < end_minutes
    return (
        (entry_weekday == current_weekday and current_minutes >= start_minutes)
        or ((entry_weekday + 1) % 7 == current_weekday and current_minutes < end_minutes)
    )


def resolve_desired_command_for_trv(
    state: AdminState,
    trv_id: str,
    now: datetime | None = None,
) -> DesiredThermostatCommand | None:
    current_time = now or datetime.now(timezone.utc)
    normalized_trv_id = trv_id.strip().lower()
    override = next(
        (
            item
            for item in state.thermostat_overrides
            if item.trv_id.lower() == normalized_trv_id and (item.expires_at is None or item.expires_at > current_time)
        ),
        None,
    )
    if override is not None:
        override_reason = "override" if not override.mode or override.mode == "manual" else override.mode
        if override.duration_hours is not None:
            override_reason = f"{override_reason}-{override.duration_hours}h"
        return DesiredThermostatCommand(
            trv_id=override.trv_id,
            owner_name=override.owner_name,
            zone_label=override.zone_label,
            target_temperature_c=override.target_temperature_c,
            reason=override_reason,
        )

    active_schedules = [
        item
        for item in state.thermostat_schedules
        if item.trv_id.lower() == normalized_trv_id and _matches_schedule(item, current_time)
    ]
    if not active_schedules:
        return None
    winning_schedule = sorted(active_schedules, key=lambda item: item.target_temperature_c, reverse=True)[0]
    return DesiredThermostatCommand(
        trv_id=winning_schedule.trv_id,
        owner_name=winning_schedule.owner_name,
        zone_label=winning_schedule.zone_label,
        target_temperature_c=winning_schedule.target_temperature_c,
        reason=f"planning-{WEEKDAY_LABELS[winning_schedule.weekday].lower()}-{winning_schedule.start_time}",
    )


def should_send_command(
    control_state: ThermostatControlState | None,
    desired: DesiredThermostatCommand,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    if control_state is None:
        return True
    if control_state.last_target_temperature_c is None:
        return True
    if abs(control_state.last_target_temperature_c - desired.target_temperature_c) >= 0.1:
        return True
    if control_state.last_applied_reason != desired.reason:
        return True
    if control_state.last_command_at is None:
        return True
    return current_time >= control_state.last_command_at + timedelta(minutes=THERMOSTAT_CONTROL_REFRESH_MINUTES)


def apply_active_thermostat_controls(
    now: datetime | None = None,
    trv_filter: str | None = None,
    owner_filter: str | None = None,
) -> list[str]:
    current_time = now or datetime.now(timezone.utc)
    state = clear_expired_thermostat_overrides(current_time)
    controllers = {item.controller_id.lower(): item for item in state.controllers if item.provider_type == "zigbee2mqtt" and item.enabled}
    devices = {
        item.device_id.lower(): item
        for item in state.zigbee_devices
        if item.role == "thermostat" and item.enabled and item.controller_id.lower() in controllers
    }
    control_states = {item.trv_id.lower(): item for item in state.thermostat_control_states}
    messages: list[str] = []

    for assignment in state.thermostats:
        if trv_filter and assignment.trv_id.lower() != trv_filter.strip().lower():
            continue
        if owner_filter and assignment.owner_name.lower() != owner_filter.strip().lower():
            continue
        device = devices.get(assignment.trv_id.lower())
        if device is None:
            continue
        desired = resolve_desired_command_for_trv(state, assignment.trv_id, now=current_time)
        if desired is None:
            continue
        control_state = control_states.get(assignment.trv_id.lower())
        if not should_send_command(control_state, desired, now=current_time):
            continue
        controller = controllers[device.controller_id.lower()]
        status = "Commande appliquee"
        applied_target = desired.target_temperature_c
        applied_reason = desired.reason
        applied_at = current_time
        try:
            publish_thermostat_setpoint(controller, assignment.trv_id, desired.target_temperature_c)
            messages.append(f"{assignment.trv_id}:{desired.target_temperature_c:.1f}C:{desired.reason}")
        except Exception as exc:
            status = f"Echec commande: {exc}"
            applied_target = None
            applied_reason = desired.reason
            applied_at = None
        update_thermostat_control_state(
            trv_id=assignment.trv_id,
            last_target_temperature_c=applied_target,
            last_applied_reason=applied_reason,
            last_command_status=status,
            last_command_at=applied_at,
        )
    return messages