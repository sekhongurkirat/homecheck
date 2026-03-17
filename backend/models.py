from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Priority(str, Enum):
    highway = "highway"
    rail = "rail"
    industrial = "industrial"
    meat_processing = "meat_processing"
    landfill = "landfill"
    airport = "airport"


# Default distance thresholds in metres.
DEFAULT_THRESHOLDS: dict[Priority, int] = {
    Priority.highway: 300,
    Priority.rail: 300,
    Priority.industrial: 500,
    Priority.meat_processing: 1000,
    Priority.landfill: 1000,
    Priority.airport: 3000,
}


class ReportRequest(BaseModel):
    address: str = Field(..., description="Full street address to evaluate.")
    priorities: list[Priority] = Field(
        default_factory=lambda: list(Priority),
        description="Which hazard categories to check.",
    )
    thresholds: dict[Priority, int] = Field(
        default_factory=lambda: dict(DEFAULT_THRESHOLDS),
        description="Per-priority distance threshold in metres.",
    )

    model_config = {"use_enum_values": True}


class HazardFlag(BaseModel):
    priority: Priority
    status: str = Field(..., pattern="^(red|yellow|green)$")
    distance_m: float
    threshold_m: int
    name: str | None = None
    subcategory: str
    source: str
    geojson: dict[str, Any]


class FloodZone(BaseModel):
    zone_code: str
    flood_label: str
    in_zone: bool


class School(BaseModel):
    name: str
    rating: int | None = None
    distance_m: float


class DevelopmentFlag(BaseModel):
    dev_type: str
    status: str
    distance_m: float
    name: str | None = None
    formed_year: int | None = None
    last_bond_year: int | None = None
    bond_amount_usd: int | None = None
    summary: str
    geojson: dict[str, Any]


class ReportResponse(BaseModel):
    address: str
    lat: float
    lng: float
    flags: list[HazardFlag]
    flood_zone: FloodZone | None = None
    school: School | None = None
    development: list[DevelopmentFlag] = Field(default_factory=list)
