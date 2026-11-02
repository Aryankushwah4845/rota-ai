"""The manager's screen: load data, edit it, generate a rota, download it.

Run it from the project folder with:  python -m streamlit run app.py

Streamlit re-runs this whole file from top to bottom every time the manager
clicks or edits something. Anything that must survive between those re-runs,
like the finished rota, is kept in st.session_state.
"""

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).parent
# Our code lives in src/, so tell Python to look there for "rota_ai".
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rota_ai.connectors.csv_connector import shifts_from_rows, staff_from_rows  # noqa: E402
from rota_ai.connectors.excel_export import (  # noqa: E402
    ROTA_HEADERS,
    day_cell_colour,
    rota_rows,
    rota_to_excel_bytes,
)
from rota_ai.engine.models import DAYS, ROLES  # noqa: E402
from rota_ai.engine.solver import (  # noqa: E402
    DEFAULT_HOURS_TOLERANCE,
    RotaInfeasibleError,
    solve_rota,
)

SAMPLE_FOLDER = PROJECT_ROOT / "data" / "sample"
USE_SAMPLE = "Use the sample café data"
USE_UPLOAD = "Upload my own CSV files"

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


def hours_mismatches(staff, shifts) -> list[str]:
    """Roles whose shifts can't add up to their contracts, even using the full tolerance."""
    mismatches = []
    for role in ROLES:
        team = [person for person in staff if person.role == role]
        needed = sum(shift.hours * shift.needs.get(role, 0) for shift in shifts)
        contracted = sum(person.contracted_hours for person in team)
        if abs(needed - contracted) > DEFAULT_HOURS_TOLERANCE * len(team):
            mismatches.append(
                f"{role.capitalize()}: the shifts need {needed} hours in total, "
                f"but contracts add up to {contracted} hours."
            )
    return mismatches


def generate(staff_rows: list[dict], shift_rows: list[dict]) -> dict:
    """Returns {"rota": ...} on success, or {"problem": ..., "details": [...]} if not."""
    try:
        staff = staff_from_rows(staff_rows)
        shifts = shifts_from_rows(shift_rows)
    except ValueError as error:
        return {"problem": "Please fix this in the tables above.", "details": [str(error)]}

    if not staff or not shifts:
        missing = "staff" if not staff else "shifts"
        return {"problem": f"There are no {missing} yet.", "details": [f"Add at least one row to the {missing} table."]}

    try:
        return {"rota": solve_rota(staff, shifts)}
    except RotaInfeasibleError as error:
        details = str(error).removeprefix("No valid rota exists. ").split("; ")
        details += hours_mismatches(staff, shifts)
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

    return table.style.map(colour_day, subset=list(DAYS)).apply(
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
    st.subheader("Your draft rota")
    table = pd.DataFrame(rota_rows(rota), columns=ROTA_HEADERS)
    st.dataframe(style_rota(table), hide_index=True, width="stretch")
    st.caption(
        f"Hours are green when they match the contract and amber when they don't "
        f"(never more than {DEFAULT_HOURS_TOLERANCE} hours away)."
    )
    if not rota.is_optimal:
        st.warning("Time ran out, so this rota is valid but may not be the fairest possible.")
    st.download_button(
        "Download as Excel",
        rota_to_excel_bytes(rota),
        file_name="rota.xlsx",
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
        return read_csv_as_text(staff_bytes), read_csv_as_text(shift_bytes), data_id
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        st.error("One of those files couldn't be read as a CSV. Check it opens properly in Excel.")
        return None


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

    st.header("1. Choose your data")
    tables = load_tables()
    if tables is None:
        return
    staff_table, shift_table, data_id = tables

    st.header("2. Check and edit")
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
        },
    )
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

    st.header("3. Generate")
    inputs = (table_to_rows(edited_staff), table_to_rows(edited_shifts))
    if st.button("Generate rota", key="generate", type="primary", width="stretch"):
        with st.spinner("Working out the fairest rota..."):
            st.session_state["result"] = generate(*inputs)
            st.session_state["result_inputs"] = inputs

    # Never show a rota that no longer matches the tables, or it could be
    # downloaded and published by mistake.
    if "result" in st.session_state:
        if st.session_state["result_inputs"] == inputs:
            show_result(st.session_state["result"])
        else:
            st.warning("The tables have changed since the last rota. Click Generate rota for a new one.")


if __name__ == "__main__":
    main()
