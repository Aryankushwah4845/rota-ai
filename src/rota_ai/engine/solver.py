"""The rota solver, built on Google OR-Tools' CP-SAT.

We never tell the computer *how* to build a rota. We describe:
  1. decisions - one yes/no question per person and shift: "do they work it?"
  2. hard rules - things that must always be true
  3. a score - what makes one valid rota better than another
CP-SAT then searches for the valid answer with the lowest score.

The legal values come from a rules pack (see rota_ai/rules), so nothing here is
specific to one country.
"""

from datetime import date

from ortools.sat.python import cp_model

from rota_ai.engine.compliance import (
    age_on,
    can_be_rostered,
    is_young_worker,
    min_rest_hours,
    shift_block_reason,
    target_hours,
    weekly_hours_limit,
)
from rota_ai.engine.models import DAYS, ROLES, SUPERVISOR, WEEKEND_DAYS, Rota, Shift, Staff
from rota_ai.rules.base import RulesPack

# Nobody may end up more than this many hours away from their contract.
DEFAULT_HOURS_TOLERANCE = 8

# How much each kind of unfairness costs in the score. One hour away from
# contract costs 1; each extra weekend shift of gap between two people in the
# same role costs 4. So hours matter more: moving a whole 8-hour shift away
# from someone's contract is never worth it just to even out one weekend shift.
HOURS_WEIGHT = 1
WEEKEND_WEIGHT = 4

# The groups of rules that apply across a whole week. When no rota exists, we
# try again without each group in turn to find out which one is responsible.
DAILY_REST = "daily rest"
WEEKLY_REST = "weekly rest"
WEEKLY_HOURS = "weekly hours"
CONTRACT_HOURS = "contract hours"
# Big enough that the contract rule stops mattering, but still a whole number.
NO_TOLERANCE_LIMIT = 100_000
EXPLAIN_TIME_LIMIT_SECONDS = 5


class RotaInfeasibleError(Exception):
    """The rules contradict each other, so no valid rota exists."""

    def __init__(self, problems: list[str]):
        super().__init__("No valid rota exists. " + "; ".join(problems))
        self.problems = problems


def solve_rota(
    staff: list[Staff],
    shifts: list[Shift],
    week_start: date,
    rules: RulesPack,
    hours_tolerance: int = DEFAULT_HOURS_TOLERANCE,
    time_limit_seconds: float = 30,
) -> Rota:
    if week_start.weekday() != 0:
        raise ValueError(f"A rota must start on a Monday, but {week_start} isn't one")

    # Rule: a supervisor on every shift. It holds whatever the input data says.
    for shift in shifts:
        if shift.needs.get(SUPERVISOR, 0) < 1:
            raise ValueError(f"{shift.day} {shift.name} must need at least one supervisor")

    # Rule: people under the minimum age are left off the rota altogether.
    workers = [person for person in staff if can_be_rostered(person, week_start, rules)]

    model, works = _build_model(workers, shifts, week_start, rules, hours_tolerance)
    solver = _new_solver(time_limit_seconds)
    status = solver.solve(model)

    if status == cp_model.INFEASIBLE:
        raise RotaInfeasibleError(_explain_infeasible(staff, shifts, week_start, rules, hours_tolerance))
    if status == cp_model.UNKNOWN:
        raise TimeoutError(f"No rota found within {time_limit_seconds} seconds")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Solver failed with status {solver.status_name(status)}")

    assignments = [
        (person.name, shift)
        for person in workers
        for shift in shifts
        if solver.value(works[person.name, shift.day, shift.name])
    ]
    return Rota(workers, shifts, assignments, status == cp_model.OPTIMAL, week_start, rules)


def _new_solver(time_limit_seconds: float) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    # One worker and a fixed seed give the same rota every run on the same data.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    return solver


def _build_model(
    staff: list[Staff],
    shifts: list[Shift],
    week_start: date,
    rules: RulesPack,
    hours_tolerance: int,
    leave_out: str | None = None,
) -> tuple[cp_model.CpModel, dict]:
    """Describes the rota problem. leave_out names one group of rules to skip."""
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

    # Rule: nobody gets a shift that's ruled out for them alone: they're
    # unavailable, on time off, opted out of Sundays, or too young for it.
    for person in staff:
        for shift in shifts:
            if shift_block_reason(person, shift, week_start, rules):
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

    # Rule: enough rest between any two shifts. Each too-close pair can't both be worked.
    if leave_out != DAILY_REST:
        for person in staff:
            rest_needed = min_rest_hours(person, week_start, rules)
            for index, first in enumerate(shifts):
                for second in shifts[index + 1:]:
                    gap = max(second.starts_at - first.ends_at, first.starts_at - second.ends_at)
                    if gap < rest_needed:
                        model.add_at_most_one(
                            [
                                works[person.name, first.day, first.name],
                                works[person.name, second.day, second.name],
                            ]
                        )

    # Rule: enough days off each week. A shift that runs past midnight uses up both days.
    if leave_out != WEEKLY_REST:
        for person in staff:
            works_on_day = [model.new_bool_var(f"{person.name}_works_{day}") for day in DAYS]
            for shift in shifts:
                for number in shift.day_numbers:
                    if number < len(DAYS):
                        model.add_implication(
                            works[person.name, shift.day, shift.name], works_on_day[number]
                        )
            if is_young_worker(person, week_start, rules):
                # Young workers need their days off in one block, so at least
                # one of these possible blocks must be completely free.
                block_length = rules.young_consecutive_days_off
                block_is_free = []
                for first_day in range(len(DAYS) - block_length + 1):
                    is_free = model.new_bool_var(f"{person.name}_free_from_{first_day}")
                    for number in range(first_day, first_day + block_length):
                        model.add(works_on_day[number] == 0).only_enforce_if(is_free)
                    block_is_free.append(is_free)
                model.add_bool_or(block_is_free)
            else:
                model.add(sum(works_on_day) <= len(DAYS) - rules.adult_days_off_per_week)

    # Rule: no more than the legal hours in the week.
    if leave_out != WEEKLY_HOURS:
        for person in staff:
            limit = weekly_hours_limit(person, week_start, rules)
            if limit is not None:
                model.add(
                    sum(shift.hours * works[person.name, shift.day, shift.name] for shift in shifts)
                    <= limit
                )

    # Score part 1: distance between each person's hours and their contract.
    # The variable's upper limit is what makes the tolerance a hard rule.
    tolerance = NO_TOLERANCE_LIMIT if leave_out == CONTRACT_HOURS else hours_tolerance
    hours_off_contract = []
    for person in staff:
        hours_worked = sum(
            shift.hours * works[person.name, shift.day, shift.name] for shift in shifts
        )
        distance = model.new_int_var(0, tolerance, f"{person.name}_hours_off")
        model.add_abs_equality(distance, hours_worked - target_hours(person, week_start))
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
    return model, works


def _explain_infeasible(
    staff: list[Staff],
    shifts: list[Shift],
    week_start: date,
    rules: RulesPack,
    hours_tolerance: int,
) -> list[str]:
    """Works out which rule is to blame, starting with the clearest causes."""
    return (
        _too_few_people(staff, shifts, week_start, rules)
        or _contracts_over_the_limit(staff, week_start, rules, hours_tolerance)
        or _week_long_rules_to_blame(staff, shifts, week_start, rules, hours_tolerance)
    )


def _too_few_people(
    staff: list[Staff], shifts: list[Shift], week_start: date, rules: RulesPack
) -> list[str]:
    """Days and shifts that can't be filled, and exactly who is blocked from them."""
    problems = []
    reasons = {}  # a dict rather than a set, to keep them in order

    def blocked(person: Staff, shift: Shift) -> str | None:
        return shift_block_reason(person, shift, week_start, rules)

    for day in DAYS:
        for role in ROLES:
            todays_shifts = [shift for shift in shifts if shift.day == day and shift.needs.get(role, 0)]
            team = [person for person in staff if person.role == role]

            needed = sum(shift.needs[role] for shift in todays_shifts)
            available = sum(
                any(not blocked(person, shift) for shift in todays_shifts) for person in team
            )
            day_is_short = needed > available
            if day_is_short:
                problems.append(f"{day}: needs {needed} {role} shift(s), {available} available")

            for shift in todays_shifts:
                free = sum(not blocked(person, shift) for person in team)
                shift_is_short = shift.needs[role] > free
                if shift_is_short and not day_is_short:
                    problems.append(
                        f"{day} {shift.name}: needs {shift.needs[role]} {role}(s), {free} can work it"
                    )
                if shift_is_short or day_is_short:
                    reasons.update(dict.fromkeys(filter(None, (blocked(p, shift) for p in team))))
    return problems + list(reasons)


def _contracts_over_the_limit(
    staff: list[Staff], week_start: date, rules: RulesPack, hours_tolerance: int
) -> list[str]:
    """People whose contract can't be met without going over their legal weekly hours."""
    problems = []
    for person in staff:
        if not can_be_rostered(person, week_start, rules):
            continue
        limit = weekly_hours_limit(person, week_start, rules)
        if limit is None or target_hours(person, week_start) - hours_tolerance <= limit:
            continue
        if is_young_worker(person, week_start, rules):
            who = f"{person.name} is {age_on(person.date_of_birth, week_start)} and can't work more than {limit} hours a week"
        else:
            who = f"{person.name} hasn't signed the {limit}-hour opt-out"
        problems.append(
            f"{who}, so they can't get within {hours_tolerance} hours of their "
            f"{person.contracted_hours}-hour contract."
        )
    return problems


def _week_long_rules_to_blame(
    staff: list[Staff],
    shifts: list[Shift],
    week_start: date,
    rules: RulesPack,
    hours_tolerance: int,
) -> list[str]:
    """Tries again without each group of rules: if a rota appears, that group was the cause."""
    workers = [person for person in staff if can_be_rostered(person, week_start, rules)]
    explanations = {
        DAILY_REST: (
            f"The rest between shifts rule is blocking this: {rules.adult_min_rest_hours} hours for "
            f"adults and {rules.young_min_rest_hours} for under-18s. Too many people would need to "
            "finish late and start early the next day."
        ),
        WEEKLY_REST: (
            f"The days off rule is blocking this: {rules.adult_days_off_per_week} full day off a week "
            f"for adults and {rules.young_consecutive_days_off} days off in a row for under-18s."
        ),
        WEEKLY_HOURS: (
            f"The weekly hours limit is blocking this: {rules.adult_max_weekly_hours} hours for adults "
            f"who haven't opted out and {rules.young_max_weekly_hours} for under-18s."
        ),
        CONTRACT_HOURS: (
            "Each day can be staffed on its own, so the likely cause is keeping everyone "
            f"within {hours_tolerance} hours of their contract."
        ),
    }
    problems = []
    for leave_out, explanation in explanations.items():
        model, _ = _build_model(workers, shifts, week_start, rules, hours_tolerance, leave_out)
        status = _new_solver(EXPLAIN_TIME_LIMIT_SECONDS).solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            problems.append(explanation)
    return problems or [
        "Several rules clash at once: rest between shifts, days off, weekly hours "
        f"and keeping everyone within {hours_tolerance} hours of their contract."
    ]
