"""Runs the Streamlit app without a browser and clicks through it like a manager."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import generate, read_csv_as_text, table_to_rows

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "sample"


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


def test_generate_succeeds_with_sample_rows(staff_rows, shift_rows):
    assert "rota" in generate(staff_rows, shift_rows)


def test_too_few_staff_is_explained(staff_rows, shift_rows):
    no_cashiers = [row for row in staff_rows if row["role"] != "cashier"]
    result = generate(no_cashiers, shift_rows)
    assert result["problem"] == "No rota is possible with these tables."
    assert "Fri: needs 2 cashier shift(s), 0 available" in result["details"]
    assert result["suggest_changes"]


def test_hours_problem_names_the_role_and_totals(staff_rows, shift_rows):
    weekdays = [row for row in shift_rows if row["day"] not in ("Sat", "Sun")]
    result = generate(staff_rows, weekdays)
    assert result["problem"] == "No rota is possible with these tables."
    assert any(
        detail.startswith("Supervisor: the shifts need 80 hours") for detail in result["details"]
    )


def test_bad_number_is_explained_in_plain_english(staff_rows, shift_rows):
    staff_rows[0]["contracted_hours"] = "lots"
    result = generate(staff_rows, shift_rows)
    assert result["problem"] == "Please fix this in the tables above."
    assert result["details"] == ["Priya: contracted_hours must be a whole number, but it is 'lots'"]
    assert "suggest_changes" not in result


def test_shift_without_supervisor_is_explained(staff_rows, shift_rows):
    shift_rows[0]["supervisor"] = "0"
    result = generate(staff_rows, shift_rows)
    assert result["details"] == ["Mon Morning must need at least one supervisor"]


@pytest.mark.parametrize("empty", ["staff", "shifts"])
def test_empty_table_is_explained(empty, staff_rows, shift_rows):
    result = generate([] if empty == "staff" else staff_rows, [] if empty == "shifts" else shift_rows)
    assert result["problem"] == f"There are no {empty} yet."


def test_blank_rows_and_empty_cells_are_ignored():
    table = read_csv_as_text(b"name,role\nKim,barista\n,\n")
    table.loc[len(table)] = [None, None]
    assert table_to_rows(table) == [{"name": "Kim", "role": "barista"}]


def test_excel_style_csv_files_can_be_read():
    with_byte_order_mark = b"\xef\xbb\xbfName, Role\nKim,barista\n"
    assert table_to_rows(read_csv_as_text(with_byte_order_mark)) == [{"name": "Kim", "role": "barista"}]
    windows_encoding = "name,role\nRené,barista\n".encode("cp1252")
    assert table_to_rows(read_csv_as_text(windows_encoding))[0]["name"] == "René"
