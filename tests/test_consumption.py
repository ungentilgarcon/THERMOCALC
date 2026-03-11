from app.models.schemas import AllocationInput, ThermostatSample
from app.services.consumption import build_monthly_allocation, compute_effort



def test_compute_effort_blocks_negative_delta() -> None:
    assert compute_effort(-2.0, 15.0, 90.0) == 0.0



def test_allocation_percentages_sum_to_100() -> None:
    payload = AllocationInput(
        month_label="2026-03",
        samples=[
            ThermostatSample(
                trv_id="a",
                zone_label="A",
                owner_name="Alice",
                surface_m2=20,
                target_temperature_c=21,
                current_temperature_c=19,
                valve_open_percent=50,
                captured_at="2026-03-01T08:15:00Z",
            ),
            ThermostatSample(
                trv_id="b",
                zone_label="B",
                owner_name="Benoit",
                surface_m2=10,
                target_temperature_c=20,
                current_temperature_c=19,
                valve_open_percent=100,
                captured_at="2026-03-01T08:15:00Z",
            ),
        ],
    )

    report = build_monthly_allocation(payload)

    total_share = sum(item.share_percent for item in report.allocations)
    assert round(total_share, 2) == 100.0
    assert report.allocations[0].owner_name == "Alice"
