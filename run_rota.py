"""Builds the sample cafe's rota for next week and saves it to Excel.

Run it from the project folder with:  python run_rota.py
"""

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
# Our code lives in src/, so tell Python to look there for "rota_ai".
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rota_ai.connectors.csv_connector import load_shifts, load_staff  # noqa: E402
from rota_ai.connectors.excel_export import rota_file_name, save_rota_to_excel  # noqa: E402
from rota_ai.engine.compliance import staff_warnings  # noqa: E402
from rota_ai.engine.models import next_monday  # noqa: E402
from rota_ai.engine.solver import RotaInfeasibleError, solve_rota  # noqa: E402
from rota_ai.rules.uk import UK_RULES  # noqa: E402

DATA_FOLDER = PROJECT_ROOT / "data" / "sample"
OUTPUT_FOLDER = PROJECT_ROOT / "output"


def main() -> int:
    staff = load_staff(DATA_FOLDER / "staff.csv")
    shifts = load_shifts(DATA_FOLDER / "shifts.csv")
    week_start = next_monday(date.today())

    for warning in staff_warnings(staff, week_start, UK_RULES):
        print(f"Warning: {warning}")

    try:
        rota = solve_rota(staff, shifts, week_start, UK_RULES)
    except RotaInfeasibleError as error:
        print(error)
        return 1

    print(f"Rota for the week starting {week_start}")
    print(f"{'Name':<10}{'Role':<12}{'Hours':>6}{'Contract':>10}{'Weekend':>9}")
    for person in rota.staff:
        print(
            f"{person.name:<10}{person.role:<12}{rota.hours_for(person.name):>6}"
            f"{person.contracted_hours:>10}{rota.weekend_shifts_for(person.name):>9}"
        )
    if not rota.is_optimal:
        print("Note: time ran out, so this rota is valid but may not be the fairest possible.")

    output_file = OUTPUT_FOLDER / rota_file_name(week_start)
    try:
        save_rota_to_excel(rota, output_file)
    except PermissionError:
        print(f"Could not save {output_file}. Close it in Excel and run this again.")
        return 1
    print(f"Saved to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
