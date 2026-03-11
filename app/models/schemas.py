from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ThermostatSample(BaseModel):
    trv_id: str
    zone_label: str
    owner_name: str
    surface_m2: float = Field(gt=0)
    target_temperature_c: float
    current_temperature_c: float
    valve_open_percent: float = Field(ge=0, le=100)
    captured_at: datetime


class AllocationInput(BaseModel):
    month_label: str
    samples: list[ThermostatSample]


class ZoneEffort(BaseModel):
    trv_id: str
    zone_label: str
    owner_name: str
    surface_m2: float
    delta_c: float
    valve_factor: float
    effort_score: float


class PersonAllocation(BaseModel):
    owner_name: str
    total_effort_score: float
    share_percent: float
    tracked_surface_m2: float
    zone_count: int


class MonthlyAllocationReport(BaseModel):
    month_label: str
    generated_at: datetime
    allocations: list[PersonAllocation]
    zones: list[ZoneEffort]
    methodology: Literal["delta-surface-valve-v1"] = "delta-surface-valve-v1"


class Occupant(BaseModel):
    owner_name: str = Field(min_length=1)
    notes: str = ""


class ThermostatAssignment(BaseModel):
    trv_id: str = Field(min_length=1)
    zone_label: str = Field(min_length=1)
    owner_name: str = Field(min_length=1)
    surface_m2: float = Field(gt=0)


class ZigbeeController(BaseModel):
    controller_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    provider_type: Literal["mock", "zigbee2mqtt"] = "mock"
    endpoint_url: str = ""
    mqtt_username: str = ""
    mqtt_password: str = ""
    base_topic: str = "zigbee2mqtt"
    auto_discovery_enabled: bool = False
    discovery_interval_minutes: int = Field(default=15, ge=1, le=1440)
    last_discovery_at: datetime | None = None
    last_discovery_status: str = ""
    notes: str = ""
    enabled: bool = True


class ZigbeeEndpoint(BaseModel):
    device_id: str = Field(min_length=1)
    controller_id: str = Field(min_length=1)
    role: Literal["thermostat", "detector", "receiver"]
    friendly_name: str = Field(min_length=1)
    model: str = ""
    ieee_address: str = ""
    owner_name: str = ""
    zone_label: str = ""
    surface_m2: float | None = Field(default=None, gt=0)
    enabled: bool = True


class ZigbeePairingLink(BaseModel):
    link_id: str = Field(min_length=1)
    controller_id: str = Field(min_length=1)
    source_device_id: str = Field(min_length=1)
    target_device_id: str = Field(min_length=1)
    relation_type: Literal["detector-to-receiver", "detector-to-thermostat", "thermostat-to-receiver"]
    notes: str = ""
    enabled: bool = True


class PdfScheduleConfig(BaseModel):
    enabled: bool = False
    day_of_month: int = Field(default=1, ge=1, le=28)
    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    output_dir: str = "generated_reports"
    last_generated_month: str | None = None


class AdminState(BaseModel):
    occupants: list[Occupant] = Field(default_factory=list)
    thermostats: list[ThermostatAssignment] = Field(default_factory=list)
    schedule: PdfScheduleConfig = Field(default_factory=PdfScheduleConfig)
    controllers: list[ZigbeeController] = Field(default_factory=list)
    zigbee_devices: list[ZigbeeEndpoint] = Field(default_factory=list)
    zigbee_pairings: list[ZigbeePairingLink] = Field(default_factory=list)


class ArchiveAllocationSnapshot(BaseModel):
    owner_name: str
    share_percent: float
    total_effort_score: float


class ArchiveRecord(BaseModel):
    filename: str
    display_name: str
    month_label: str
    generated_at: datetime
    owners: list[ArchiveAllocationSnapshot] = Field(default_factory=list)


class ArchiveIndex(BaseModel):
    archives: list[ArchiveRecord] = Field(default_factory=list)
