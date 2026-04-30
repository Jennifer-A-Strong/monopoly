"""Mutable game-state objects used by the engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerState:
    """Per-player mutable state."""
    index: int
    name: str
    position: int = 0          # board square index (0–39)
    money: int = 1500
    in_jail: bool = False
    jail_turns: int = 0
    consecutive_doubles: int = 0
    is_bankrupt: bool = False
    # Each entry is the card-id of a held Get Out of Jail Free card.
    gojf_cards: list[str] = field(default_factory=list)


@dataclass
class PropertyState:
    """Per-property mutable state."""
    square_index: int
    owner: int | None = None        # player index, or None (bank)
    houses: int = 0                 # 0–4 = houses, 5 = hotel
    is_mortgaged: bool = False
