"""Focused tests for engine branches that don't reliably trigger in normal play.

Covers three paths the 100-game batch did NOT exercise:
  1. Bankruptcy to the bank (no creditor — owed money to the bank).
  2. Selling a hotel when the bank has fewer than 4 houses.
  3. The "Advance to nearest Utility" Chance card's 10×-new-dice rent.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monopoly.engine import GameEngine
from monopoly.loader import load_all
from monopoly.ruleset import us_2008
from monopoly.types import SellHouse


DATA_DIR = REPO_ROOT / "data"


def make_engine(seed: int = 42) -> GameEngine:
    """Construct a fresh 2-player engine with the standard data files."""
    board, chance, cc = load_all(DATA_DIR)
    return GameEngine(["Alice", "Bob"], us_2008(), board, chance, cc, seed=seed)


# ─────────────────────────────────────────────────────────────────
# 1. Bankruptcy-to-bank
# ─────────────────────────────────────────────────────────────────

def test_bankrupt_to_bank_when_owing_no_creditor():
    """A player who can't pay a bank-side charge (tax, building, card)
    after auto-liquidation goes bankrupt to the bank and is eliminated."""
    engine = make_engine()
    alice = engine.players[0]

    alice.money = 50  # not enough for a $200 charge
    # Alice owns nothing, so auto-liquidation can do nothing

    engine._charge(0, 200, "test_income_tax", creditor=None)
    engine._check_game_over()

    assert alice.is_bankrupt
    assert alice.money == 0
    assert engine.is_game_over
    assert engine.winner == 1


def test_bankrupt_to_bank_returns_properties_to_bank():
    """When a player bankrupts to the bank, their properties return to the
    bank — owner cleared, mortgage cleared, houses cleared."""
    engine = make_engine()
    alice = engine.players[0]

    # Alice owns Mediterranean (sq 1) — already mortgaged so liquidation can't help
    engine.properties[1].owner = 0
    engine.properties[1].is_mortgaged = True
    alice.money = 10

    engine._charge(0, 200, "test_tax", creditor=None)

    prop = engine.properties[1]
    assert prop.owner is None
    assert not prop.is_mortgaged
    assert prop.houses == 0


# ─────────────────────────────────────────────────────────────────
# 2. Hotel sell-down with insufficient houses in bank
# ─────────────────────────────────────────────────────────────────

def test_sell_hotel_normal_downgrade_when_bank_has_houses():
    """Sanity check on the normal path: with ≥4 houses available,
    selling a hotel downgrades to 4 houses and refunds house_cost / 2."""
    engine = make_engine()
    alice = engine.players[0]

    boardwalk = engine.properties[39]
    boardwalk.owner = 0
    boardwalk.houses = 5
    engine.bank_houses = 10
    engine.bank_hotels = engine.ruleset.max_hotels - 1
    money_before = alice.money

    engine._pending.clear()
    engine._can_roll_again = False
    engine._push_post_roll(0)
    engine.apply(SellHouse(property_index=39))

    assert boardwalk.houses == 4
    assert engine.bank_hotels == engine.ruleset.max_hotels   # hotel returned
    assert engine.bank_houses == 10 - 4                       # 4 houses placed
    assert alice.money - money_before == 100                  # 200 / 2


def test_sell_hotel_falls_back_when_bank_low_on_houses():
    """When the bank has fewer than 4 houses available, selling a hotel
    sells it entirely (no replacement houses) and refunds the full
    5 × house_cost / 2."""
    engine = make_engine()
    alice = engine.players[0]

    boardwalk = engine.properties[39]
    boardwalk.owner = 0
    boardwalk.houses = 5
    engine.bank_houses = 2                                    # < 4
    engine.bank_hotels = engine.ruleset.max_hotels - 1
    money_before = alice.money

    engine._pending.clear()
    engine._can_roll_again = False
    engine._push_post_roll(0)
    engine.apply(SellHouse(property_index=39))

    assert boardwalk.houses == 0                              # entire sale
    assert engine.bank_hotels == engine.ruleset.max_hotels    # hotel returned
    assert engine.bank_houses == 2                            # unchanged
    assert alice.money - money_before == 5 * 200 // 2         # = 500


# ─────────────────────────────────────────────────────────────────
# 3. 10×-dice utility card
# ─────────────────────────────────────────────────────────────────

def test_advance_to_nearest_utility_card_charges_10x_new_roll():
    """The Chance card 'Advance token to nearest Utility' overrides the
    normal 4×/10× utility rent.  Rent is always 10 × a NEW dice roll,
    regardless of how many utilities the owner holds."""
    engine = make_engine(seed=42)

    # Bob owns Electric Company only — normal rent would be 4× dice
    engine.properties[12].owner = 1
    assert engine.properties[28].owner is None

    rent = engine._calculate_rent(
        sq_idx=12,
        dice_total=2,                         # original landing roll (would give 8)
        via_card="nearest_utility",
        lander=0,
    )

    assert 20 <= rent <= 120                  # 10 × (2..12)
    assert rent % 10 == 0
    assert rent != 8                          # not normal-rent calculation


def test_normal_utility_rent_uses_landing_dice_total():
    """Sanity check: without the special card, rent uses the landing
    dice roll (4× for one utility owned, 10× for both)."""
    engine = make_engine()

    engine.properties[12].owner = 1
    assert engine._calculate_rent(12, dice_total=7) == 4 * 7

    engine.properties[28].owner = 1
    assert engine._calculate_rent(12, dice_total=7) == 10 * 7
