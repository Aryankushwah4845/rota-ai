"""Checks that bad CSV files are rejected and the Excel file is laid out correctly."""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from rota_ai.connectors.csv_connector import load_shifts, load_staff
from rota_ai.connectors.excel_export import OFF, UNAVAILABLE, save_rota_to_excel
from rota_ai.engine.models import DAYS
from rota_ai.engine.solver import solve_rota

SAMPLE = Path(__file__).parent.parent / "data" / "sample"
STAFF_HEADER = "name,role,contracted_hours,unavailable_days\n"
SHIFTS_HEADER = "day,shift,start_hour,end_hour,barista,cashier,supervisor\n"


def write_csv(tmp_path, text):
    path = tmp_path / "input.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_misspelled_unavailable_day_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + "Kim,barista,40,Monday\n")
    with pytest.raises(ValueError, match="Monday"):
        load_staff(path)


def test_unknown_role_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + "Kim,chef,40,\n")
    with pytest.raises(ValueError, match="chef"):
        load_staff(path)


def test_empty_unavailable_days_means_always_available(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + "Kim,barista,40,\n")
    assert load_staff(path)[0].unavailable_days == set()


def test_duplicate_staff_name_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + "Kim,barista,40,\nKim,cashier,16,\n")
    with pytest.raises(ValueError, match="unique"):
        load_staff(path)


def test_duplicate_shift_is_rejected(tmp_path):
    row = "Mon,Morning,7,15,1,0,1\n"
    path = write_csv(tmp_path, SHIFTS_HEADER + row + row)
    with pytest.raises(ValueError, match="once"):
        load_shifts(path)


def test_missing_column_is_named(tmp_path):
    path = write_csv(tmp_path, "name,role\nKim,barista\n")
    with pytest.raises(ValueError, match="contracted_hours, unavailable_days"):
        load_staff(path)


def test_row_too_short_is_explained(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + "Kim,barista\n")
    with pytest.raises(ValueError, match="contracted_hours must be a whole number"):
        load_staff(path)


@pytest.mark.parametrize("hours", ["forty", "-8", "37.5", ""])
def test_bad_contracted_hours_are_rejected(tmp_path, hours):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,{hours},\n")
    with pytest.raises(ValueError, match="Kim: contracted_hours must be a whole number"):
        load_staff(path)


def test_shift_hour_past_midnight_is_rejected(tmp_path):
    path = write_csv(tmp_path, SHIFTS_HEADER + "Mon,Morning,7,25,1,0,1\n")
    with pytest.raises(ValueError, match="Mon Morning: end_hour must be a whole number from 0 to 24"):
        load_shifts(path)


@pytest.fixture(scope="module")
def rota():
    return solve_rota(load_staff(SAMPLE / "staff.csv"), load_shifts(SAMPLE / "shifts.csv"))


@pytest.fixture
def sheet(rota, tmp_path):
    path = tmp_path / "subfolder" / "rota.xlsx"
    save_rota_to_excel(rota, path)
    return load_workbook(path).active


def test_excel_has_staff_as_rows_and_days_as_columns(sheet, rota):
    headers = [cell.value for cell in sheet[1]]
    assert headers[:2] == ["Name", "Role"]
    assert headers[2:9] == list(DAYS)
    assert [row[0].value for row in sheet.iter_rows(min_row=2)] == [p.name for p in rota.staff]


def test_excel_cells_match_the_rota(sheet, rota):
    headers = [cell.value for cell in sheet[1]]
    for row, person in zip(sheet.iter_rows(min_row=2), rota.staff):
        for day in DAYS:
            cell = row[headers.index(day)].value
            todays = [s for s in rota.shifts_for(person.name) if s.day == day]
            if todays:
                assert cell == todays[0].label
            elif day in person.unavailable_days:
                assert cell == UNAVAILABLE
            else:
                assert cell == OFF
        assert row[headers.index("Hours")].value == rota.hours_for(person.name)
