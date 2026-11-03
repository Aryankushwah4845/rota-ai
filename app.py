"""The manager's screen: load data, edit it, generate a rota, download it.

Run it from the project folder with:  python -m streamlit run app.py

Streamlit re-runs this whole file from top to bottom every time the manager
clicks or edits something. Anything that must survive between those re-runs,
like the finished rota, is kept in st.session_state.
"""

import sys
from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).parent
# Our code lives in src/, so tell Python to look there for "rota_ai".
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rota_ai.connectors.csv_connector import (  # noqa: E402
    OPTIONAL_STAFF_COLUMNS,
    shifts_from_rows,
    staff_from_rows,
)
from rota_ai.connectors.excel_export import (  # noqa: E402
    day_cell_colour,
    rota_file_name,
    rota_headers,
    rota_rows,
    rota_to_excel_bytes,
)
from rota_ai.engine.compliance import (  # noqa: E402
    can_be_rostered,
    staff_warnings,
    target_hours,
    weekly_labour_cost,
)
from rota_ai.engine.models import DAYS, ROLES, Shift, Staff, monday_of, next_monday  # noqa: E402
from rota_ai.engine.solver import (  # noqa: E402
    DEFAULT_HOURS_TOLERANCE,
    RotaInfeasibleError,
    solve_rota,
)
from rota_ai.rules.base import RulesPack  # noqa: E402
from rota_ai.rules.uk import UK_RULES, describe_rules  # noqa: E402

SAMPLE_FOLDER = PROJECT_ROOT / "data" / "sample"
USE_SAMPLE = "Use the sample café data"
USE_UPLOAD = "Upload my own CSV files"
DISCLAIMER = "These rules are a guide, not legal advice. Check with an employment adviser."
TRUE_FALSE_COLUMNS = ("opted_out_48h", "sunday_opt_out")

ON_CONTRACT_COLOUR = "C6EFCE"
OFF_CONTRACT_COLOUR = "FFD966"


def read_csv_as_text(content: bytes) -> pd.DataFrame:
    """Every cell stays text, so the checks in csv_connector can explain bad values."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel's plain "CSV" option doesn't save as UTF-8.
        text = content.decode("cp1252", errors="replace")
    table = pd.read_csv(BytesIO(text.encode("utf-8")), dtype=str, keep_default_na=False)
    table.columns = [column.strip().lower() for column in table.columns]
    return table


def table_to_rows(table: pd.DataFrame) -> list[dict]:
    """Turns an on-screen table into clean rows, skipping any left completely blank."""
    rows = []
    for row in table.to_dict("records"):
        clean = {col: "" if pd.isna(value) else str(value).strip() for col, value in row.items()}
        if any(clean.values()):
            rows.append(clean)
    return rows


def with_new_staff_columns(table: pd.DataFrame) -> pd.DataFrame:
    """Gives older files the newer columns, so the manager can fill them in on screen."""
    table = table.copy()
    for column in ("date_of_birth", *OPTIONAL_STAFF_COLUMNS):
        if column not in table.columns:
            table[column] = ""
    # Excel saves these as TRUE and FALSE, but the on-screen menu offers lower case.
    for column in TRUE_FALSE_COLUMNS:
        table[column] = table[column].str.strip().str.lower()
    return table


def time_off_by_person(entries: list[tuple[str, date, date]]) -> dict[str, set[date]]:
    """Turns (name, first date, last date) entries into each person's set of dates."""
    time_off = {}
    for name, first, last in entries:
        days = (last - first).days + 1
        time_off.setdefault(name, set()).update(first + timedelta(days=n) for n in range(days))
    return time_off


def hours_mismatches(staff: list[Staff], shifts: list[Shift], week_start: date, rules: RulesPack) -> list[str]:
    """Roles whose shifts can't add up to their contracts, even using the full tolerance."""
    mismatches = []
    workers = [person for person in staff if can_be_rostered(person, week_start, rules)]
    for role in ROLES:
        team = [person for person in workers if person.role == role]
        needed = sum(shift.hours * shift.needs.get(role, 0) for shift in shifts)
        contracted = sum(target_hours(person, week_start) for person in team)
        if abs(needed - contracted) > DEFAULT_HOURS_TOLERANCE * len(team):
            mismatches.append(
                f"{role.capitalize()}: the shifts need {needed} hours in total, "
                f"but contracts add up to {contracted} hours."
            )
    return mismatches


def generate(
    staff_rows: list[dict],
    shift_rows: list[dict],
    week_start: date,
    time_off: dict[str, set[date]] | None = None,
    rules: RulesPack = UK_RULES,
) -> dict:
    """Returns {"rota": ...} on success, or {"problem": ..., "details": [...]} if not."""
    try:
        staff = staff_from_rows(staff_rows)
        shifts = shifts_from_rows(shift_rows)
    except ValueError as error:
        return {"problem": "Please fix this in the tables above.", "details": [str(error)]}

    if not staff or not shifts:
        missing = "staff" if not staff else "shifts"
        return {"problem": f"There are no {missing} yet.", "details": [f"Add at least one row to the {missing} table."]}

    for person in staff:
        person.time_off = (time_off or {}).get(person.name, set())

    try:
        return {"rota": solve_rota(staff, shifts, week_start, rules)}
    except RotaInfeasibleError as error:
        details = error.problems + hours_mismatches(staff, shifts, week_start, rules)
        return {"problem": "No rota is possible with these tables.", "details": details, "suggest_changes": True}
    except TimeoutError as error:
        return {"problem": "The search took too long.", "details": [str(error)]}
    except ValueError as error:
        return {"problem": "Please fix this in the tables above.", "details": [str(error)]}


def style_rota(table: pd.DataFrame):
    def colour_day(text):
        colour = day_cell_colour(text)
        return f"background-color: #{colour}; color: black" if colour else ""

    def colour_hours(row):
        colour = ON_CONTRACT_COLOUR if row["Hours"] == row["Contract"] else OFF_CONTRACT_COLOUR
        return [f"background-color: #{colour}; color: black"] * len(row)

    # Day columns sit straight after Name and Role.
    day_columns = list(table.columns[2 : 2 + len(DAYS)])
    return table.style.map(colour_day, subset=day_columns).apply(
        colour_hours, axis=1, subset=["Hours", "Contract"]
    )


def show_result(result: dict) -> None:
    if "problem" in result:
        details = "\n".join(f"- {detail}" for detail in result["details"])
        st.error(f"**{result['problem']}**\n\n{details}")
        if result.get("suggest_changes"):
            st.info(
                "Things to try: free up someone's unavailable days, reduce how many staff a "
                "shift needs, add staff, or change contracted hours. Then generate again."
            )
        return

    rota = result["rota"]
    st.subheader(f"Your draft rota, week starting {rota.week_start.day} {rota.week_start:%B %Y}")
    table = pd.DataFrame(rota_rows(rota), columns=rota_headers(rota.week_start))
    st.dataframe(style_rota(table), hide_index=True, width="stretch")
    st.caption(
        f"Hours are green when they match the contract and amber when they don't "
        f"(never more than {DEFAULT_HOURS_TOLERANCE} hours away, after allowing for time off)."
    )
    if not rota.is_optimal:
        st.warning("Time ran out, so this rota is valid but may not be the fairest possible.")

    cost, no_rate = weekly_labour_cost(rota)
    st.metric("Total weekly labour cost", f"£{cost:,.2f}")
    note = "Counts every rostered hour, so breaks are treated as paid."
    if no_rate:
        note += f" Leaves out {', '.join(no_rate)}, who have no hourly rate."
    st.caption(note)

    st.download_button(
        "Download as Excel",
        rota_to_excel_bytes(rota),
        file_name=rota_file_name(rota.week_start),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, str] | None:
    """Returns the starting tables and an id for this data, or None if not ready yet."""
    source = st.radio("Where is your data?", [USE_SAMPLE, USE_UPLOAD], horizontal=True)
    if source == USE_SAMPLE:
        staff_bytes = (SAMPLE_FOLDER / "staff.csv").read_bytes()
        shift_bytes = (SAMPLE_FOLDER / "shifts.csv").read_bytes()
        data_id = "sample"
    else:
        left, right = st.columns(2)
        staff_file = left.file_uploader("Staff CSV", type="csv")
        shift_file = right.file_uploader("Shifts CSV", type="csv")
        if staff_file is None or shift_file is None:
            st.info("Upload both CSV files to continue.")
            return None
        staff_bytes = staff_file.getvalue()
        shift_bytes = shift_file.getvalue()
        data_id = f"{staff_file.file_id}_{shift_file.file_id}"

    try:
        return with_new_staff_columns(read_csv_as_text(staff_bytes)), read_csv_as_text(shift_bytes), data_id
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        st.error("One of those files couldn't be read as a CSV. Check it opens properly in Excel.")
        return None


def choose_week() -> date:
    picked = st.date_input(
        "Pick any date in the week you want a rota for",
        value=next_monday(date.today()),
        key="week_picker",
        format="DD/MM/YYYY",
    )
    week_start = monday_of(picked)
    week_end = week_start + timedelta(days=6)
    st.caption(
        f"This rota will run from Monday {week_start.day} {week_start:%B} "
        f"to Sunday {week_end.day} {week_end:%B %Y}."
    )
    return week_start


def edit_time_off(names: list[str], week_start: date) -> list[tuple[str, date, date]]:
    """The time off section. Returns its entries, which last until the page is refreshed."""
    st.subheader("Time off")
    st.caption(
        "For holidays and appointments on specific dates. Don't record the reason, just the "
        "dates. These entries are lost if you refresh the page or close the app."
    )
    entries = st.session_state.setdefault("time_off", [])

    person_column, first_column, last_column = st.columns(3)
    person = person_column.selectbox("Who", names, key="time_off_person")
    first = first_column.date_input("From", value=week_start, key="time_off_first", format="DD/MM/YYYY")
    last = last_column.date_input("To", value=week_start, key="time_off_last", format="DD/MM/YYYY")
    if st.button("Add time off", key="add_time_off"):
        if not person:
            st.error("Add someone to the staff table first.")
        elif last < first:
            st.error("The 'To' date is before the 'From' date.")
        else:
            entries.append((person, first, last))

    for number, (person, first, last) in enumerate(entries):
        text_column, button_column = st.columns([5, 1])
        text_column.write(f"{person}: {first.day} {first:%b %Y} to {last.day} {last:%b %Y}")
        if button_column.button("Remove", key=f"remove_time_off_{number}"):
            del entries[number]
            st.rerun()
        if person not in names:
            text_column.warning(f"Nobody called {person} is in the staff table, so this won't be used.")
    return entries


def show_rules() -> RulesPack:
    """The Rules section. Returns the rules to use, with the manager's choice applied."""
    with st.expander("Rules"):
        exception = st.checkbox(
            "Use the hospitality/retail exception for under-18s' night work",
            key="sector_exception",
            help=(
                "Lets 16-17 year olds work at night, but never between midnight and 04:00. "
                "Only allowed in retail, catering, hotels, pubs, restaurants and bars, when no "
                "adult is available, the work keeps the service running or meets a surge in "
                "demand, and they get supervision and time off in lieu. Rota AI can't check "
                "those conditions, so you need to."
            ),
        )
        rules = replace(UK_RULES, young_sector_exception=exception)
        st.table(pd.DataFrame(describe_rules(rules)).set_index("Rule"))
    return rules


def rota_page() -> None:
    st.header("1. Choose your data")
    tables = load_tables()
    if tables is None:
        return
    staff_table, shift_table, data_id = tables

    st.header("2. Choose the week")
    week_start = choose_week()

    st.header("3. Check and edit")
    st.caption(
        "Double-click a cell to change it. To add a row, click the empty row at the bottom. "
        "To delete one, tick the box at its left and press Delete. Your files aren't changed."
    )
    st.subheader("Staff")
    edited_staff = st.data_editor(
        staff_table,
        key=f"staff_{data_id}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height="content",
        column_config={
            "role": st.column_config.SelectboxColumn("role", options=ROLES),
            "unavailable_days": st.column_config.TextColumn(
                "unavailable_days", help="Separate days with ; for example Wed;Thu"
            ),
            "date_of_birth": st.column_config.TextColumn(
                "date_of_birth", help="For example 2009-03-15 or 15/03/2009"
            ),
            "opted_out_48h": st.column_config.SelectboxColumn(
                "opted_out_48h",
                options=["true", "false"],
                help="True if they've signed the 48-hour opt-out. Doesn't count for under-18s.",
            ),
            "sunday_opt_out": st.column_config.SelectboxColumn(
                "sunday_opt_out",
                options=["true", "false"],
                help="True if they've opted out of Sunday working.",
            ),
            "hourly_rate": st.column_config.TextColumn("hourly_rate", help="Pounds an hour, for example 12.71"),
        },
    )
    staff_rows = table_to_rows(edited_staff)
    names = [row["name"] for row in staff_rows if row.get("name")]

    time_off_entries = edit_time_off(names, week_start)

    st.subheader("Shifts")
    edited_shifts = st.data_editor(
        shift_table,
        key=f"shifts_{data_id}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height="content",
        column_config={"day": st.column_config.SelectboxColumn("day", options=list(DAYS))},
    )

    rules = show_rules()

    # Bad rows are explained when the manager clicks Generate rota.
    try:
        warnings = staff_warnings(staff_from_rows(staff_rows), week_start, rules)
    except ValueError:
        warnings = []
    for warning in warnings:
        st.warning(warning)

    st.header("4. Generate")
    shift_rows = table_to_rows(edited_shifts)
    inputs = (staff_rows, shift_rows, week_start, list(time_off_entries), rules)
    if st.button("Generate rota", key="generate", type="primary", width="stretch"):
        with st.spinner("Working out the fairest rota..."):
            st.session_state["result"] = generate(
                staff_rows, shift_rows, week_start, time_off_by_person(time_off_entries), rules
            )
            st.session_state["result_inputs"] = inputs

    # Never show a rota that no longer matches the tables, or it could be
    # downloaded and published by mistake.
    if "result" in st.session_state:
        if st.session_state["result_inputs"] == inputs:
            show_result(st.session_state["result"])
        else:
            st.warning("Something has changed since the last rota. Click Generate rota for a new one.")


def main() -> None:
    st.set_page_config(page_title="Rota AI", layout="wide")
    # Streamlit has no setting for button size, so make this one big with CSS.
    st.markdown(
        """<style>
        .st-key-generate button { height: 4.5rem; }
        .st-key-generate button p { font-size: 1.5rem; font-weight: 600; }
        </style>""",
        unsafe_allow_html=True,
    )
    st.title("Rota AI")
    rota_page()
    st.divider()
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
