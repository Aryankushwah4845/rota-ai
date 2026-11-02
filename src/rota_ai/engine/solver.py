"""The rota solver, built on Google OR-Tools' CP-SAT.

We never tell the computer *how* to build a rota. We describe:
  1. decisions - one yes/no question per person and shift: "do they work it?"
  2. hard rules - things that must always be true
  3. a score - what makes one valid rota better than another
CP-SAT then searches for the valid answer with the lowest score.
"""

from ortools.sat.python import cp_model

from rota_ai.engine.models import DAYS, ROLES, SUPERVISOR, WEEKEND_DAYS, Rota, Shift, Staff

# Nobody may end up more than this many hours away from their contract.
DEFAULT_HOURS_TOLERANCE = 8

# How much each kind of unfairness costs in the score. One hour away from
# contract costs 1; each extra weekend shift of gap between two people in the
# same role costs 4. So hours matter more: moving a whole 8-hour shift away
# from someone's contract is never worth it just to even out one weekend shift.
HOURS_WEIGHT = 1
WEEKEND_WEIGHT = 4


class RotaInfeasibleError(Exception):
    """The rules contradict each other, so no valid rota exists."""


def solve_rota(
    staff: list[Staff],
    shifts: list[Shift],
    hours_tolerance: int = DEFAULT_HOURS_TOLERANCE,
    time_limit_seconds: float = 30,
) -> Rota:
    # Rule: a supervisor on every shift. It holds whatever the input data says.
    for shift in shifts:
        if shift.needs.get(SUPERVISOR, 0) < 1:
            raise ValueError(f"{shift.day} {shift.name} must need at least one supervisor")

    model = cp_model.CpModel()

    # Decisions: works[person, day, shift] is 1 if they work it, otherwise 0.
    works = {
        (person.name, shift.day, shift.name): model.new_bool_var(
            f"{person.name}_{shift.day}_{shift.name}"
        )
        for person in staff
        for shift in shifts
    }

    # Rule: everyone works at most one shift per day.
    for person in staff:
        for day in DAYS:
            model.add_at_most_one(
                works[person.name, shift.day, shift.name] for shift in shifts if shift.day == day
            )

    # Rule: nobody is rostered on a day they're unavailable.
    for person in staff:
        for shift in shifts:
            if shift.day in person.unavailable_days:
                model.add(works[person.name, shift.day, shift.name] == 0)

    # Rule: every shift gets exactly the people it needs in each role. People
    # only work their own role, so a barista never fills a cashier's place.
    for shift in shifts:
        for role in ROLES:
            model.add(
                sum(
                    works[person.name, shift.day, shift.name]
                    for person in staff
                    if person.role == role
                )
                == shift.needs.get(role, 0)
            )

    # Score part 1: distance between each person's hours and their contract.
    # The variable's upper limit is what makes the tolerance a hard rule.
    hours_off_contract = []
    for person in staff:
        hours_worked = sum(
            shift.hours * works[person.name, shift.day, shift.name] for shift in shifts
        )
        distance = model.new_int_var(0, hours_tolerance, f"{person.name}_hours_off")
        model.add_abs_equality(distance, hours_worked - person.contracted_hours)
        hours_off_contract.append(distance)

    # Score part 2: for each role, the gap between whoever has the most weekend
    # shifts and whoever has the fewest. Roles are compared separately because
    # each role has its own number of weekend places to share out.
    weekend_gaps = []
    max_shifts = len(shifts)
    for role in {person.role for person in staff}:
        weekend_counts = [
            sum(
                works[person.name, shift.day, shift.name]
                for shift in shifts
                if shift.day in WEEKEND_DAYS
            )
            for person in staff
            if person.role == role
        ]
        most = model.new_int_var(0, max_shifts, f"{role}_most_weekends")
        fewest = model.new_int_var(0, max_shifts, f"{role}_fewest_weekends")
        model.add_max_equality(most, weekend_counts)
        model.add_min_equality(fewest, weekend_counts)
        weekend_gaps.append(most - fewest)

    model.minimize(HOURS_WEIGHT * sum(hours_off_contract) + WEEKEND_WEIGHT * sum(weekend_gaps))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    # One worker and a fixed seed give the same rota every run on the same data.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)

    if status == cp_model.INFEASIBLE:
        raise RotaInfeasibleError(_explain_infeasible(staff, shifts, hours_tolerance))
    if status == cp_model.UNKNOWN:
        raise TimeoutError(f"No rota found within {time_limit_seconds} seconds")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Solver failed with status {solver.status_name(status)}")

    assignments = [
        (person.name, shift)
        for person in staff
        for shift in shifts
        if solver.value(works[person.name, shift.day, shift.name])
    ]
    return Rota(staff, shifts, assignments, is_optimal=status == cp_model.OPTIMAL)


def _explain_infeasible(staff: list[Staff], shifts: list[Shift], hours_tolerance: int) -> str:
    """Look for the most common cause: too few people available on a day."""
    problems = []
    for day in DAYS:
        for role in ROLES:
            needed = sum(shift.needs.get(role, 0) for shift in shifts if shift.day == day)
            available = sum(
                person.role == role and day not in person.unavailable_days for person in staff
            )
            if needed > available:
                problems.append(f"{day}: needs {needed} {role} shift(s), {available} available")
    if problems:
        return "No valid rota exists. " + "; ".join(problems)
    return (
        "No valid rota exists. Each day can be staffed on its own, so the likely cause is "
        f"keeping everyone within {hours_tolerance} hours of their contract."
    )
