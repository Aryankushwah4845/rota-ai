"""Applies a rules pack to one person: their age, their limits, and what blocks them.

Age is always worked out on the first day of the week, so nobody's limits change
halfway through a rota.
"""

from datetime import date, timedelta

from rota_ai.engine.models import DAYS, SUNDAY, Rota, Shift, Staff, date_of
from rota_ai.rules.base import RulesPack, WageBand, WageRates


def age_on(born: date, on: date) -> int:
    birthday_still_to_come = (on.month, on.day) < (born.month, born.day)
    return on.year - born.year - birthday_still_to_come


def can_be_rostered(person: Staff, week_start: date, rules: RulesPack) -> bool:
    return age_on(person.date_of_birth, week_start) >= rules.minimum_age


def is_young_worker(person: Staff, week_start: date, rules: RulesPack) -> bool:
    return can_be_rostered(person, week_start, rules) and (
        age_on(person.date_of_birth, week_start) < rules.adult_age
    )


def min_rest_hours(person: Staff, week_start: date, rules: RulesPack) -> int:
    if is_young_worker(person, week_start, rules):
        return rules.young_min_rest_hours
    return rules.adult_min_rest_hours


def weekly_hours_limit(person: Staff, week_start: date, rules: RulesPack) -> int | None:
    """The most hours they may work this week, or None if the law sets no limit for them."""
    if is_young_worker(person, week_start, rules):
        return rules.young_max_weekly_hours
    return None if person.opted_out_48h else rules.adult_max_weekly_hours


def break_minutes(person: Staff, shift: Shift, week_start: date, rules: RulesPack) -> int:
    """The break this person must get on this shift. 0 means none is required."""
    if is_young_worker(person, week_start, rules):
        return rules.young_break_minutes if shift.hours > rules.young_break_after_hours else 0
    return rules.adult_break_minutes if shift.hours > rules.adult_break_after_hours else 0


def target_hours(person: Staff, week_start: date) -> int:
    """Their contract, reduced fairly for time off on days they'd normally be able to work.

    Without this, someone on holiday all week would be "too far from their
    contract" and no rota could ever be made.
    """
    working_days = [day for day in DAYS if day not in person.unavailable_days]
    if not working_days:
        return person.contracted_hours
    days_off = sum(date_of(week_start, day) in person.time_off for day in working_days)
    return round(person.contracted_hours * (len(working_days) - days_off) / len(working_days))


def _night_rule(rules: RulesPack) -> tuple[set[int], str]:
    """The hours young workers can't work, and the plain-English reason why."""
    if rules.young_sector_exception:
        start, end = rules.young_sector_ban_start_hour, rules.young_sector_ban_end_hour
        wording = "under-18s can never work"
    else:
        start, end = rules.young_night_start_hour, rules.young_night_end_hour
        wording = "no work for under-18s"
    banned = {(start + hour) % 24 for hour in range((end - start) % 24)}
    return banned, f"{wording} between {start:02d}:00 and {end:02d}:00"


def shift_block_reason(person: Staff, shift: Shift, week_start: date, rules: RulesPack) -> str | None:
    """Why this person can never work this shift, in plain English, or None if they can."""
    name = person.name
    age = age_on(person.date_of_birth, week_start)
    if age < rules.minimum_age:
        return f"{name} is {age} and can't be rostered, because school-age workers need local council rules"

    for number in shift.day_numbers:
        if DAYS[number % 7] in person.unavailable_days:
            return f"{name} is unavailable on {DAYS[number % 7]}"
        on = week_start + timedelta(days=number)
        if on in person.time_off:
            return f"{name} has time off on {DAYS[number % 7]} {on.day} {on:%b}"
        if DAYS[number % 7] == SUNDAY and person.sunday_opt_out:
            return f"{name} has opted out of Sunday working"

    if is_young_worker(person, week_start, rules):
        cannot_work = f"{name} is {age} and can't work the {shift.clock_label} shift"
        if shift.hours > rules.young_max_daily_hours:
            return f"{cannot_work} (under-18s can't work more than {rules.young_max_daily_hours} hours a day)"
        banned_hours, night_wording = _night_rule(rules)
        if shift.clock_hours & banned_hours:
            return f"{cannot_work} ({night_wording})"
    return None


def wage_rates_for(on: date, rules: RulesPack) -> WageRates | None:
    """The newest rates that have started by this date, or None if we hold none that early."""
    started = [rates for rates in rules.minimum_wages if rates.effective_from <= on]
    return max(started, key=lambda rates: rates.effective_from, default=None)


def wage_band_for(age: int, rates: WageRates) -> WageBand | None:
    fitting = [band for band in rates.bands if age >= band.min_age]
    return max(fitting, key=lambda band: band.min_age, default=None)


def staff_warnings(staff: list[Staff], week_start: date, rules: RulesPack) -> list[str]:
    """Things the manager should know about. None of these stop a rota being made."""
    warnings = []
    rates = wage_rates_for(week_start, rules)
    for person in staff:
        age = age_on(person.date_of_birth, week_start)
        if age < rules.minimum_age:
            warnings.append(
                f"{person.name} is {age}, so they won't be rostered. School-age workers "
                "need local council rules: check with your council before giving them shifts."
            )
            continue
        if age == rules.minimum_age:
            warnings.append(
                f"{person.name} is {age}. Check they've reached school-leaving age, "
                "as they're covered by local council rules until then."
            )
        if is_young_worker(person, week_start, rules) and person.opted_out_48h:
            warnings.append(
                f"{person.name} is {age}, so their 48-hour opt-out doesn't count: "
                f"the {rules.young_max_weekly_hours}-hour limit still applies."
            )
        if person.hourly_rate is None or rates is None:
            continue
        band = wage_band_for(age, rates)
        if band and person.hourly_rate < band.hourly_rate:
            warning = (
                f"{person.name} is {age} and paid £{person.hourly_rate:.2f} an hour, below the "
                f"£{band.hourly_rate:.2f} legal minimum for age {band.label}."
            )
            if person.hourly_rate >= rates.apprentice_rate:
                warning += f" This is only allowed if they're an apprentice on the £{rates.apprentice_rate:.2f} rate."
            warnings.append(warning)

    if rates is None and any(person.hourly_rate is not None for person in staff):
        warnings.append(
            f"We don't hold minimum wage rates for the week of {week_start.day} {week_start:%B %Y}, "
            "so pay wasn't checked."
        )
    return warnings


def weekly_labour_cost(rota: Rota) -> tuple[float, list[str]]:
    """The week's total pay, and the names of anyone left out because they have no rate.

    All rostered hours count, so breaks are treated as paid.
    """
    total = 0.0
    no_rate = []
    for person in rota.staff:
        if person.hourly_rate is None:
            if rota.hours_for(person.name):
                no_rate.append(person.name)
        else:
            total += person.hourly_rate * rota.hours_for(person.name)
    return total, no_rate
