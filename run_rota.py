"""Builds the sample cafe's rota and saves it to Excel.

Run it from the project folder with:  python run_rota.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
# Our code lives in src/, so tell Python to look there for "rota_ai".
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rota_ai.connectors.csv_connector import load_shifts, load_staff  # noqa: E402
from rota_ai.connectors.excel_export import save_rota_to_excel  # noqa: E402
from rota_ai.engine.solver import RotaInfeasibleError, solve_rota  # noqa: E402

DATA_FOLDER = PROJECT_ROOT / "data" / "sample"
OUTPUT_FILE = PROJECT_ROOT / "output" / "rota.xlsx"


def main() -> int:
    staff = load_staff(DATA_FOLDER / "staff.csv")
    shifts = load_shifts(DATA_FOLDER / "shifts.csv")

    try:
        rota = solve_rota(staff, shifts)
    except RotaInfeasibleError as error:
        print(error)
        return 1

    print(f"{'Name':<10}{'Role':<12}{'Hours':>6}{'Contract':>10}{'Weekend':>9}")
    for person in staff:
        print(
            f"{person.name:<10}{person.role:<12}{rota.hours_for(person.name):>6}"
            f"{person.contracted_hours:>10}{rota.weekend_shifts_for(person.name):>9}"
        )
    if not rota.is_optimal:
        print("Note: time ran out, so this rota is valid but may not be the fairest possible.")

    try:
        save_rota_to_excel(rota, OUTPUT_FILE)
    except PermissionError:
        print(f"Could not save {OUTPUT_FILE}. Close it in Excel and run this again.")
        return 1
    print(f"Saved to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
