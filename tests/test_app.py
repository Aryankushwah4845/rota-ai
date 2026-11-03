"""Runs the Streamlit app without a browser and clicks through it like a manager."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import DISCLAIMER, generate, read_csv_as_text, table_to_rows, time_off_by_person, with_new_staff_columns
from rota_ai.engine.models import next_monday
from rota_ai.rules.uk import UK_RULES

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "sample"
WEEK = date(2026, 11, 9)


def sample_rows(name):
    return table_to_rows(read_csv_as_text((SAMPLE / name).read_bytes()))


@pytest.fixture
def staff_rows():
    return sample_rows("staff.csv")


@pytest.fixture
def shift_rows():
    return sample_rows("shifts.csv")


@pytest.fixture
def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()


def test_app_opens_with_sample_data_and_no_errors(app):
    assert not app.exception
    assert not app.error


def test_sample_data_opens_without_legal_warnings(app):
    assert not app.warning


def test_generate_button_shows_rota_and_download(app):
    app.button(key="generate").click().run()
    assert not app.exception
    assert not app.error
    # The staff and shifts editors count as dataframes too. The rota comes last.
    assert len(app.dataframe) == 3
    rota_table = app.dataframe[-1].value
    assert list(rota_table["Name"]) == [row["name"] for row in sample_rows("staff.csv")]
    assert list(rota_table["Hours"]) == list(rota_table["Contract"])
    assert len(app.download_button) == 1


def test_upload_mode_waits_for_both_files(app):
    app.radio[0].set_value("Upload my own CSV files").run()
    assert not app.exception
    assert len(app.file_uploader) == 2
    assert not app.button


def test_disclaimer_is_always_at_the_bottom(app):
    assert app.caption[-1].value == DISCLAIMER
    app.radio[0].set_value("Upload my own CSV files").run()
    assert app.caption[-1].value == DISCLAIMER


def test_week_picker_starts_on_next_week_and_shows_real_dates(app):
    assert app.date_input(key="week_picker").value == next_monday(date.today())
    app.date_input(key="week_picker").set_value(date(2026, 11, 11)).run()  # a Wednesday
    assert any("Monday 9 November to Sunday 15 November 2026" in c.value for c in app.caption)
    app.button(key="generate").click().run()
    assert not app.exception
    assert "Mon 9 Nov" in app.dataframe[-1].value.columns


def test_rota_is_hidden_after_the_week_changes(app):
    app.date_input(key="week_picker").set_value(date(2026, 11, 9)).run()
    app.button(key="generate").click().run()
    assert len(app.dataframe) == 3
    app.date_input(key="week_picker").set_value(date(2026, 11, 16)).run()
    assert len(app.dataframe) == 2
    assert any("Generate rota for a new one" in warning.value for warning in app.warning)


def test_rota_is_hidden_after_time_off_changes(app):
    app.button(key="generate").click().run()
    assert len(app.dataframe) == 3
    app.button(key="add_time_off").click().run()
    assert len(app.dataframe) == 2


def test_time_off_can_be_added_used_and_removed(app):
    app.date_input(key="week_picker").set_value(WEEK).run()
    app.selectbox(key="time_off_person").set_value("Priya").run()
    tuesday = date(2026, 11, 10)
    app.date_input(key="time_off_first").set_value(tuesday)
    app.date_input(key="time_off_last").set_value(tuesday)
    app.button(key="add_time_off").click().run()
    assert not app.exception
    assert app.session_state["time_off"] == [("Priya", tuesday, tuesday)]

    app.button(key="generate").click().run()
    rota_table = app.dataframe[-1].value
    priya = rota_table[rota_table["Name"] == "Priya"].iloc[0]
    assert priya["Tue 10 Nov"] == "Time off"

    app.button(key="remove_time_off_0").click().run()
    assert app.session_state["time_off"] == []


def test_time_off_with_dates_the_wrong_way_round_is_refused(app):
    app.date_input(key="time_off_first").set_value(date(2026, 11, 12))
    app.date_input(key="time_off_last").set_value(date(2026, 11, 10))
    app.button(key="add_time_off").click().run()
    assert any("before" in error.value for error in app.error)
    assert app.session_state["time_off"] == []


def test_rules_section_shows_the_values_and_exception_setting(app):
    assert any(expander.label == "Rules" for expander in app.expander)
    rules_table = app.table[0].value
    assert "Adults: rest between shifts" in rules_table.index
    assert rules_table.loc["Ages 16-17: night work", "Value"] == "No work 22:00-06:00"
    app.checkbox(key="sector_exception").check().run()
    assert app.table[0].value.loc["Ages 16-17: night work", "Value"].startswith("No work 00:00-04:00")


def test_sector_exception_lets_a_young_worker_work_until_23_00(staff_rows, shift_rows):
    # Without Noor, Lena is the only cashier for shifts that all finish at 23:00.
    only_lena = [row for row in staff_rows if row["name"] != "Noor"]
    for row in shift_rows:
        row["cashier"] = "1" if row["shift"] == "Evening" and row["day"] in ("Fri", "Sat") else "0"
    assert "problem" in generate(only_lena, shift_rows, WEEK)
    assert "rota" in generate(only_lena, shift_rows, WEEK, rules=replace(UK_RULES, young_sector_exception=True))


def test_labour_cost_is_shown(app):
    app.date_input(key="week_picker").set_value(WEEK).run()
    app.button(key="generate").click().run()
    # 40*14.5 + 40*14.5 + 32*14 + 40*13 + 40*12.75 + 32*11.5 + 16*8.5 + 16*12.71
    assert app.metric[0].label == "Total weekly labour cost"
    assert app.metric[0].value == "£3,345.36"


def test_generate_succeeds_with_sample_rows(staff_rows, shift_rows):
    assert "rota" in generate(staff_rows, shift_rows, WEEK)


def test_too_few_staff_is_explained(staff_rows, shift_rows):
    no_cashiers = [row for row in staff_rows if row["role"] != "cashier"]
    result = generate(no_cashiers, shift_rows, WEEK)
    assert result["problem"] == "No rota is possible with these tables."
    assert "Fri: needs 2 cashier shift(s), 0 available" in result["details"]
    assert result["suggest_changes"]


def test_hours_problem_names_the_role_and_totals(staff_rows, shift_rows):
    weekdays = [row for row in shift_rows if row["day"] not in ("Sat", "Sun")]
    result = generate(staff_rows, weekdays, WEEK)
    assert result["problem"] == "No rota is possible with these tables."
    assert any(
        detail.startswith("Supervisor: the shifts need 80 hours") for detail in result["details"]
    )


def test_failure_names_the_rule_and_person_on_screen(staff_rows, shift_rows):
    friday = date(2026, 11, 13)
    result = generate(staff_rows, shift_rows, WEEK, time_off_by_person([("Noor", friday, friday)]))
    assert result["problem"] == "No rota is possible with these tables."
    assert any("Lena is 17 and can't work the 15:00-23:00 shift" in detail for detail in result["details"])
    assert "Noor has time off on Fri 13 Nov" in result["details"]


def test_bad_number_is_explained_in_plain_english(staff_rows, shift_rows):
    staff_rows[0]["contracted_hours"] = "lots"
    result = generate(staff_rows, shift_rows, WEEK)
    assert result["problem"] == "Please fix this in the tables above."
    assert result["details"] == ["Priya: contracted_hours must be a whole number, but it is 'lots'"]
    assert "suggest_changes" not in result


def test_missing_date_of_birth_is_explained(staff_rows, shift_rows):
    staff_rows[0]["date_of_birth"] = ""
    result = generate(staff_rows, shift_rows, WEEK)
    assert result["problem"] == "Please fix this in the tables above."
    assert "Priya: date_of_birth is needed" in result["details"][0]


def test_shift_without_supervisor_is_explained(staff_rows, shift_rows):
    shift_rows[0]["supervisor"] = "0"
    result = generate(staff_rows, shift_rows, WEEK)
    assert result["details"] == ["Mon Morning must need at least one supervisor"]


@pytest.mark.parametrize("empty", ["staff", "shifts"])
def test_empty_table_is_explained(empty, staff_rows, shift_rows):
    result = generate([] if empty == "staff" else staff_rows, [] if empty == "shifts" else shift_rows, WEEK)
    assert result["problem"] == f"There are no {empty} yet."


def test_older_files_get_the_new_columns_to_fill_in():
    old_file = read_csv_as_text(b"name,role,contracted_hours,unavailable_days\nKim,barista,40,\n")
    table = with_new_staff_columns(old_file)
    for column in ("date_of_birth", "opted_out_48h", "sunday_opt_out", "hourly_rate"):
        assert table.loc[0, column] == ""


def test_excel_true_and_false_become_lower_case():
    excel_file = read_csv_as_text(b"name,opted_out_48h,sunday_opt_out\nKim,TRUE,FALSE\n")
    table = with_new_staff_columns(excel_file)
    assert table.loc[0, "opted_out_48h"] == "true"
    assert table.loc[0, "sunday_opt_out"] == "false"


def test_time_off_ranges_include_both_end_dates():
    time_off = time_off_by_person([("Kim", date(2026, 11, 9), date(2026, 11, 11))])
    assert time_off == {"Kim": {date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)}}


def test_blank_rows_and_empty_cells_are_ignored():
    table = read_csv_as_text(b"name,role\nKim,barista\n,\n")
    table.loc[len(table)] = [None, None]
    assert table_to_rows(table) == [{"name": "Kim", "role": "barista"}]


def test_excel_style_csv_files_can_be_read():
    with_byte_order_mark = b"\xef\xbb\xbfName, Role\nKim,barista\n"
    assert table_to_rows(read_csv_as_text(with_byte_order_mark)) == [{"name": "Kim", "role": "barista"}]
    windows_encoding = "name,role\nRené,barista\n".encode("cp1252")
    assert table_to_rows(read_csv_as_text(windows_encoding))[0]["name"] == "René"
