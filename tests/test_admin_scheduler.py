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
from app.services.reporting import build_combined_allocation_rows
from app.services.scheduler import should_generate_report



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
    assert second.last_ecs_allocation.allocations[0].allocated_amount == 60.0
    assert second.last_ecs_allocation.allocations[1].allocated_amount == 80.0
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
            )
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
    assert rows[1]["heating_share_percent"] == 0.0
    assert rows[1]["ecs_allocated_amount"] == 75.0
