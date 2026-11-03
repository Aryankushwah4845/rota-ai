"""Turns rows of staff and shift data into engine objects, checking them on the way.

The rows can come from a CSV file or from a table on screen. The checks matter: a
typo like "Monday" instead of "Mon" would otherwise be ignored, and that person
could be rostered on a day they can't work.
"""

import csv
from collections.abc import Iterable
from datetime import date, datetime
from math import isfinite
from pathlib import Path

from rota_ai.engine.models import DAYS, ROLES, Shift, Staff

STAFF_COLUMNS = ("name", "role", "contracted_hours", "unavailable_days", "date_of_birth")
# These can be left out of a file, or left blank for anyone they don't apply to.
OPTIONAL_STAFF_COLUMNS = ("opted_out_48h", "sunday_opt_out", "hourly_rate")
# Excel often rewrites dates as day/month/year when it saves a CSV.
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
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


def _date_of_birth(row: dict, name: str) -> date:
    text = _cell(row, "date_of_birth")
    if not text:
        raise ValueError(
            f"{name}: date_of_birth is needed to apply the right legal rules for their age. "
            "Use a date like 2009-03-15"
        )
    for date_format in DATE_FORMATS:
        try:
            born = datetime.strptime(text, date_format).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"{name}: date_of_birth must be a date like 2009-03-15, but it is '{text}'")
    if born > date.today():
        raise ValueError(f"{name}: date_of_birth is in the future: '{text}'")
    return born


def _true_or_false(row: dict, column: str, name: str) -> bool:
    text = (row.get(column) or "").strip().lower()
    if text in ("", "false", "no"):
        return False
    if text in ("true", "yes"):
        return True
    raise ValueError(f"{name}: {column} must be true or false, but it is '{text}'")


def _hourly_rate(row: dict, name: str) -> float | None:
    text = (row.get("hourly_rate") or "").strip().removeprefix("£")
    if not text:
        return None
    try:
        rate = float(text)
    except ValueError:
        rate = -1
    if rate < 0 or not isfinite(rate):
        raise ValueError(f"{name}: hourly_rate must be an amount like 12.71, but it is '{text}'")
    return rate


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

        contracted_hours = _whole_number(row, "contracted_hours", name)
        staff.append(
            Staff(
                name,
                role,
                contracted_hours,
                unavailable,
                date_of_birth=_date_of_birth(row, name),
                opted_out_48h=_true_or_false(row, "opted_out_48h", name),
                sunday_opt_out=_true_or_false(row, "sunday_opt_out", name),
                hourly_rate=_hourly_rate(row, name),
            )
        )

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
