"""Checks choosing a week, real dates in the rota, and time off on specific dates."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from rota_ai.connectors.csv_connector import load_shifts, load_staff
from rota_ai.connectors.excel_export import TIME_OFF, rota_file_name, rota_headers, rota_rows
from rota_ai.engine.compliance import target_hours
from rota_ai.engine.models import SUPERVISOR, Shift, Staff, date_of, day_heading, monday_of, next_monday
from rota_ai.engine.solver import RotaInfeasibleError, solve_rota
from rota_ai.rules.uk import UK_RULES

SAMPLE = Path(__file__).parent.parent / "data" / "sample"
WEEK = date(2026, 11, 9)
ADULT_BORN = date(1990, 1, 1)


def person(**fields):
    return Staff("Alex", SUPERVISOR, fields.pop("contract", 8), fields.pop("unavailable", set()), ADULT_BORN, **fields)


@pytest.mark.parametrize(
    "picked",
    [date(2026, 11, 9), date(2026, 11, 11), date(2026, 11, 15)],
)
def test_any_date_gives_its_monday_to_sunday_week(picked):
    assert monday_of(picked) == WEEK


def test_next_monday_is_always_next_week():
    assert next_monday(date(2026, 11, 2)) == WEEK
    assert next_monday(date(2026, 11, 8)) == WEEK


def test_real_dates_in_headings():
    assert day_heading(WEEK, "Mon") == "Mon 9 Nov"
    assert day_heading(WEEK, "Sun") == "Sun 15 Nov"
    assert rota_headers(WEEK)[2:9] == [
        "Mon 9 Nov",
        "Tue 10 Nov",
        "Wed 11 Nov",
        "Thu 12 Nov",
        "Fri 13 Nov",
        "Sat 14 Nov",
        "Sun 15 Nov",
    ]


def test_week_crossing_into_a_new_month_and_year():
    new_year_week = date(2026, 12, 28)
    assert day_heading(new_year_week, "Sun") == "Sun 3 Jan"
    assert date_of(new_year_week, "Sun") == date(2027, 1, 3)


def test_file_name_includes_the_week():
    assert rota_file_name(WEEK) == "rota_2026-11-09.xlsx"


def test_rota_must_start_on_a_monday():
    shifts = [Shift("Mon", "Morning", 7, 15, {SUPERVISOR: 1})]
    with pytest.raises(ValueError, match="Monday"):
        solve_rota([person()], shifts, date(2026, 11, 10), UK_RULES)


def test_nobody_works_on_their_time_off():
    shifts = [Shift("Wed", "Morning", 7, 15, {SUPERVISOR: 1})]
    on_holiday = person(time_off={date(2026, 11, 11)})
    with pytest.raises(RotaInfeasibleError, match="Alex has time off on Wed 11 Nov"):
        solve_rota([on_holiday], shifts, WEEK, UK_RULES)


def test_time_off_in_a_different_week_makes_no_difference():
    shifts = [Shift("Wed", "Morning", 7, 15, {SUPERVISOR: 1})]
    other_week = person(time_off={date(2026, 11, 18)})
    assert solve_rota([other_week], shifts, WEEK, UK_RULES).shifts_for("Alex") == shifts


def test_time_off_also_blocks_an_overnight_shift_running_into_it():
    shifts = [Shift("Tue", "Night", 22, 2, {SUPERVISOR: 1})]
    off_wednesday = person(time_off={date(2026, 11, 11)})
    with pytest.raises(RotaInfeasibleError, match="time off"):
        solve_rota([off_wednesday], shifts, WEEK, UK_RULES)


def test_time_off_lowers_their_target_hours():
    # 40 hours across 5 possible days, so each day off takes off 8 hours.
    five_days = person(contract=40, unavailable={"Sat", "Sun"})
    assert target_hours(five_days, WEEK) == 40
    assert target_hours(replace(five_days, time_off={date(2026, 11, 9)}), WEEK) == 32
    # Time off on a day they don't work anyway changes nothing.
    assert target_hours(replace(five_days, time_off={date(2026, 11, 14)}), WEEK) == 40


def test_a_whole_week_of_holiday_needs_no_hours():
    whole_week = {date(2026, 11, day) for day in range(9, 16)}
    assert target_hours(person(contract=40, time_off=whole_week), WEEK) == 0


def test_time_off_shows_in_the_rota():
    staff = load_staff(SAMPLE / "staff.csv")
    shifts = load_shifts(SAMPLE / "shifts.csv")
    staff_on_holiday = next(p for p in staff if p.name == "Priya")
    staff_on_holiday.time_off = {date(2026, 11, 10)}
    rota = solve_rota(staff, shifts, WEEK, UK_RULES)
    priya_row = rota_rows(rota)[staff.index(staff_on_holiday)]
    assert priya_row[3] == TIME_OFF  # Tuesday's column
    assert all(shift.day != "Tue" for shift in rota.shifts_for("Priya"))
