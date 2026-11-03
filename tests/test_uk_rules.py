"""One test (or more) for each UK rule, checked on small made-up rotas.

Everyone here is a supervisor, because every shift must have one, and the contract
tolerance is switched off so that only the rule being tested can get in the way.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import rota_ai.rules.uk
from rota_ai.engine.compliance import (
    age_on,
    break_minutes,
    staff_warnings,
    wage_band_for,
    wage_rates_for,
    weekly_labour_cost,
)
from rota_ai.engine.models import DAYS, SUPERVISOR, Shift, Staff
from rota_ai.engine.solver import RotaInfeasibleError, solve_rota
from rota_ai.rules.base import WageBand, WageRates
from rota_ai.rules.uk import UK_RULES, describe_rules

WEEK = date(2026, 11, 9)  # a Monday
ADULT_BORN = date(1990, 1, 1)
SEVENTEEN_BORN = date(2009, 3, 15)
EXCEPTION_ON = replace(UK_RULES, young_sector_exception=True)


def person(name="Alex", born=ADULT_BORN, contract=0, unavailable=(), **fields):
    return Staff(name, SUPERVISOR, contract, set(unavailable), born, **fields)


def shift(day, start, end, name="Shift"):
    return Shift(day, name, start, end, {SUPERVISOR: 1})


def solve(staff, shifts, rules=UK_RULES):
    return solve_rota(staff, shifts, WEEK, rules, hours_tolerance=1000)


def can_cover(staff, shifts, rules=UK_RULES):
    """True if this person (or team) can legally cover all these shifts."""
    try:
        solve(staff, shifts, rules)
        return True
    except RotaInfeasibleError:
        return False


def explanation(staff, shifts, rules=UK_RULES):
    with pytest.raises(RotaInfeasibleError) as error:
        solve(staff, shifts, rules)
    return str(error.value)


# Rule 1: adults need 11 hours' rest between shifts.


def test_adult_needs_11_hours_rest_between_shifts():
    assert not can_cover([person()], [shift("Mon", 15, 23), shift("Tue", 9, 17)])  # 10 hours
    assert can_cover([person()], [shift("Mon", 15, 23), shift("Tue", 10, 18)])  # 11 hours


def test_rest_rule_is_named_when_it_is_the_cause():
    message = explanation([person()], [shift("Mon", 15, 23), shift("Tue", 7, 15)])
    assert "rest between shifts" in message
    assert "11 hours" in message


def test_rest_counts_from_when_an_overnight_shift_really_ends():
    overnight = shift("Mon", 22, 6)  # finishes at 06:00 on Tuesday
    assert not can_cover([person()], [overnight, shift("Tue", 16, 20)])  # 10 hours
    assert can_cover([person()], [overnight, shift("Tue", 17, 21)])  # 11 hours


# Rule 2: adults need at least one full day off a week.


def test_adult_gets_a_full_day_off_each_week():
    every_day = [shift(day, 9, 17) for day in DAYS]
    assert not can_cover([person(opted_out_48h=True)], every_day)
    assert can_cover([person(opted_out_48h=True)], every_day[:6])


def test_days_off_rule_is_named_when_it_is_the_cause():
    every_day = [shift(day, 9, 17) for day in DAYS]
    assert "days off rule" in explanation([person(opted_out_48h=True)], every_day)


def test_a_shift_past_midnight_uses_up_the_next_day_too():
    # Monday to Saturday's shifts run overnight, so Sunday is never a clear day.
    shifts = [shift(day, 22, 6) for day in DAYS[:6]]
    assert not can_cover([person(opted_out_48h=True)], shifts)
    assert can_cover([person(opted_out_48h=True)], shifts[:5])


# Rule 3: 48 hours a week, unless opted out.


def test_48_hour_limit_applies_unless_opted_out():
    fifty_hours = [shift(day, 8, 18) for day in DAYS[:5]]
    assert not can_cover([person()], fifty_hours)
    assert can_cover([person(opted_out_48h=True)], fifty_hours)


def test_weekly_hours_rule_is_named_when_it_is_the_cause():
    fifty_hours = [shift(day, 8, 18) for day in DAYS[:5]]
    assert "weekly hours limit" in explanation([person()], fifty_hours)


def test_contract_above_the_limit_names_the_person():
    with pytest.raises(RotaInfeasibleError, match="Alex hasn't signed the 48-hour opt-out"):
        solve_rota([person(contract=60)], [shift("Mon", 9, 17)], WEEK, UK_RULES)


def test_todo_for_the_17_week_average_is_recorded():
    source = Path(rota_ai.rules.uk.__file__).read_text(encoding="utf-8")
    assert "TODO: the 48-hour limit" in source
    assert "AVERAGE over 17 weeks" in source


# Rule 4: adults get a 20-minute break on shifts over 6 hours.


def test_adult_break_only_on_shifts_over_6_hours():
    adult = person()
    assert break_minutes(adult, shift("Mon", 9, 16), WEEK, UK_RULES) == 20
    assert break_minutes(adult, shift("Mon", 9, 15), WEEK, UK_RULES) == 0


# Rule 5: under-18s work at most 8 hours a day and 40 a week, with no opt-out.


def test_young_worker_limited_to_8_hours_a_day():
    young = person("Lena", SEVENTEEN_BORN)
    assert can_cover([young], [shift("Mon", 8, 16)])
    message = explanation([young], [shift("Mon", 8, 17)])
    assert "Lena is 17 and can't work the 08:00-17:00 shift" in message
    assert "8 hours a day" in message


def test_young_worker_limited_to_40_hours_a_week_even_if_opted_out():
    # The 8-hour day and two days off already stop anyone going over 40 hours,
    # so allow longer days here to prove the weekly limit works by itself.
    longer_days = replace(UK_RULES, young_max_daily_hours=12)
    young = person("Lena", SEVENTEEN_BORN, opted_out_48h=True)
    assert can_cover([young], [shift(day, 8, 16) for day in DAYS[:5]], longer_days)  # 40 hours
    assert not can_cover([young], [shift(day, 8, 17) for day in DAYS[:5]], longer_days)  # 45 hours


def test_young_worker_contract_above_the_limit_is_explained():
    young = person("Lena", SEVENTEEN_BORN, contract=56)
    with pytest.raises(RotaInfeasibleError, match="Lena is 17 and can't work more than 40 hours a week"):
        solve_rota([young], [shift("Mon", 8, 16)], WEEK, UK_RULES)


def test_opt_out_flag_on_young_worker_gets_a_warning():
    warnings = staff_warnings([person("Lena", SEVENTEEN_BORN, opted_out_48h=True)], WEEK, UK_RULES)
    assert any("opt-out doesn't count" in warning for warning in warnings)


# Rule 6: under-18s need 12 hours' rest between shifts.


def test_young_worker_needs_12_hours_rest():
    young = person("Lena", SEVENTEEN_BORN)
    assert not can_cover([young], [shift("Mon", 14, 22), shift("Tue", 9, 17)])  # 11 hours
    assert can_cover([young], [shift("Mon", 14, 22), shift("Tue", 10, 18)])  # 12 hours
    # The same 11-hour gap is fine for an adult.
    assert can_cover([person()], [shift("Mon", 14, 22), shift("Tue", 9, 17)])


# Rule 7: under-18s need 48 hours off a week, which means two days in a row.


def test_young_worker_needs_two_days_off_in_a_row():
    young = person("Lena", SEVENTEEN_BORN)
    together = [shift(day, 9, 15) for day in ("Mon", "Tue", "Wed", "Thu", "Fri")]  # Sat, Sun off
    apart = [shift(day, 9, 15) for day in ("Mon", "Tue", "Wed", "Fri", "Sat")]  # Thu, Sun off
    assert can_cover([young], together)
    assert not can_cover([young], apart)
    # An adult can have separate days off.
    assert can_cover([person()], apart)


# Rule 8: under-18s get a 30-minute break on shifts over 4.5 hours.


def test_young_worker_break_only_on_shifts_over_4_and_a_half_hours():
    young = person("Lena", SEVENTEEN_BORN)
    assert break_minutes(young, shift("Mon", 9, 14), WEEK, UK_RULES) == 30
    assert break_minutes(young, shift("Mon", 9, 13), WEEK, UK_RULES) == 0
    # The same 5-hour shift doesn't require a break for an adult.
    assert break_minutes(person(), shift("Mon", 9, 14), WEEK, UK_RULES) == 0


# Rule 9: under-18s can't work at night, with a sector exception that still bans 00:00-04:00.


@pytest.mark.parametrize(
    "start, end, allowed",
    [
        (15, 23, False),  # overlaps 22:00-23:00
        (14, 22, True),  # finishes just as the night starts
        (5, 9, False),  # overlaps 05:00-06:00
        (6, 14, True),  # starts just as the night ends
    ],
)
def test_young_worker_blocked_from_night_shifts(start, end, allowed):
    assert can_cover([person("Lena", SEVENTEEN_BORN)], [shift("Mon", start, end)]) is allowed


@pytest.mark.parametrize(
    "start, end, allowed",
    [
        (15, 23, True),  # allowed by the exception
        (20, 24, True),  # finishes exactly at midnight
        (4, 9, True),  # starts exactly at 04:00
        (22, 2, False),  # runs past midnight
        (1, 5, False),  # inside the ban
        (3, 8, False),  # overlaps 03:00-04:00
    ],
)
def test_sector_exception_still_bans_midnight_to_4am(start, end, allowed):
    young = person("Lena", SEVENTEEN_BORN)
    assert can_cover([young], [shift("Mon", start, end)], EXCEPTION_ON) is allowed


def test_sector_exception_starts_switched_off():
    assert UK_RULES.young_sector_exception is False


def test_night_block_is_explained_in_plain_english():
    young = person("Lena", SEVENTEEN_BORN)
    message = explanation([young], [shift("Fri", 15, 23)])
    assert "Lena is 17 and can't work the 15:00-23:00 shift" in message
    assert "22:00" in message


# Rule 10: under-16s are never rostered, with a clear warning.


def test_under_16_is_not_rostered_and_gets_a_warning():
    child = person("Kai", date(2011, 6, 1), contract=40)
    adult = person("Alex", contract=8)
    rota = solve([child, adult], [shift("Mon", 9, 17)])
    assert [p.name for p in rota.staff] == ["Alex"]
    assert rota.shifts_for("Kai") == []
    warnings = staff_warnings([child, adult], WEEK, UK_RULES)
    assert any("Kai is 15" in warning and "local council" in warning for warning in warnings)


def test_under_16_is_named_when_nobody_else_can_work():
    message = explanation([person("Kai", date(2011, 6, 1))], [shift("Mon", 9, 17)])
    assert "Kai is 15 and can't be rostered" in message


def test_16_year_old_gets_a_school_leaving_age_warning():
    warnings = staff_warnings([person("Bo", date(2010, 1, 1))], WEEK, UK_RULES)
    assert any("school-leaving age" in warning for warning in warnings)


def test_age_is_worked_out_on_the_first_day_of_the_week():
    assert age_on(date(2008, 11, 9), WEEK) == 18  # turns 18 that Monday
    assert age_on(date(2008, 11, 10), WEEK) == 17  # turns 18 on the Tuesday
    # So someone turning 18 on the Tuesday is a young worker all week.
    turning_18 = person("Bo", date(2008, 11, 10))
    assert not can_cover([turning_18], [shift("Wed", 15, 23)])


# Rule 11: Sunday opt-out.


def test_sunday_opt_out_is_never_rostered_on_sunday():
    assert not can_cover([person(sunday_opt_out=True)], [shift("Sun", 9, 17)])
    assert can_cover([person()], [shift("Sun", 9, 17)])
    assert can_cover([person(sunday_opt_out=True)], [shift("Sat", 9, 17)])


def test_sunday_opt_out_covers_overnight_shifts_into_sunday():
    assert not can_cover([person(sunday_opt_out=True)], [shift("Sat", 22, 2)])


def test_sunday_opt_out_is_explained():
    message = explanation([person("Sam", sunday_opt_out=True)], [shift("Sun", 9, 17)])
    assert "Sam has opted out of Sunday working" in message


# Rule 12: minimum wage warnings and labour cost.


@pytest.mark.parametrize(
    "born, rate, warned",
    [
        (date(1990, 1, 1), 12.71, False),  # 21 and over, exactly the minimum
        (date(1990, 1, 1), 12.70, True),
        (date(2006, 1, 1), 10.85, False),  # aged 20
        (date(2006, 1, 1), 10.84, True),
        (date(2009, 3, 15), 8.00, False),  # aged 17
        (date(2009, 3, 15), 7.99, True),
    ],
)
def test_pay_below_the_minimum_for_their_age_is_warned(born, rate, warned):
    warnings = staff_warnings([person(born=born, hourly_rate=rate)], WEEK, UK_RULES)
    assert any("legal minimum" in warning for warning in warnings) is warned


def test_no_hourly_rate_means_no_pay_warning():
    assert staff_warnings([person()], WEEK, UK_RULES) == []


def test_apprentice_rate_is_mentioned_when_it_could_explain_the_pay():
    warnings = staff_warnings([person(hourly_rate=8.00)], WEEK, UK_RULES)
    assert "apprentice" in warnings[0]
    too_low_for_anyone = staff_warnings([person(hourly_rate=7.00)], WEEK, UK_RULES)
    assert "apprentice" not in too_low_for_anyone[0]


def test_wage_rates_stored_with_their_start_date():
    rates = wage_rates_for(WEEK, UK_RULES)
    assert rates.effective_from == date(2026, 4, 1)
    assert [wage_band_for(age, rates).hourly_rate for age in (21, 20, 18, 17, 16)] == [
        12.71,
        10.85,
        10.85,
        8.00,
        8.00,
    ]
    assert rates.apprentice_rate == 8.00


def test_newest_rates_that_have_started_are_used():
    next_year = WageRates(date(2027, 4, 1), (WageBand(21, "21 and over", 13.00),), 8.50)
    rules = replace(UK_RULES, minimum_wages=(*UK_RULES.minimum_wages, next_year))
    assert wage_rates_for(date(2027, 3, 29), rules).effective_from == date(2026, 4, 1)
    assert wage_rates_for(date(2027, 4, 5), rules).effective_from == date(2027, 4, 1)


def test_week_before_any_rates_says_pay_was_not_checked():
    early_week = date(2026, 3, 30)
    warnings = staff_warnings([person(hourly_rate=5.00)], early_week, UK_RULES)
    assert len(warnings) == 1
    assert "pay wasn't checked" in warnings[0]


def test_labour_cost_adds_up_and_names_anyone_without_a_rate():
    paid = person("Alex", hourly_rate=15.00)
    unpaid = person("Bo")
    rota = solve([paid, unpaid], [shift("Mon", 9, 17, "One"), shift("Tue", 9, 13, "Two")])
    cost, no_rate = weekly_labour_cost(rota)
    assert cost == 15.00 * rota.hours_for("Alex")
    assert no_rate == (["Bo"] if rota.hours_for("Bo") else [])


# Rule 13: the Employment Rights Act 2025 is recorded for later.


def test_todo_for_the_employment_rights_act_2025_is_recorded():
    source = Path(rota_ai.rules.uk.__file__).read_text(encoding="utf-8")
    assert "TODO: the Employment Rights Act 2025" in source


# The rules pack itself.


def test_rules_table_shows_every_rule_and_the_exception():
    rules_text = str(describe_rules(UK_RULES))
    for expected in ("11 hours", "48", "40 a week", "12 hours", "2 days off in a row", "22:00-06:00", "£12.71", "£8.00"):
        assert expected in rules_text
    assert "00:00-04:00" in str(describe_rules(EXCEPTION_ON))
