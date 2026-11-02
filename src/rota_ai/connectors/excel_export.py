"""Saves a finished rota as an Excel file: staff as rows, days as columns."""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from rota_ai.engine.models import DAYS, Rota

OFF = "Off"
UNAVAILABLE = "Unavailable"
ROTA_HEADERS = ["Name", "Role", *DAYS, "Hours", "Contract", "Weekend shifts"]

MORNING_COLOUR = "FFF2CC"
EVENING_COLOUR = "D9E2F3"
OTHER_SHIFT_COLOUR = "E2EFDA"
UNAVAILABLE_COLOUR = "D9D9D9"
HEADER_FILL = PatternFill("solid", fgColor="1F3864")


def day_cell_colour(text: str) -> str | None:
    """The background colour for a day cell, or None for no colour (a day off)."""
    if text == OFF:
        return None
    if text == UNAVAILABLE:
        return UNAVAILABLE_COLOUR
    if text.startswith("Morning"):
        return MORNING_COLOUR
    if text.startswith("Evening"):
        return EVENING_COLOUR
    return OTHER_SHIFT_COLOUR


def rota_rows(rota: Rota) -> list[list]:
    """One row per person, in the same order as ROTA_HEADERS."""
    rows = []
    for person in rota.staff:
        day_cells = []
        for day in DAYS:
            todays_shifts = [s for s in rota.shifts_for(person.name) if s.day == day]
            if todays_shifts:
                day_cells.append(todays_shifts[0].label)
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

    sheet.append(ROTA_HEADERS)
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
