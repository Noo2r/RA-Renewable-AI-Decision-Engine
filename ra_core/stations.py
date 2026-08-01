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

Part 3 note: battery *operating* fields (charge/discharge rate limits,
min/max SoC, round-trip efficiencies) are added here so the decision
engine can compute physically valid charge/discharge amounts per station.
All three stations use the same simple, documented demo assumptions: a
0.5C charge/discharge rate (empties or fills in ~2 hours), a 10-95%
usable SoC band, and 95% efficiency in each direction (matching the
existing BATTERY_CHARGE_EFFICIENCY/BATTERY_DISCHARGE_EFFICIENCY constants
already used by the synthetic generator's SoC simulation). No battery
degradation, cycle-counting, temperature effects, state-of-health
estimation, or multiple batteries per station are modeled.
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

    # --- Part 3: battery operating constraints ------------------------
    battery_charge_limit_kw: float
    battery_discharge_limit_kw: float
    battery_min_soc_pct: float
    battery_max_soc_pct: float
    battery_charge_efficiency: float
    battery_discharge_efficiency: float

    def __post_init__(self):
        assert 0 <= self.battery_min_soc_pct < self.battery_max_soc_pct <= 100, self.id
        assert 0 < self.battery_charge_efficiency <= 1, self.id
        assert 0 < self.battery_discharge_efficiency <= 1, self.id
        assert self.battery_charge_limit_kw >= 0, self.id
        assert self.battery_discharge_limit_kw >= 0, self.id

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
            "battery_charge_limit_kw": self.battery_charge_limit_kw,
            "battery_discharge_limit_kw": self.battery_discharge_limit_kw,
            "battery_min_soc_pct": self.battery_min_soc_pct,
            "battery_max_soc_pct": self.battery_max_soc_pct,
            "battery_charge_efficiency": self.battery_charge_efficiency,
            "battery_discharge_efficiency": self.battery_discharge_efficiency,
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

# Shared Part 3 battery-operating demo assumptions (documented above):
# 0.5C charge/discharge rate, 10-95% usable SoC band, 95% round-trip
# efficiency each way -- identical across all three stations for
# simplicity; only battery_capacity_kwh (and therefore the absolute kW
# rate) differs per station.
_BATTERY_MIN_SOC_PCT = 10.0
_BATTERY_MAX_SOC_PCT = 95.0
_BATTERY_CHARGE_EFFICIENCY = 0.95
_BATTERY_DISCHARGE_EFFICIENCY = 0.95


def _rate_kw(capacity_kwh: float) -> float:
    """0.5C: the battery can fully charge/discharge in about 2 hours."""
    return capacity_kwh * 0.5


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
        battery_charge_limit_kw=_rate_kw(35.0),
        battery_discharge_limit_kw=_rate_kw(35.0),
        battery_min_soc_pct=_BATTERY_MIN_SOC_PCT,
        battery_max_soc_pct=_BATTERY_MAX_SOC_PCT,
        battery_charge_efficiency=_BATTERY_CHARGE_EFFICIENCY,
        battery_discharge_efficiency=_BATTERY_DISCHARGE_EFFICIENCY,
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
        battery_charge_limit_kw=_rate_kw(35.0),
        battery_discharge_limit_kw=_rate_kw(35.0),
        battery_min_soc_pct=_BATTERY_MIN_SOC_PCT,
        battery_max_soc_pct=_BATTERY_MAX_SOC_PCT,
        battery_charge_efficiency=_BATTERY_CHARGE_EFFICIENCY,
        battery_discharge_efficiency=_BATTERY_DISCHARGE_EFFICIENCY,
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
        battery_charge_limit_kw=_rate_kw(50.0),
        battery_discharge_limit_kw=_rate_kw(50.0),
        battery_min_soc_pct=_BATTERY_MIN_SOC_PCT,
        battery_max_soc_pct=_BATTERY_MAX_SOC_PCT,
        battery_charge_efficiency=_BATTERY_CHARGE_EFFICIENCY,
        battery_discharge_efficiency=_BATTERY_DISCHARGE_EFFICIENCY,
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
