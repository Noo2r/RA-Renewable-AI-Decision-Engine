"""Station domain model + a small fixed registry of demo stations.

RA (Part 1) supports exactly three synthetic demo stations. This registry
is intentionally a flat dict, not a database table or plugin system --
station configuration is static, code-defined data for this phase of the
project.

IMPORTANT -- these are demo stations, not real facilities:
  * Names ("RA South Solar Demo", etc.) are illustrative demo names.
  * Latitude/longitude are approximate regional placeholders (Southern
    Egypt, the Gulf of Suez area, Upper Egypt), not surveyed plant
    coordinates.
  * All capacities, demand, and battery figures are synthetic values
    chosen to be in the same scale as the original single-station MVP.
  * Nothing in this module represents official plant data.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StationConfig:
    """Static configuration for one synthetic station.

    Only fields actually used by the generator/decision engine are
    included -- see ra_core.data_generator.generate_series and
    ra_core.decision_engine.evaluate for how each field is consumed.
    """

    id: str
    name: str
    energy_type: str  # "solar" | "wind" | "hybrid"
    latitude: float
    longitude: float

    solar_capacity_kw: float
    wind_capacity_kw: float
    battery_capacity_kwh: float

    demand_scale: float
    seed_offset: int

    def public_dict(self) -> dict:
        """Fields safe to expose over the API (excludes seed_offset)."""
        return {
            "id": self.id,
            "name": self.name,
            "energy_type": self.energy_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "solar_capacity_kw": self.solar_capacity_kw,
            "wind_capacity_kw": self.wind_capacity_kw,
            "battery_capacity_kwh": self.battery_capacity_kwh,
            "data_source": "synthetic",
        }


class UnknownStationError(KeyError):
    """Raised when a station_id doesn't match any registered station."""

    def __init__(self, station_id: str):
        super().__init__(station_id)
        self.station_id = station_id

    def __str__(self):
        return f"Unknown station '{self.station_id}'. Options: {list(STATION_IDS)}"


DEFAULT_STATION_ID = "hybrid-01"

# Registration order doubles as the display order for GET /stations.
# Capacities/demand_scale/battery for hybrid-01 intentionally match the
# original single-station MVP's global constants exactly (SOLAR_CAPACITY_KW,
# WIND_CAPACITY_KW, BATTERY_CAPACITY_KWH, implicit demand_scale=1.0, and
# seed_offset=0) so that generate_series(scenario) with no station argument
# continues to produce byte-identical output to the Part 0 baseline.
_STATIONS: dict[str, StationConfig] = {
    "solar-01": StationConfig(
        id="solar-01",
        name="RA South Solar Demo",
        energy_type="solar",
        latitude=24.45,
        longitude=32.73,
        solar_capacity_kw=55.0,
        wind_capacity_kw=0.0,
        battery_capacity_kwh=35.0,
        demand_scale=0.6,
        seed_offset=101,
    ),
    "wind-01": StationConfig(
        id="wind-01",
        name="RA Gulf Wind Demo",
        energy_type="wind",
        latitude=29.50,
        longitude=32.50,
        solar_capacity_kw=0.0,
        wind_capacity_kw=32.0,
        battery_capacity_kwh=35.0,
        demand_scale=0.55,
        seed_offset=202,
    ),
    "hybrid-01": StationConfig(
        id="hybrid-01",
        name="RA Hybrid Energy Hub",
        energy_type="hybrid",
        latitude=27.18,
        longitude=31.17,
        solar_capacity_kw=40.0,
        wind_capacity_kw=15.0,
        battery_capacity_kwh=50.0,
        demand_scale=1.0,
        seed_offset=0,
    ),
}

STATION_IDS: tuple[str, ...] = tuple(_STATIONS.keys())

assert DEFAULT_STATION_ID in _STATIONS, "DEFAULT_STATION_ID must be a registered station"


def get_station(station_id: str) -> StationConfig:
    try:
        return _STATIONS[station_id]
    except KeyError:
        raise UnknownStationError(station_id) from None


def list_stations() -> list[StationConfig]:
    return list(_STATIONS.values())
