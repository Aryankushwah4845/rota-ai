"""Saves a finished rota as an Excel file: staff as rows, days as columns.

Rotas often get pinned up for staff to see, so dates of birth and pay stay out of it.
"""

from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from rota_ai.engine.compliance import break_minutes
from rota_ai.engine.models import DAYS, Rota, date_of, day_heading

OFF = "Off"
UNAVAILABLE = "Unavailable"
TIME_OFF = "Time off"

MORNING_COLOUR = "FFF2CC"
EVENING_COLOUR = "D9E2F3"
OTHER_SHIFT_COLOUR = "E2EFDA"
UNAVAILABLE_COLOUR = "D9D9D9"
TIME_OFF_COLOUR = "F8CBAD"
HEADER_FILL = PatternFill("solid", fgColor="1F3864")


def rota_file_name(week_start: date) -> str:
    return f"rota_{week_start.isoformat()}.xlsx"


def rota_headers(week_start: date) -> list[str]:
    days = [day_heading(week_start, day) for day in DAYS]
    return ["Name", "Role", *days, "Hours", "Contract", "Weekend shifts"]


def day_cell_colour(text: str) -> str | None:
    """The background colour for a day cell, or None for no colour (a day off)."""
    if text == OFF:
        return None
    if text == UNAVAILABLE:
        return UNAVAILABLE_COLOUR
    if text == TIME_OFF:
        return TIME_OFF_COLOUR
    if text.startswith("Morning"):
        return MORNING_COLOUR
    if text.startswith("Evening"):
        return EVENING_COLOUR
    return OTHER_SHIFT_COLOUR


def rota_rows(rota: Rota) -> list[list]:
    """One row per person, in the same order as rota_headers."""
    rows = []
    for person in rota.staff:
        day_cells = []
        for day in DAYS:
            todays_shifts = [s for s in rota.shifts_for(person.name) if s.day == day]
            if todays_shifts:
                shift = todays_shifts[0]
                minutes = break_minutes(person, shift, rota.week_start, rota.rules)
                day_cells.append(f"{shift.label} ({minutes} min break)" if minutes else shift.label)
            elif date_of(rota.week_start, day) in person.time_off:
                day_cells.append(TIME_OFF)
            elif day in person.unavailable_days:
                day_cells.append(UNAVAILABLE)
            else:
                day_cells.append(OFF)
        rows.append(
            [
                person.name,
                person.role.capitalize(),
                *day_cells,
                rota.hours_for(person.name),
                person.contracted_hours,
                rota.weekend_shifts_for(person.name),
            ]
        )
    return rows


def rota_to_excel_bytes(rota: Rota) -> bytes:
    """Builds the Excel file in memory, ready to save or download."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rota"

    sheet.append(rota_headers(rota.week_start))
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    for row in rota_rows(rota):
        sheet.append(row)

    # Colour each day cell by its text. Day columns start after Name and Role.
    for row in sheet.iter_rows(min_row=2, min_col=3, max_col=2 + len(DAYS)):
        for cell in row:
            cell.alignment = Alignment(horizontal="center")
            colour = day_cell_colour(cell.value)
            if colour:
                cell.fill = PatternFill("solid", fgColor=colour)

    for column in sheet.columns:
        longest = max(len(str(cell.value)) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = longest + 3

    # Keep the names and day headings on screen while scrolling.
    sheet.freeze_panes = "C2"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def save_rota_to_excel(rota: Rota, path: Path) -> None:
    content = rota_to_excel_bytes(rota)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
