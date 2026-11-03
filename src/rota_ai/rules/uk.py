"""The UK rules pack. Every value here comes from the law named beside it.

"WTR" means the Working Time Regulations 1998 (SI 1998/1833), which cover
England, Wales and Scotland. Northern Ireland has its own, very similar version.

To change a legal value, change it here: nothing else in the project holds one.
These rules are a guide, not legal advice.

TODO: the 48-hour limit in WTR reg 4 is really an AVERAGE over 17 weeks, and we
check it against one week, which is stricter. Doing it properly needs past
rotas, so add it when we add history.

TODO: the rest rules can only see one rota at a time, so a late Sunday shift
followed by an early Monday shift in the next rota isn't caught. Check this
across rotas when we add history.

TODO: the Employment Rights Act 2025 will add reasonable notice of shifts and
pay for short-notice cancellations. Those parts aren't in force yet. Add them
here when they start.
"""

from datetime import date

from rota_ai.rules.base import RulesPack, WageBand, WageRates

UK_RULES = RulesPack(
    name="United Kingdom",
    # Under-16s are of compulsory school age, so local council byelaws apply
    # (Children and Young Persons Act 1933, s.18). We don't roster them at all.
    minimum_age=16,
    # WTR reg 2: a "young worker" is over compulsory school age but under 18.
    adult_age=18,
    # WTR reg 10(1): 11 consecutive hours' rest in each 24 hours.
    adult_min_rest_hours=11,
    # WTR reg 11(1): 24 uninterrupted hours off in each 7 days. We give a full
    # calendar day, which always covers it. Weeks start on Monday (reg 11(6)).
    adult_days_off_per_week=1,
    # WTR reg 4(1): 48 hours a week, unless the worker signs an opt-out.
    adult_max_weekly_hours=48,
    # WTR reg 12(1) and (3): 20 minutes when the working day is over 6 hours.
    adult_break_after_hours=6,
    adult_break_minutes=20,
    # WTR reg 5A: 8 hours a day and 40 a week. There is no opt-out.
    young_max_daily_hours=8,
    young_max_weekly_hours=40,
    # WTR reg 10(2): 12 consecutive hours' rest in each 24 hours.
    young_min_rest_hours=12,
    # WTR reg 11(3): 48 hours off in each 7 days. These have to be in one
    # block, so two separate days off would not count.
    young_consecutive_days_off=2,
    # WTR reg 12(4): 30 minutes when the working day is over 4.5 hours.
    young_break_after_hours=4.5,
    young_break_minutes=30,
    # WTR reg 6A: no work in the "restricted period", normally 22:00-06:00.
    young_night_start_hour=22,
    young_night_end_hour=6,
    # WTR reg 27A(2): retail, catering, hotels, pubs, restaurants and bars can
    # use young workers at night, but never between midnight and 04:00. It is
    # only allowed if no adult is available, the work keeps the service running
    # or meets a surge in demand, and the young worker gets supervision and
    # time off in lieu. The manager has to judge that, so it starts switched off.
    young_sector_exception=False,
    young_sector_ban_start_hour=0,
    young_sector_ban_end_hour=4,
    # National Minimum Wage Act 1998 and National Minimum Wage Regulations 2015.
    # Add each April's new rates to the end of this list.
    minimum_wages=(
        WageRates(
            effective_from=date(2026, 4, 1),
            bands=(
                WageBand(min_age=21, label="21 and over", hourly_rate=12.71),
                WageBand(min_age=18, label="18-20", hourly_rate=10.85),
                WageBand(min_age=16, label="16-17", hourly_rate=8.00),
            ),
            apprentice_rate=8.00,
        ),
    ),
)


def describe_rules(rules: RulesPack) -> list[dict]:
    """The rules in plain English, for the app's "Rules" section."""
    wtr = "Working Time Regulations 1998"
    if rules.young_sector_exception:
        night_rule = (
            f"No work {rules.young_sector_ban_start_hour:02d}:00-"
            f"{rules.young_sector_ban_end_hour:02d}:00 (sector exception on)"
        )
    else:
        night_rule = f"No work {rules.young_night_start_hour:02d}:00-{rules.young_night_end_hour:02d}:00"

    table = [
        ("Adults: rest between shifts", f"At least {rules.adult_min_rest_hours} hours", f"{wtr}, reg 10"),
        ("Adults: weekly rest", f"At least {rules.adult_days_off_per_week} full day off", f"{wtr}, reg 11"),
        ("Adults: weekly hours", f"Up to {rules.adult_max_weekly_hours}, unless opted out", f"{wtr}, reg 4"),
        (
            "Adults: breaks",
            f"{rules.adult_break_minutes} minutes for shifts over {rules.adult_break_after_hours:g} hours",
            f"{wtr}, reg 12",
        ),
        (
            "Ages 16-17: working hours",
            f"Up to {rules.young_max_daily_hours} a day and {rules.young_max_weekly_hours} a week, no opt-out",
            f"{wtr}, reg 5A",
        ),
        ("Ages 16-17: rest between shifts", f"At least {rules.young_min_rest_hours} hours", f"{wtr}, reg 10"),
        (
            "Ages 16-17: weekly rest",
            f"At least {rules.young_consecutive_days_off} days off in a row",
            f"{wtr}, reg 11",
        ),
        (
            "Ages 16-17: breaks",
            f"{rules.young_break_minutes} minutes for shifts over {rules.young_break_after_hours:g} hours",
            f"{wtr}, reg 12",
        ),
        ("Ages 16-17: night work", night_rule, f"{wtr}, regs 6A and 27A"),
        (
            "Under 16",
            "Never rostered: local council rules apply",
            "Children and Young Persons Act 1933",
        ),
        (
            "Sunday working",
            "Never rostered on a Sunday if they've opted out",
            "Employment Rights Act 1996, Part IV (shop workers, England and Wales)",
        ),
    ]
    for rates in rules.minimum_wages:
        starts = f"{rates.effective_from.day} {rates.effective_from:%B %Y}"
        for band in rates.bands:
            table.append(
                (f"Minimum wage, {band.label}", f"£{band.hourly_rate:.2f} an hour from {starts}", "National Minimum Wage Act 1998")
            )
        table.append(
            ("Minimum wage, apprentice", f"£{rates.apprentice_rate:.2f} an hour from {starts}", "National Minimum Wage Act 1998")
        )
    return [{"Rule": rule, "Value": value, "Source": source} for rule, value, source in table]
