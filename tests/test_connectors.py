"""Checks that bad CSV files are rejected and the Excel file is laid out correctly."""

from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rota_ai.connectors.csv_connector import load_shifts, load_staff
from rota_ai.connectors.excel_export import OFF, UNAVAILABLE, rota_rows, save_rota_to_excel
from rota_ai.engine.models import DAYS, day_heading
from rota_ai.engine.solver import solve_rota
from rota_ai.rules.uk import UK_RULES

SAMPLE = Path(__file__).parent.parent / "data" / "sample"
WEEK = date(2026, 11, 9)
STAFF_HEADER = "name,role,contracted_hours,unavailable_days,date_of_birth\n"
BORN = "1990-01-01"
SHIFTS_HEADER = "day,shift,start_hour,end_hour,barista,cashier,supervisor\n"


def write_csv(tmp_path, text):
    path = tmp_path / "input.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_misspelled_unavailable_day_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,Monday,{BORN}\n")
    with pytest.raises(ValueError, match="Monday"):
        load_staff(path)


def test_unknown_role_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,chef,40,,{BORN}\n")
    with pytest.raises(ValueError, match="chef"):
        load_staff(path)


def test_empty_unavailable_days_means_always_available(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,,{BORN}\n")
    assert load_staff(path)[0].unavailable_days == set()


def test_duplicate_staff_name_is_rejected(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,,{BORN}\nKim,cashier,16,,{BORN}\n")
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
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,{hours},,{BORN}\n")
    with pytest.raises(ValueError, match="Kim: contracted_hours must be a whole number"):
        load_staff(path)


def test_shift_hour_past_midnight_is_rejected(tmp_path):
    path = write_csv(tmp_path, SHIFTS_HEADER + "Mon,Morning,7,25,1,0,1\n")
    with pytest.raises(ValueError, match="Mon Morning: end_hour must be a whole number from 0 to 24"):
        load_shifts(path)


@pytest.mark.parametrize("born", ["2009-03-15", "15/03/2009"])
def test_date_of_birth_accepts_both_common_formats(tmp_path, born):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,,{born}\n")
    assert load_staff(path)[0].date_of_birth == date(2009, 3, 15)


@pytest.mark.parametrize("born", ["", "soon", "2009-13-45", "2999-01-01"])
def test_missing_or_bad_date_of_birth_is_rejected(tmp_path, born):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,,{born}\n")
    with pytest.raises(ValueError, match="Kim: date_of_birth"):
        load_staff(path)


def test_new_optional_fields_default_to_off_and_blank(tmp_path):
    path = write_csv(tmp_path, STAFF_HEADER + f"Kim,barista,40,,{BORN}\n")
    kim = load_staff(path)[0]
    assert kim.opted_out_48h is False
    assert kim.sunday_opt_out is False
    assert kim.hourly_rate is None
    assert kim.time_off == set()


def test_new_optional_fields_are_read(tmp_path):
    header = "name,role,contracted_hours,unavailable_days,date_of_birth,opted_out_48h,sunday_opt_out,hourly_rate\n"
    path = write_csv(tmp_path, header + f"Kim,barista,40,,{BORN},TRUE,yes,£12.71\n")
    kim = load_staff(path)[0]
    assert kim.opted_out_48h is True
    assert kim.sunday_opt_out is True
    assert kim.hourly_rate == 12.71


@pytest.mark.parametrize(
    "column, value",
    [("opted_out_48h", "maybe"), ("sunday_opt_out", "perhaps"), ("hourly_rate", "lots"), ("hourly_rate", "-5"), ("hourly_rate", "nan")],
)
def test_bad_optional_fields_are_rejected(tmp_path, column, value):
    header = f"name,role,contracted_hours,unavailable_days,date_of_birth,{column}\n"
    path = write_csv(tmp_path, header + f"Kim,barista,40,,{BORN},{value}\n")
    with pytest.raises(ValueError, match=f"Kim: {column}"):
        load_staff(path)


@pytest.fixture(scope="module")
def rota():
    return solve_rota(load_staff(SAMPLE / "staff.csv"), load_shifts(SAMPLE / "shifts.csv"), WEEK, UK_RULES)


@pytest.fixture
def sheet(rota, tmp_path):
    path = tmp_path / "subfolder" / "rota.xlsx"
    save_rota_to_excel(rota, path)
    return load_workbook(path).active


def test_excel_has_staff_as_rows_and_days_as_columns(sheet, rota):
    headers = [cell.value for cell in sheet[1]]
    assert headers[:2] == ["Name", "Role"]
    assert headers[2:9] == [day_heading(WEEK, day) for day in DAYS]
    assert headers[2] == "Mon 9 Nov"
    assert [row[0].value for row in sheet.iter_rows(min_row=2)] == [p.name for p in rota.staff]


def test_excel_cells_match_the_rota(sheet, rota):
    headers = [cell.value for cell in sheet[1]]
    for row, person in zip(sheet.iter_rows(min_row=2), rota.staff):
        for day in DAYS:
            cell = row[headers.index(day_heading(WEEK, day))].value
            todays = [s for s in rota.shifts_for(person.name) if s.day == day]
            if todays:
                assert cell.startswith(todays[0].label)
            elif day in person.unavailable_days:
                assert cell == UNAVAILABLE
            else:
                assert cell == OFF
        assert row[headers.index("Hours")].value == rota.hours_for(person.name)


def test_rota_shows_each_persons_break(rota):
    rows = {row[0]: row for row in rota_rows(rota)}
    lena_shifts = [cell for cell in rows["Lena"][2:9] if cell.startswith("Morning")]
    assert lena_shifts
    assert all(cell.endswith("(30 min break)") for cell in lena_shifts)
    noor_shifts = [cell for cell in rows["Noor"][2:9] if cell.startswith("Evening")]
    assert noor_shifts
    assert all(cell.endswith("(20 min break)") for cell in noor_shifts)


def test_excel_leaves_out_dates_of_birth_and_pay(sheet):
    every_cell = " ".join(str(cell.value) for row in sheet.iter_rows() for cell in row)
    assert "2009" not in every_cell
    assert "8.5" not in every_cell
    assert "date_of_birth" not in every_cell
