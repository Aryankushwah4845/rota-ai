"""The shape of a "rules pack": every legal value the engine needs from a country.

The engine only ever reads these settings, so a new country needs a new file
like uk.py and no changes to the engine.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WageBand:
    min_age: int
    label: str  # e.g. "18-20"
    hourly_rate: float


@dataclass(frozen=True)
class WageRates:
    effective_from: date
    bands: tuple[WageBand, ...]
    apprentice_rate: float


@dataclass(frozen=True)
class RulesPack:
    name: str

    # Who counts as what, by age on the first day of the week.
    minimum_age: int  # younger than this: never rostered
    adult_age: int  # from minimum_age up to here: a young worker

    # Adults
    adult_min_rest_hours: int
    adult_days_off_per_week: int
    adult_max_weekly_hours: int  # can be lifted by the person's opt-out
    adult_break_after_hours: float
    adult_break_minutes: int

    # Young workers
    young_max_daily_hours: int
    young_max_weekly_hours: int  # no opt-out
    young_min_rest_hours: int
    young_consecutive_days_off: int
    young_break_after_hours: float
    young_break_minutes: int
    young_night_start_hour: int
    young_night_end_hour: int
    young_sector_exception: bool  # True: only the hours below are banned
    young_sector_ban_start_hour: int
    young_sector_ban_end_hour: int

    # Pay. The newest rates that have started by the rota's week are used.
    minimum_wages: tuple[WageRates, ...]
