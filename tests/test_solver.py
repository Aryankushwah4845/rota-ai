"""Checks every rota rule by inspecting the finished rota, not the solver's code."""

from collections import Counter
from pathlib import Path

import pytest

from rota_ai.connectors.csv_connector import load_shifts, load_staff
from rota_ai.engine.models import DAYS, ROLES, SUPERVISOR, Shift, Staff
from rota_ai.engine.solver import DEFAULT_HOURS_TOLERANCE, RotaInfeasibleError, solve_rota

SAMPLE = Path(__file__).parent.parent / "data" / "sample"


@pytest.fixture(scope="module")
def staff():
    return load_staff(SAMPLE / "staff.csv")


@pytest.fixture(scope="module")
def shifts():
    return load_shifts(SAMPLE / "shifts.csv")


@pytest.fixture(scope="module")
def rota(staff, shifts):
    return solve_rota(staff, shifts)


def staff_count_on_day(shifts, day):
    return sum(sum(shift.needs.values()) for shift in shifts if shift.day == day)


def test_sample_data_matches_the_brief(staff, shifts):
    assert len(staff) == 8
    assert {person.role for person in staff} == set(ROLES)
    assert len(shifts) == 14
    assert {(shift.name, shift.start_hour, shift.end_hour) for shift in shifts} == {
        ("Morning", 7, 15),
        ("Evening", 15, 23),
    }


def test_friday_and_saturday_need_more_staff_than_other_days(shifts):
    quiet_days = [day for day in DAYS if day not in ("Fri", "Sat")]
    busiest_quiet_day = max(staff_count_on_day(shifts, day) for day in quiet_days)
    assert staff_count_on_day(shifts, "Fri") > busiest_quiet_day
    assert staff_count_on_day(shifts, "Sat") > busiest_quiet_day


def test_at_most_one_shift_per_day(rota):
    worked = Counter((name, shift.day) for name, shift in rota.assignments)
    assert max(worked.values()) == 1


def test_nobody_works_when_unavailable(rota, staff):
    for person in staff:
        worked_days = {shift.day for shift in rota.shifts_for(person.name)}
        assert not worked_days & person.unavailable_days


def test_every_shift_has_exactly_the_roles_it_needs(rota, staff, shifts):
    role_of = {person.name: person.role for person in staff}
    for shift in shifts:
        working = [name for name, s in rota.assignments if s is shift]
        assert Counter(role_of[name] for name in working) == Counter(
            {role: count for role, count in shift.needs.items() if count > 0}
        )


def test_supervisor_on_every_shift(rota, staff, shifts):
    supervisors = {person.name for person in staff if person.role == SUPERVISOR}
    for shift in shifts:
        assert any(name in supervisors for name, s in rota.assignments if s is shift)


def test_hours_match_contracts(rota, staff):
    # The sample data is built so that everyone can hit their contract exactly.
    for person in staff:
        assert rota.hours_for(person.name) == person.contracted_hours


def test_weekend_shifts_shared_fairly_within_each_role(rota, staff):
    for role in ROLES:
        counts = [rota.weekend_shifts_for(p.name) for p in staff if p.role == role]
        assert max(counts) - min(counts) <= 1


def test_solver_proves_rota_is_the_best_possible(rota):
    assert rota.is_optimal


def test_same_data_gives_the_same_rota(rota, staff, shifts):
    again = solve_rota(staff, shifts)
    assert [(n, s.day, s.name) for n, s in again.assignments] == [
        (n, s.day, s.name) for n, s in rota.assignments
    ]


def test_too_few_available_people_is_explained(staff, shifts):
    nobody_on_monday = [
        Staff(p.name, p.role, p.contracted_hours, p.unavailable_days | {"Mon"})
        if p.role == SUPERVISOR
        else p
        for p in staff
    ]
    with pytest.raises(RotaInfeasibleError, match="Mon: needs 2 supervisor"):
        solve_rota(nobody_on_monday, shifts)


def test_impossible_hours_are_explained():
    # One 8-hour shift can't get someone within 8 hours of a 40-hour contract.
    person = Staff("Solo", SUPERVISOR, 40, set())
    shift = Shift("Mon", "Morning", 7, 15, {SUPERVISOR: 1})
    with pytest.raises(RotaInfeasibleError, match=f"within {DEFAULT_HOURS_TOLERANCE} hours"):
        solve_rota([person], [shift])


def test_shift_without_a_supervisor_is_rejected(staff):
    shift = Shift("Mon", "Morning", 7, 15, {"barista": 1, "cashier": 0, SUPERVISOR: 0})
    with pytest.raises(ValueError, match="supervisor"):
        solve_rota(staff, [shift])
