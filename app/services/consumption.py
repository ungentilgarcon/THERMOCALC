from collections import defaultdict
from datetime import datetime, timezone

from app.models.schemas import AllocationInput, MonthlyAllocationReport, PersonAllocation, ZoneEffort


def compute_effort(delta_c: float, surface_m2: float, valve_open_percent: float) -> float:
    bounded_delta = max(delta_c, 0.0)
    valve_factor = max(min(valve_open_percent, 100.0), 0.0) / 100.0
    return bounded_delta * surface_m2 * valve_factor


def build_monthly_allocation(payload: AllocationInput) -> MonthlyAllocationReport:
    zone_efforts: list[ZoneEffort] = []
    per_owner_effort: dict[str, float] = defaultdict(float)
    per_owner_surface: dict[str, float] = defaultdict(float)
    per_owner_zone_count: dict[str, int] = defaultdict(int)

    for sample in payload.samples:
        delta_c = max(sample.target_temperature_c - sample.current_temperature_c, 0.0)
        valve_factor = sample.valve_open_percent / 100.0
        effort_score = compute_effort(delta_c, sample.surface_m2, sample.valve_open_percent)

        zone_efforts.append(
            ZoneEffort(
                trv_id=sample.trv_id,
                zone_label=sample.zone_label,
                owner_name=sample.owner_name,
                surface_m2=sample.surface_m2,
                delta_c=round(delta_c, 2),
                valve_factor=round(valve_factor, 3),
                effort_score=round(effort_score, 3),
            )
        )
        per_owner_effort[sample.owner_name] += effort_score
        per_owner_surface[sample.owner_name] += sample.surface_m2
        per_owner_zone_count[sample.owner_name] += 1

    total_effort = sum(per_owner_effort.values())
    allocations = []
    for owner_name, owner_effort in sorted(per_owner_effort.items()):
        share_percent = 0.0 if total_effort == 0 else (owner_effort / total_effort) * 100.0
        allocations.append(
            PersonAllocation(
                owner_name=owner_name,
                total_effort_score=round(owner_effort, 3),
                share_percent=round(share_percent, 2),
                tracked_surface_m2=round(per_owner_surface[owner_name], 2),
                zone_count=per_owner_zone_count[owner_name],
            )
        )

    return MonthlyAllocationReport(
        month_label=payload.month_label,
        generated_at=datetime.now(timezone.utc),
        allocations=allocations,
        zones=zone_efforts,
    )
