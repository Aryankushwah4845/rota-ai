"""Saves a finished rota as an Excel file: staff as rows, days as columns."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from rota_ai.engine.models import DAYS, Rota

OFF = "Off"
UNAVAILABLE = "Unavailable"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
MORNING_FILL = PatternFill("solid", fgColor="FFF2CC")
EVENING_FILL = PatternFill("solid", fgColor="D9E2F3")
UNAVAILABLE_FILL = PatternFill("solid", fgColor="D9D9D9")


def save_rota_to_excel(rota: Rota, path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rota"

    sheet.append(["Name", "Role", *DAYS, "Hours", "Contract", "Weekend shifts"])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

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
        sheet.append(
            [
                person.name,
                person.role.capitalize(),
                *day_cells,
                rota.hours_for(person.name),
                person.contracted_hours,
                rota.weekend_shifts_for(person.name),
            ]
        )

    # Colour each day cell by its text. Day columns start after Name and Role.
    for row in sheet.iter_rows(min_row=2, min_col=3, max_col=2 + len(DAYS)):
        for cell in row:
            cell.alignment = Alignment(horizontal="center")
            if cell.value == UNAVAILABLE:
                cell.fill = UNAVAILABLE_FILL
            elif cell.value.startswith("Morning"):
                cell.fill = MORNING_FILL
            elif cell.value.startswith("Evening"):
                cell.fill = EVENING_FILL

    for column in sheet.columns:
        longest = max(len(str(cell.value)) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = longest + 3

    # Keep the names and day headings on screen while scrolling.
    sheet.freeze_panes = "C2"

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
