from collections import defaultdict
from datetime import datetime, timezone

from app.models.schemas import AllocationInput, MonthlyAllocationReport, PersonAllocation, ZoneEffort


def compute_running_state_factor(running_state: str) -> float:
    normalized = running_state.strip().lower()
    if normalized == "heat":
        return 1.0
    if normalized == "idle":
        return 0.0
    return 0.5


def compute_duty_cycle_factor(duty_cycle_percent: float | None, valve_open_percent: float) -> float:
    if duty_cycle_percent is None:
        return max(min(valve_open_percent, 100.0), 0.0) / 100.0
    return max(min(duty_cycle_percent, 100.0), 0.0) / 100.0


def compute_demand_factor(valve_open_percent: float, running_state: str = "", duty_cycle_percent: float | None = None) -> float:
    valve_factor = max(min(valve_open_percent, 100.0), 0.0) / 100.0
    running_state_factor = compute_running_state_factor(running_state)
    duty_cycle_factor = compute_duty_cycle_factor(duty_cycle_percent, valve_open_percent)
    return (0.55 * valve_factor) + (0.25 * running_state_factor) + (0.20 * duty_cycle_factor)


def compute_effort(
    delta_c: float,
    surface_m2: float,
    valve_open_percent: float,
    running_state: str = "",
    duty_cycle_percent: float | None = None,
) -> float:
    bounded_delta = max(delta_c, 0.0)
    demand_factor = compute_demand_factor(valve_open_percent, running_state, duty_cycle_percent)
    return bounded_delta * surface_m2 * demand_factor


def build_monthly_allocation(payload: AllocationInput) -> MonthlyAllocationReport:
    zone_efforts: list[ZoneEffort] = []
    per_owner_effort: dict[str, float] = defaultdict(float)
    per_owner_surface: dict[str, float] = defaultdict(float)
    per_owner_zone_count: dict[str, int] = defaultdict(int)

    for sample in payload.samples:
        delta_c = max(sample.target_temperature_c - sample.current_temperature_c, 0.0)
        valve_factor = sample.valve_open_percent / 100.0
        running_state_factor = compute_running_state_factor(sample.running_state)
        duty_cycle_factor = compute_duty_cycle_factor(sample.duty_cycle_percent, sample.valve_open_percent)
        demand_factor = compute_demand_factor(sample.valve_open_percent, sample.running_state, sample.duty_cycle_percent)
        effort_score = compute_effort(
            delta_c,
            sample.surface_m2,
            sample.valve_open_percent,
            sample.running_state,
            sample.duty_cycle_percent,
        )

        zone_efforts.append(
            ZoneEffort(
                trv_id=sample.trv_id,
                zone_label=sample.zone_label,
                owner_name=sample.owner_name,
                surface_m2=sample.surface_m2,
                delta_c=round(delta_c, 2),
                valve_factor=round(valve_factor, 3),
                running_state=sample.running_state or "unknown",
                running_state_factor=round(running_state_factor, 3),
                duty_cycle_percent=(round(sample.duty_cycle_percent, 1) if sample.duty_cycle_percent is not None else None),
                duty_cycle_factor=round(duty_cycle_factor, 3),
                demand_factor=round(demand_factor, 3),
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
