from datetime import datetime

from datetime import timezone

from app.models.schemas import (
    AllocationInput,
    AdminState,
    EcsAllocationLine,
    EcsAllocationRun,
    MonthlyAllocationReport,
    PdfScheduleConfig,
    PersonAllocation,
    ThermostatSample,
    ZoneEffort,
)
from app.services import admin_state as admin_state_service
from app.services.admin_state import apply_assignments_to_payload
from app.services.consumption import build_monthly_allocation
from app.services.billing import build_combined_allocation_rows
from app.services.scheduler import should_generate_report
from app.services import thermostat_control as thermostat_control_service



def test_assignments_override_sample_metadata() -> None:
    payload = AllocationInput(
        month_label="2026-03",
        samples=[
            ThermostatSample(
                trv_id="trv-1",
                zone_label="Ancienne zone",
                owner_name="Ancien occupant",
                surface_m2=10,
                target_temperature_c=21,
                current_temperature_c=19,
                valve_open_percent=40,
                captured_at="2026-03-01T08:15:00Z",
            )
        ],
    )
    state = AdminState.model_validate(
        {
            "occupants": [{"owner_name": "Alice", "notes": ""}],
            "thermostats": [
                {
                    "trv_id": "trv-1",
                    "zone_label": "Salon",
                    "owner_name": "Alice",
                    "surface_m2": 22,
                }
            ],
            "schedule": {},
        }
    )

    updated = apply_assignments_to_payload(payload, state)
    report = build_monthly_allocation(updated)

    assert updated.samples[0].owner_name == "Alice"
    assert updated.samples[0].surface_m2 == 22
    assert report.allocations[0].tracked_surface_m2 == 22



def test_schedule_due_only_once_per_month() -> None:
    schedule = PdfScheduleConfig(
        enabled=True,
        day_of_month=10,
        hour=6,
        minute=30,
        last_generated_month=None,
    )

    assert should_generate_report(datetime(2026, 3, 10, 6, 30), schedule, "2026-03") is True
    schedule.last_generated_month = "2026-03"
    assert should_generate_report(datetime(2026, 3, 10, 7, 0), schedule, "2026-03") is False


def test_ecs_allocation_uses_index_delta_and_persists_result(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(
        AdminState.model_validate(
            {
                "occupants": [
                    {"owner_name": "Alice", "notes": ""},
                    {"owner_name": "Benoit", "notes": ""},
                ]
            }
        )
    )

    first = admin_state_service.update_ecs_readings_and_allocate(
        current_indexes_m3={"Alice": 10.0, "Benoit": 20.0},
        total_amount=120.0,
        amount_label="EUR",
        period_label="Mars 2026",
    )
    second = admin_state_service.update_ecs_readings_and_allocate(
        current_indexes_m3={"Alice": 11.5, "Benoit": 22.0},
        total_amount=140.0,
        amount_label="EUR",
        period_label="Avril 2026",
    )

    assert first.last_ecs_allocation is not None
    assert first.last_ecs_allocation.total_consumption_m3 == 0
    assert second.last_ecs_allocation is not None
    assert second.last_ecs_allocation.total_consumption_m3 == 3.5
    assert second.last_ecs_allocation.allocations[0].delta_m3 == 1.5
    assert second.last_ecs_allocation.allocations[1].delta_m3 == 2.0
    assert second.last_ecs_allocation.allocations[0].allocated_amount == 21.0
    assert second.last_ecs_allocation.allocations[1].allocated_amount == 28.0
    assert len(second.ecs_allocation_history) == 2
    assert second.ecs_allocation_history[0].period_label == "Avril 2026"
    assert second.ecs_allocation_history[1].period_label == "Mars 2026"


def test_combined_allocation_rows_merge_heating_and_ecs_owners() -> None:
    report = MonthlyAllocationReport(
        month_label="2026-04",
        generated_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        allocations=[
            PersonAllocation(
                owner_name="Alice",
                total_effort_score=12.5,
                share_percent=62.5,
                tracked_surface_m2=45.0,
                zone_count=2,
            ),
            PersonAllocation(
                owner_name="Benoit",
                total_effort_score=7.5,
                share_percent=37.5,
                tracked_surface_m2=18.0,
                zone_count=1,
            ),
        ],
        zones=[
            ZoneEffort(
                trv_id="trv-1",
                zone_label="Salon",
                owner_name="Alice",
                surface_m2=45.0,
                delta_c=2.0,
                valve_factor=0.6,
                running_state="heat",
                running_state_factor=1.0,
                duty_cycle_percent=70.0,
                duty_cycle_factor=0.7,
                demand_factor=0.73,
                effort_score=12.5,
            )
        ],
    )
    ecs_allocation = EcsAllocationRun(
        period_label="2026-04",
        amount_label="EUR",
        total_amount=100.0,
        total_consumption_m3=4.0,
        calculated_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        allocations=[
            EcsAllocationLine(
                owner_name="Alice",
                previous_index_m3=10.0,
                current_index_m3=11.0,
                delta_m3=1.0,
                share_percent=25.0,
                allocated_amount=25.0,
            ),
            EcsAllocationLine(
                owner_name="Benoit",
                previous_index_m3=20.0,
                current_index_m3=23.0,
                delta_m3=3.0,
                share_percent=75.0,
                allocated_amount=75.0,
            ),
        ],
    )

    rows = build_combined_allocation_rows(report, ecs_allocation=ecs_allocation)

    assert [row["owner_name"] for row in rows] == ["Alice", "Benoit"]
    assert rows[0]["heating_share_percent"] == 62.5
    assert rows[0]["ecs_share_percent"] == 25.0
    assert rows[1]["heating_share_percent"] == 37.5
    assert rows[0]["heating_component_amount"] == 40.62
    assert rows[0]["ecs_component_amount"] == 8.75
    assert rows[0]["combined_allocated_amount"] == 49.37
    assert rows[1]["combined_allocated_amount"] == 50.63


def test_schedule_override_priority_and_expiry(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_or_update_thermostat("trv-1", "Salon", "Alice", 22.0)
    admin_state_service.add_or_update_thermostat_schedule(
        schedule_id="",
        trv_id="trv-1",
        weekday=0,
        start_time="06:00",
        end_time="08:30",
        target_temperature_c=20.0,
        enabled=True,
    )
    admin_state_service.set_thermostat_override(
        trv_id="trv-1",
        target_temperature_c=22.5,
        duration_hours=2,
        now=datetime(2026, 3, 9, 6, 15, tzinfo=timezone.utc),
    )

    state = admin_state_service.load_admin_state()
    desired_override = thermostat_control_service.resolve_desired_command_for_trv(
        state,
        "trv-1",
        now=datetime(2026, 3, 9, 7, 0, tzinfo=timezone.utc),
    )
    desired_schedule = thermostat_control_service.resolve_desired_command_for_trv(
        admin_state_service.clear_expired_thermostat_overrides(datetime(2026, 3, 9, 8, 16, tzinfo=timezone.utc)),
        "trv-1",
        now=datetime(2026, 3, 9, 8, 16, tzinfo=timezone.utc),
    )

    assert desired_override is not None
    assert desired_override.target_temperature_c == 22.5
    assert desired_override.reason == "override-2h"
    assert desired_schedule is not None
    assert desired_schedule.target_temperature_c == 20.0
    assert desired_schedule.reason.startswith("planning-")


def test_night_schedule_can_cross_midnight(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_or_update_thermostat("trv-1", "Salon", "Alice", 22.0)
    admin_state_service.add_or_update_thermostat_schedule(
        schedule_id="night",
        trv_id="trv-1",
        weekday=0,
        start_time="22:00",
        end_time="06:30",
        target_temperature_c=16.5,
        profile_name="Nuit",
        enabled=True,
    )

    state = admin_state_service.load_admin_state()
    desired = thermostat_control_service.resolve_desired_command_for_trv(
        state,
        "trv-1",
        now=datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc),
    )

    assert desired is not None
    assert desired.target_temperature_c == 16.5
    assert desired.reason == "planning-lun-22:00"


def test_apply_active_thermostat_controls_publishes_and_updates_state(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_or_update_controller(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
        enabled=True,
    )
    admin_state_service.add_or_update_zigbee_device(
        device_id="trv-1",
        controller_id="bridge-a",
        role="thermostat",
        friendly_name="TRV Salon",
        owner_name="Alice",
        zone_label="Salon",
        surface_m2=22.0,
        enabled=True,
    )
    admin_state_service.add_or_update_thermostat("trv-1", "Salon", "Alice", 22.0)
    admin_state_service.add_or_update_thermostat_schedule(
        schedule_id="",
        trv_id="trv-1",
        weekday=0,
        start_time="06:00",
        end_time="08:30",
        target_temperature_c=20.0,
        enabled=True,
    )

    published: list[tuple[str, float]] = []
    monkeypatch.setattr(
        thermostat_control_service,
        "publish_thermostat_setpoint",
        lambda controller, device_id, target_temperature_c, preset="manual": published.append((device_id, target_temperature_c)),
    )

    messages = thermostat_control_service.apply_active_thermostat_controls(
        now=datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc),
    )
    state = admin_state_service.load_admin_state()

    assert messages == ["trv-1:20.0C:planning-lun-06:00"]
    assert published == [("trv-1", 20.0)]
    assert state.thermostat_control_states[0].last_command_status == "Commande appliquee"

    messages_second = thermostat_control_service.apply_active_thermostat_controls(
        now=datetime(2026, 3, 9, 6, 35, tzinfo=timezone.utc),
    )

    assert messages_second == []
    assert published == [("trv-1", 20.0)]


def test_quick_profile_and_multi_day_schedule_creation(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_or_update_thermostat("trv-1", "Salon", "Alice", 22.0)
    admin_state_service.add_or_update_quick_profile(
        profile_id="night",
        profile_name="Nuit",
        start_time="22:00",
        end_time="06:30",
        target_temperature_c=16.5,
        enabled=True,
    )
    profile = admin_state_service.build_schedule_payload_from_profile("night")
    state = admin_state_service.create_schedules_for_days(
        trv_id="trv-1",
        weekdays=[0, 1, 2],
        start_time="06:00",
        end_time="08:00",
        target_temperature_c=profile.target_temperature_c,
        profile_name=profile.profile_name,
        enabled=True,
    )

    assert len(state.thermostat_quick_profiles) == 1
    assert state.thermostat_quick_profiles[0].profile_name == "Nuit"
    assert len(state.thermostat_schedules) == 3
    assert all(item.profile_name == "Nuit" for item in state.thermostat_schedules)


def test_occupant_hors_gel_sets_indefinite_override(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_or_update_thermostat("trv-1", "Salon", "Alice", 22.0)

    state = admin_state_service.set_occupant_hors_gel("Alice")

    assert len(state.thermostat_overrides) == 1
    assert state.thermostat_overrides[0].mode == "hors-gel"
    assert state.thermostat_overrides[0].target_temperature_c == 7.0
    assert state.thermostat_overrides[0].expires_at is None


def test_apply_active_thermostat_controls_can_filter_owner(tmp_path, monkeypatch) -> None:
    admin_file = tmp_path / "admin_state.json"
    monkeypatch.setattr(admin_state_service, "ADMIN_STATE_PATH", admin_file)

    admin_state_service.save_admin_state(AdminState())
    admin_state_service.add_occupant("Alice")
    admin_state_service.add_occupant("Benoit")
    admin_state_service.add_or_update_controller(
        controller_id="bridge-a",
        label="Bridge A",
        provider_type="zigbee2mqtt",
        endpoint_url="mqtt://broker.local:1883",
        enabled=True,
    )
    for trv_id, owner_name, zone_label in [("trv-1", "Alice", "Salon"), ("trv-2", "Benoit", "Bureau")]:
        admin_state_service.add_or_update_zigbee_device(
            device_id=trv_id,
            controller_id="bridge-a",
            role="thermostat",
            friendly_name=trv_id,
            owner_name=owner_name,
            zone_label=zone_label,
            surface_m2=20.0,
            enabled=True,
        )
        admin_state_service.add_or_update_thermostat(trv_id, zone_label, owner_name, 20.0)
        admin_state_service.add_or_update_thermostat_schedule(
            schedule_id="",
            trv_id=trv_id,
            weekday=0,
            start_time="06:00",
            end_time="09:00",
            target_temperature_c=19.0,
            enabled=True,
        )

    published: list[str] = []
    monkeypatch.setattr(
        thermostat_control_service,
        "publish_thermostat_setpoint",
        lambda controller, device_id, target_temperature_c, preset="manual": published.append(device_id),
    )

    messages = thermostat_control_service.apply_active_thermostat_controls(
        now=datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc),
        owner_filter="Alice",
    )

    assert messages == ["trv-1:19.0C:planning-lun-06:00"]
    assert published == ["trv-1"]


def test_build_heating_control_view_exposes_occupant_statuses() -> None:
    from app.api.routes import build_heating_control_view

    state = AdminState.model_validate(
        {
            "occupants": [
                {"owner_name": "Alice", "notes": ""},
                {"owner_name": "Benoit", "notes": ""},
            ],
            "thermostats": [
                {"trv_id": "trv-a", "zone_label": "Salon", "owner_name": "Alice", "surface_m2": 20},
                {"trv_id": "trv-b", "zone_label": "Bureau", "owner_name": "Benoit", "surface_m2": 12},
            ],
            "thermostat_overrides": [
                {
                    "trv_id": "trv-a",
                    "owner_name": "Alice",
                    "zone_label": "Salon",
                    "target_temperature_c": 7,
                    "duration_hours": None,
                    "mode": "hors-gel",
                    "started_at": "2026-03-11T09:00:00Z",
                    "expires_at": None,
                },
                {
                    "trv_id": "trv-b",
                    "owner_name": "Benoit",
                    "zone_label": "Bureau",
                    "target_temperature_c": 21,
                    "duration_hours": 12,
                    "mode": "manual",
                    "started_at": "2026-03-11T09:00:00Z",
                    "expires_at": "2026-03-11T21:00:00Z",
                },
            ],
        }
    )

    groups = build_heating_control_view(state)

    assert groups[0]["occupant_status_label"] == "Mode vacances hors-gel"
    assert groups[0]["occupant_status_class"] == "status-occupant-freeze"
    assert groups[1]["occupant_status_label"] == "Override temporaire"
    assert groups[1]["occupant_status_class"] == "status-occupant-temporary"
