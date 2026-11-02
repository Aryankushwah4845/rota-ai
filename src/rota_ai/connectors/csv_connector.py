"""Turns rows of staff and shift data into engine objects, checking them on the way.

The rows can come from a CSV file or from a table on screen. The checks matter: a
typo like "Monday" instead of "Mon" would otherwise be ignored, and that person
could be rostered on a day they can't work.
"""

import csv
from collections.abc import Iterable
from pathlib import Path

from rota_ai.engine.models import DAYS, ROLES, Shift, Staff

STAFF_COLUMNS = ("name", "role", "contracted_hours", "unavailable_days")
SHIFT_COLUMNS = ("day", "shift", "start_hour", "end_hour", *ROLES)


def _check_columns(row: dict, columns: tuple[str, ...], table: str) -> None:
    missing = [column for column in columns if column not in row]
    if missing:
        raise ValueError(f"The {table} table is missing these columns: {', '.join(missing)}")


def _cell(row: dict, column: str) -> str:
    # A row that is too short gives None for its missing cells.
    return (row[column] or "").strip()


def _whole_number(row: dict, column: str, where: str, maximum: int | None = None) -> int:
    text = _cell(row, column)
    if not text.isdigit() or (maximum is not None and int(text) > maximum):
        limit = f" from 0 to {maximum}" if maximum is not None else ""
        raise ValueError(f"{where}: {column} must be a whole number{limit}, but it is '{text}'")
    return int(text)


def staff_from_rows(rows: Iterable[dict]) -> list[Staff]:
    staff = []
    for number, row in enumerate(rows, start=1):
        _check_columns(row, STAFF_COLUMNS, "staff")
        name = _cell(row, "name")
        if not name:
            raise ValueError(f"Staff row {number} has no name")

        role = _cell(row, "role").lower()
        if role not in ROLES:
            raise ValueError(f"{name}: unknown role '{role}'. Use one of: {', '.join(ROLES)}")

        # Days are separated by ";", e.g. "Wed;Thu". The column may be empty.
        unavailable = {day.strip() for day in _cell(row, "unavailable_days").split(";") if day.strip()}
        unknown_days = unavailable - set(DAYS)
        if unknown_days:
            raise ValueError(
                f"{name}: unknown unavailable days {sorted(unknown_days)}. "
                f"Use {', '.join(DAYS)}, separated by ';'"
            )

        staff.append(Staff(name, role, _whole_number(row, "contracted_hours", name), unavailable))

    names = [person.name for person in staff]
    if len(names) != len(set(names)):
        raise ValueError(f"Staff names must be unique, got {', '.join(names)}")
    return staff


def shifts_from_rows(rows: Iterable[dict]) -> list[Shift]:
    shifts = []
    for number, row in enumerate(rows, start=1):
        _check_columns(row, SHIFT_COLUMNS, "shifts")
        day = _cell(row, "day")
        if day not in DAYS:
            raise ValueError(f"Shift row {number}: unknown day '{day}'. Use one of: {', '.join(DAYS)}")
        name = _cell(row, "shift")
        if not name:
            raise ValueError(f"Shift row {number} has no shift name")

        where = f"{day} {name}"
        shifts.append(
            Shift(
                day=day,
                name=name,
                start_hour=_whole_number(row, "start_hour", where, maximum=24),
                end_hour=_whole_number(row, "end_hour", where, maximum=24),
                needs={role: _whole_number(row, role, where) for role in ROLES},
            )
        )

    keys = [(shift.day, shift.name) for shift in shifts]
    if len(keys) != len(set(keys)):
        raise ValueError("Each day and shift may only appear once, but one is listed twice")
    return shifts


def load_staff(path: Path) -> list[Staff]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return staff_from_rows(csv.DictReader(file))


def load_shifts(path: Path) -> list[Shift]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return shifts_from_rows(csv.DictReader(file))
