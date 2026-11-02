"""Reads staff and shifts from CSV files and turns them into engine objects.

The checks here matter: a typo like "Monday" instead of "Mon" would otherwise be
ignored, and that person could be rostered on a day they can't work.
"""

import csv
from pathlib import Path

from rota_ai.engine.models import DAYS, ROLES, Shift, Staff


def load_staff(path: Path) -> list[Staff]:
    staff = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            name = row["name"].strip()
            role = row["role"].strip().lower()
            if role not in ROLES:
                raise ValueError(f"{name}: unknown role '{role}', expected one of {ROLES}")

            # Days are separated by ";", e.g. "Wed;Thu". The column may be empty.
            unavailable = {day.strip() for day in row["unavailable_days"].split(";") if day.strip()}
            unknown_days = unavailable - set(DAYS)
            if unknown_days:
                raise ValueError(f"{name}: unknown days {sorted(unknown_days)}, expected {DAYS}")

            staff.append(Staff(name, role, int(row["contracted_hours"]), unavailable))

    names = [person.name for person in staff]
    if len(names) != len(set(names)):
        raise ValueError(f"Staff names must be unique, got {names}")
    return staff


def load_shifts(path: Path) -> list[Shift]:
    shifts = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            day = row["day"].strip()
            if day not in DAYS:
                raise ValueError(f"Unknown day '{day}', expected one of {DAYS}")
            shifts.append(
                Shift(
                    day=day,
                    name=row["shift"].strip(),
                    start_hour=int(row["start_hour"]),
                    end_hour=int(row["end_hour"]),
                    needs={role: int(row[role]) for role in ROLES},
                )
            )

    keys = [(shift.day, shift.name) for shift in shifts]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Each day and shift may only appear once, got {keys}")
    return shifts
