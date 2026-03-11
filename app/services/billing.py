from app.core.config import BILLING_ECS_WEIGHT, BILLING_HEATING_WEIGHT
from app.models.schemas import EcsAllocationRun, MonthlyAllocationReport


def build_combined_allocation_rows(report: MonthlyAllocationReport, ecs_allocation: EcsAllocationRun | None = None) -> list[dict[str, object]]:
    heating_index = {allocation.owner_name.lower(): allocation for allocation in report.allocations}
    ecs_index = {}
    if ecs_allocation is not None:
        ecs_index = {item.owner_name.lower(): item for item in ecs_allocation.allocations}

    owner_names = sorted(set(heating_index) | set(ecs_index))
    total_bill_amount = ecs_allocation.total_amount if ecs_allocation is not None else 0.0
    rows: list[dict[str, object]] = []
    for owner_name in owner_names:
        allocation = heating_index.get(owner_name)
        ecs_line = ecs_index.get(owner_name)
        display_name = allocation.owner_name if allocation is not None else ecs_line.owner_name
        heating_share_percent = allocation.share_percent if allocation else 0.0
        ecs_share_percent = ecs_line.share_percent if ecs_line else 0.0
        heating_component_amount = round(total_bill_amount * BILLING_HEATING_WEIGHT * (heating_share_percent / 100.0), 2)
        ecs_component_amount = round(total_bill_amount * BILLING_ECS_WEIGHT * (ecs_share_percent / 100.0), 2)
        combined_share_percent = round(
            (heating_share_percent * BILLING_HEATING_WEIGHT) + (ecs_share_percent * BILLING_ECS_WEIGHT),
            2,
        )
        combined_allocated_amount = round(heating_component_amount + ecs_component_amount, 2)
        rows.append(
            {
                "owner_name": display_name,
                "heating_share_percent": heating_share_percent,
                "heating_score": (allocation.total_effort_score if allocation else 0.0),
                "tracked_surface_m2": (allocation.tracked_surface_m2 if allocation else 0.0),
                "heating_component_amount": heating_component_amount,
                "ecs_share_percent": ecs_share_percent,
                "ecs_component_amount": ecs_component_amount,
                "ecs_delta_m3": (ecs_line.delta_m3 if ecs_line else 0.0),
                "combined_share_percent": combined_share_percent,
                "combined_allocated_amount": combined_allocated_amount,
            }
        )
    return rows