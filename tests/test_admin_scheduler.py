from datetime import datetime

from app.models.schemas import AllocationInput, AdminState, PdfScheduleConfig, ThermostatSample
from app.services.admin_state import apply_assignments_to_payload
from app.services.consumption import build_monthly_allocation
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
