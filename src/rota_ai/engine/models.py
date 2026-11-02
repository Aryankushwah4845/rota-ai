"""The shared vocabulary of the engine: what a staff member, shift and rota are."""

from dataclasses import dataclass

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKEND_DAYS = ("Sat", "Sun")
ROLES = ("barista", "cashier", "supervisor")
SUPERVISOR = "supervisor"


@dataclass
class Staff:
    name: str
    role: str
    contracted_hours: int
    unavailable_days: set[str]


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


@dataclass
class Rota:
    """A finished rota. Each assignment is one person working one shift."""

    staff: list[Staff]
    shifts: list[Shift]
    assignments: list[tuple[str, Shift]]  # (staff name, shift)
    is_optimal: bool  # True if the solver proved nothing scores better

    def shifts_for(self, name: str) -> list[Shift]:
        return [shift for person, shift in self.assignments if person == name]

    def hours_for(self, name: str) -> int:
        return sum(shift.hours for shift in self.shifts_for(name))

    def weekend_shifts_for(self, name: str) -> int:
        return sum(shift.day in WEEKEND_DAYS for shift in self.shifts_for(name))
