"""Action, Event, and PendingDecision types for the Monopoly engine.

Actions are data objects that players produce to advance the game.
Events are structured log records of everything that happens.
PendingDecision is what the engine advertises while waiting for input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


# ═══════════════════════════════════════════════════════════════════
# Actions
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RollDice:
    """Roll the dice and move."""

@dataclass(frozen=True)
class BuyProperty:
    """Buy the unowned property the player just landed on."""

@dataclass(frozen=True)
class DeclineProperty:
    """Decline to buy (auction in Stage 5; currently property stays unowned)."""

@dataclass(frozen=True)
class PayJailFine:
    """Pay the fine to leave jail, then roll normally."""

@dataclass(frozen=True)
class UseGOJFCard:
    """Use a Get Out of Jail Free card, then roll normally."""

@dataclass(frozen=True)
class AttemptJailRoll:
    """Try to roll doubles to escape jail."""

@dataclass(frozen=True)
class BuildHouse:
    """Build one house on the given property (even-build rules enforced)."""
    property_index: int

@dataclass(frozen=True)
class SellHouse:
    """Sell one house from the given property back to the bank at half price."""
    property_index: int

@dataclass(frozen=True)
class MortgageProperty:
    """Mortgage a property to receive half its printed price."""
    property_index: int

@dataclass(frozen=True)
class UnmortgageProperty:
    """Unmortgage a property by paying the mortgage amount plus 10 % interest."""
    property_index: int

@dataclass(frozen=True)
class EndTurn:
    """End the current turn and pass play to the next player."""

Action = Union[
    RollDice, BuyProperty, DeclineProperty,
    PayJailFine, UseGOJFCard, AttemptJailRoll,
    BuildHouse, SellHouse, MortgageProperty, UnmortgageProperty,
    EndTurn,
]


# ═══════════════════════════════════════════════════════════════════
# Events
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GameStarted:
    n_players: int
    seed: int
    player_names: tuple[str, ...]

@dataclass(frozen=True)
class TurnStarted:
    player: int
    turn: int

@dataclass(frozen=True)
class DiceRolled:
    player: int
    d1: int
    d2: int

@dataclass(frozen=True)
class PlayerMoved:
    player: int
    from_sq: int
    to_sq: int

@dataclass(frozen=True)
class PassedGo:
    player: int
    amount: int

@dataclass(frozen=True)
class CardDrawn:
    player: int
    deck: str          # "chance" or "community_chest"
    card_id: str
    card_text: str

@dataclass(frozen=True)
class PropertyBought:
    player: int
    square: int
    price: int

@dataclass(frozen=True)
class PropertyDeclined:
    player: int
    square: int

@dataclass(frozen=True)
class RentPaid:
    payer: int
    owner: int
    amount: int
    square: int

@dataclass(frozen=True)
class TaxPaid:
    player: int
    amount: int
    square: int

@dataclass(frozen=True)
class SentToJail:
    player: int
    reason: str        # "go_to_jail_square", "three_doubles", "chance_card", "cc_card"

@dataclass(frozen=True)
class LeftJail:
    player: int
    method: str        # "doubles", "paid_fine", "gojf_card"

@dataclass(frozen=True)
class JailRollFailed:
    player: int
    attempt: int

@dataclass(frozen=True)
class MoneyChanged:
    player: int
    amount: int        # positive = gained, negative = spent/lost
    reason: str

@dataclass(frozen=True)
class BuildingChanged:
    player: int
    square: int
    old_houses: int    # 0-5 (5 = hotel)
    new_houses: int

@dataclass(frozen=True)
class PropertyMortgaged:
    player: int
    square: int
    amount: int        # cash received

@dataclass(frozen=True)
class PropertyUnmortgaged:
    player: int
    square: int
    cost: int          # cash paid (mortgage + interest)

@dataclass(frozen=True)
class GOJFReceived:
    player: int
    deck: str

@dataclass(frozen=True)
class GOJFUsed:
    player: int
    deck: str

@dataclass(frozen=True)
class PlayerBankrupt:
    player: int
    creditor: int | None   # None → bankrupt to the bank

@dataclass(frozen=True)
class GameOver:
    winner: int
    turn: int

Event = Union[
    GameStarted, TurnStarted, DiceRolled, PlayerMoved, PassedGo,
    CardDrawn, PropertyBought, PropertyDeclined, RentPaid, TaxPaid,
    SentToJail, LeftJail, JailRollFailed, MoneyChanged,
    BuildingChanged, PropertyMortgaged, PropertyUnmortgaged,
    GOJFReceived, GOJFUsed, PlayerBankrupt, GameOver,
]


# ═══════════════════════════════════════════════════════════════════
# Pending decisions
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PendingDecision:
    """A decision the engine is waiting for from a specific player.

    ``actions`` enumerates every legal action.  The player picks exactly one
    and hands it to ``engine.apply()``.
    """
    player_index: int
    decision_type: str    # "roll", "buy_or_decline", "jail", "post_roll"
    prompt: str
    actions: list[Action]
