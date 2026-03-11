from datetime import datetime, timezone

from app.models.schemas import AllocationInput, ThermostatSample


def _sample(
    trv_id: str,
    zone_label: str,
    owner_name: str,
    surface_m2: float,
    target_temperature_c: float,
    current_temperature_c: float,
    valve_open_percent: float,
    running_state: str,
    duty_cycle_percent: float | None,
) -> ThermostatSample:
    return ThermostatSample(
        trv_id=trv_id,
        zone_label=zone_label,
        owner_name=owner_name,
        surface_m2=surface_m2,
        target_temperature_c=target_temperature_c,
        current_temperature_c=current_temperature_c,
        valve_open_percent=valve_open_percent,
        running_state=running_state,
        duty_cycle_percent=duty_cycle_percent,
        captured_at=datetime.now(timezone.utc),
    )


def list_test_scenarios() -> list[dict[str, str]]:
    return [
        {
            "key": "balanced",
            "label": "Appartement equilibre",
            "description": "Deux occupants avec des besoins proches et une chauffe moderee.",
        },
        {
            "key": "living_room_peak",
            "label": "Pointe sur salon",
            "description": "Une grande zone salon absorbe l'essentiel de la demande.",
        },
        {
            "key": "night_setback",
            "label": "Abaissement nocturne",
            "description": "Retour de chauffe apres baisse nocturne avec deltas eleves.",
        },
    ]


def build_test_payload(scenario_key: str) -> AllocationInput:
    if scenario_key == "living_room_peak":
        return AllocationInput(
            month_label="Scenario salon",
            samples=[
                _sample("trv-salon-1", "Salon", "Alice", 34.0, 22.0, 18.3, 82.0, "heat", 88.0),
                _sample("trv-salon-2", "Salon baie", "Alice", 18.0, 21.5, 18.7, 76.0, "heat", 80.0),
                _sample("trv-chambre-1", "Chambre", "Benoit", 15.0, 19.0, 18.6, 22.0, "idle", 15.0),
            ],
        )
    if scenario_key == "night_setback":
        return AllocationInput(
            month_label="Scenario nuit",
            samples=[
                _sample("trv-suite", "Suite", "Alice", 24.0, 20.5, 16.9, 74.0, "heat", 72.0),
                _sample("trv-bureau", "Bureau", "Alice", 11.0, 19.5, 17.5, 48.0, "heat", 44.0),
                _sample("trv-enfant", "Chambre enfant", "Benoit", 14.0, 20.0, 17.2, 65.0, "heat", 61.0),
                _sample("trv-couloir", "Couloir", "Benoit", 9.0, 17.0, 16.6, 10.0, "idle", 5.0),
            ],
        )
    return AllocationInput(
        month_label="Scenario equilibre",
        samples=[
            _sample("trv-salon", "Salon", "Alice", 22.0, 21.0, 19.2, 56.0, "heat", 59.0),
            _sample("trv-chambre", "Chambre", "Alice", 13.0, 19.0, 18.2, 28.0, "idle", 20.0),
            _sample("trv-cuisine", "Cuisine", "Benoit", 16.0, 20.0, 18.7, 46.0, "heat", 40.0),
            _sample("trv-bureau", "Bureau", "Benoit", 12.0, 19.5, 18.6, 35.0, "idle", 26.0),
        ],
    )


def build_empty_payload(row_count: int = 3) -> AllocationInput:
    bounded_count = max(1, min(row_count, 12))
    samples = [
        _sample(
            trv_id=f"scenario-{index + 1}",
            zone_label="",
            owner_name="",
            surface_m2=10.0,
            target_temperature_c=20.0,
            current_temperature_c=19.0,
            valve_open_percent=0.0,
            running_state="idle",
            duty_cycle_percent=0.0,
        )
        for index in range(bounded_count)
    ]
    return AllocationInput(month_label="Scenario manuel", samples=samples)


def build_rows(payload: AllocationInput) -> list[dict[str, object]]:
    return [
        {
            "trv_id": sample.trv_id,
            "zone_label": sample.zone_label,
            "owner_name": sample.owner_name,
            "surface_m2": sample.surface_m2,
            "target_temperature_c": sample.target_temperature_c,
            "current_temperature_c": sample.current_temperature_c,
            "valve_open_percent": sample.valve_open_percent,
            "running_state": sample.running_state or "unknown",
            "duty_cycle_percent": sample.duty_cycle_percent if sample.duty_cycle_percent is not None else 0.0,
        }
        for sample in payload.samples
    ]