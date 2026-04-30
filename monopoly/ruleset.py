"""RuleSet configuration — every tunable parameter in one place.

Engine code reads from the RuleSet; there are no ``if era == ...`` branches.
Pre-2008 vs. post-2008 is a configuration, not a code branch.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleSet:
    starting_money: int = 1500
    go_salary: int = 200
    jail_fine: int = 50
    income_tax: int = 200       # flat in post-2008
    luxury_tax: int = 100       # $75 in pre-2008
    max_houses: int = 32
    max_hotels: int = 12
    doubles_to_jail: int = 3
    max_jail_turns: int = 3
    mortgage_rate: float = 0.5          # receive price × rate
    unmortgage_interest: float = 0.10   # 10 % surcharge to unmortgage
    house_sell_rate: float = 0.5        # sell houses at half purchase price
    max_turns: int = 1000               # safety valve for infinite games
    # House rules (all off by default)
    double_salary_on_landing: bool = False   # $400 for landing exactly on Go
    free_parking_jackpot: bool = False       # fines pool on Free Parking


# ── Preset constructors ──────────────────────────────────────────

def us_2008() -> RuleSet:
    """Post-2008, pre-2021 US Standard Edition — the canonical target."""
    return RuleSet()


def us_1935() -> RuleSet:
    """Pre-2008 US rules (Luxury Tax $75; Income Tax choice is a future refinement)."""
    return RuleSet(luxury_tax=75)


def family_game() -> RuleSet:
    """Common house rules layered on top of the 2008 base."""
    return RuleSet(double_salary_on_landing=True, free_parking_jackpot=True)
