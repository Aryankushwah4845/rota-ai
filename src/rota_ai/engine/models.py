"""The shared vocabulary of the engine: what a staff member, shift and rota are."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from rota_ai.rules.base import RulesPack

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKEND_DAYS = ("Sat", "Sun")
SUNDAY = "Sun"
ROLES = ("barista", "cashier", "supervisor")
SUPERVISOR = "supervisor"


def monday_of(day: date) -> date:
    """The Monday that starts the week containing this date."""
    return day - timedelta(days=day.weekday())


def next_monday(today: date) -> date:
    return monday_of(today) + timedelta(days=7)


def date_of(week_start: date, day: str) -> date:
    return week_start + timedelta(days=DAYS.index(day))


def day_heading(week_start: date, day: str) -> str:
    """For example "Mon 9 Nov"."""
    this_date = date_of(week_start, day)
    return f"{day} {this_date.day} {this_date:%b}"


@dataclass
class Staff:
    name: str
    role: str
    contracted_hours: int
    unavailable_days: set[str]
    date_of_birth: date
    opted_out_48h: bool = False
    sunday_opt_out: bool = False
    hourly_rate: float | None = None
    time_off: set[date] = field(default_factory=set)  # specific dates, e.g. a holiday


@dataclass
class Shift:
    day: str
    name: str  # e.g. "Morning"
    start_hour: int
    end_hour: int
    needs: dict[str, int]  # how many people of each role, e.g. {"barista": 1}

    @property
    def hours(self) -> int:
        return (self.end_hour - self.start_hour) % 24

    @property
    def label(self) -> str:
        return f"{self.name} {self.start_hour}-{self.end_hour}"

    @property
    def clock_label(self) -> str:
        """For example "15:00-23:00"."""
        return f"{self.start_hour:02d}:00-{self.end_hour % 24:02d}:00"

    @property
    def starts_at(self) -> int:
        """Hours since the start of Monday, so shifts on any days can be compared."""
        return DAYS.index(self.day) * 24 + self.start_hour

    @property
    def ends_at(self) -> int:
        return self.starts_at + self.hours

    @property
    def clock_hours(self) -> set[int]:
        """Each hour of the day this shift covers. A 22-2 shift gives {22, 23, 0, 1}."""
        return {(self.start_hour + hour) % 24 for hour in range(self.hours)}

    @property
    def day_numbers(self) -> range:
        """Days this shift touches, Monday being 0. An overnight Sunday shift reaches 7."""
        last_hour_worked = self.starts_at + max(self.hours, 1) - 1
        return range(self.starts_at // 24, last_hour_worked // 24 + 1)


@dataclass
class Rota:
    """A finished rota. Each assignment is one person working one shift."""

    staff: list[Staff]
    shifts: list[Shift]
    assignments: list[tuple[str, Shift]]  # (staff name, shift)
    is_optimal: bool  # True if the solver proved nothing scores better
    week_start: date  # the Monday this rota starts on
    rules: RulesPack

    def shifts_for(self, name: str) -> list[Shift]:
        return [shift for person, shift in self.assignments if person == name]

    def hours_for(self, name: str) -> int:
        return sum(shift.hours for shift in self.shifts_for(name))

    def weekend_shifts_for(self, name: str) -> int:
        return sum(shift.day in WEEKEND_DAYS for shift in self.shifts_for(name))
