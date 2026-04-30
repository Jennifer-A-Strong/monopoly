"""Movement-only Monopoly simulator (Stage 1).

Tracks how often each of the 40 squares is landed on across many dice rolls.
No economics: no money, no property ownership, no rent.

All randomness flows through a single random.Random instance so results are
fully reproducible given the same seed.
"""

from __future__ import annotations

import random
from typing import Any

BOARD_SIZE = 40
JAIL_SQUARE = 10       # "Just Visiting / Jail"
GO_TO_JAIL_SQUARE = 30
GO_SQUARE = 0

RAILROAD_SQUARES: frozenset[int] = frozenset({5, 15, 25, 35})
UTILITY_SQUARES: frozenset[int] = frozenset({12, 28})


def _nearest_forward(current: int, targets: frozenset[int]) -> int:
    """Return the first target square reached by moving forward from current (wraps)."""
    for offset in range(1, BOARD_SIZE + 1):
        candidate = (current + offset) % BOARD_SIZE
        if candidate in targets:
            return candidate
    raise ValueError(f"No targets found among {targets}")  # unreachable with valid data


class MovementSimulator:
    """
    Simulates movement around a Monopoly board.

    Jail strategies
    ---------------
    "roll_for_doubles"
        Try to roll doubles each turn in jail. Forced out after 3 failed attempts
        (moving by whatever was rolled on the 3rd turn). Rolling doubles to escape
        does NOT grant an extra roll.
    "pay_immediately"
        Always pay the fine on the first jail turn and move normally.
    """

    def __init__(
        self,
        board: list[dict[str, Any]],
        chance_cards: list[dict[str, Any]],
        cc_cards: list[dict[str, Any]],
        seed: int = 42,
        jail_strategy: str = "roll_for_doubles",
    ) -> None:
        if jail_strategy not in ("roll_for_doubles", "pay_immediately"):
            raise ValueError(f"Unknown jail_strategy: {jail_strategy!r}")

        self.board = board
        self._chance_cards = list(chance_cards)
        self._cc_cards = list(cc_cards)
        self.jail_strategy = jail_strategy
        self.rng = random.Random(seed)

        # Quick type-lookup by index (board is already sorted by loader)
        self._sq_type: list[str] = [sq["type"] for sq in board]

        # Sanity-check the squares we depend on
        assert self._sq_type[JAIL_SQUARE] == "jail", \
            f"Expected square {JAIL_SQUARE} to be 'jail', got {self._sq_type[JAIL_SQUARE]!r}"
        assert self._sq_type[GO_TO_JAIL_SQUARE] == "go_to_jail", \
            f"Expected square {GO_TO_JAIL_SQUARE} to be 'go_to_jail', got {self._sq_type[GO_TO_JAIL_SQUARE]!r}"

        # Shuffle both decks once at startup; they reshuffle when exhausted
        self.rng.shuffle(self._chance_cards)
        self.rng.shuffle(self._cc_cards)
        self._chance_idx = 0
        self._cc_idx = 0

        # Accumulated landing counts, indexed by square
        self.visits: list[int] = [0] * BOARD_SIZE

        # Token state
        self._square = 0
        self._in_jail = False
        self._jail_turns = 0          # turns spent in jail this stretch
        self._consecutive_doubles = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _roll_dice(self) -> tuple[int, int]:
        return self.rng.randint(1, 6), self.rng.randint(1, 6)

    def _draw_chance(self) -> dict[str, Any]:
        card = self._chance_cards[self._chance_idx]
        self._chance_idx += 1
        if self._chance_idx >= len(self._chance_cards):
            self._chance_idx = 0
            self.rng.shuffle(self._chance_cards)
        return card

    def _draw_cc(self) -> dict[str, Any]:
        card = self._cc_cards[self._cc_idx]
        self._cc_idx += 1
        if self._cc_idx >= len(self._cc_cards):
            self._cc_idx = 0
            self.rng.shuffle(self._cc_cards)
        return card

    def _send_to_jail(self) -> None:
        self._square = JAIL_SQUARE
        self._in_jail = True
        self._jail_turns = 0
        self._consecutive_doubles = 0

    def _apply_card(self, card: dict[str, Any], from_square: int) -> None:
        """
        Apply a card's movement effect, updating self._square (and jail state).
        from_square is the square on which the card was drawn (needed for move_relative).
        Financial cards are no-ops in Stage 1.
        """
        kind = card["kind"]

        if kind == "move_absolute":
            self._square = card["square"]
            # Landing on Go to Jail via card sends you to jail
            if self._square == GO_TO_JAIL_SQUARE:
                self._send_to_jail()

        elif kind == "move_relative":
            self._square = (from_square + card["offset"]) % BOARD_SIZE
            if self._square == GO_TO_JAIL_SQUARE:
                self._send_to_jail()

        elif kind == "move_nearest":
            target_type = card["target_type"]
            targets = RAILROAD_SQUARES if target_type == "railroad" else UTILITY_SQUARES
            self._square = _nearest_forward(from_square, targets)

        elif kind == "go_to_jail":
            self._send_to_jail()

        # get_out_of_jail: no movement in Stage 1 (card ownership not tracked)
        # Financial kinds: no-op in Stage 1

    def _handle_landing(self) -> None:
        """
        Process the effects of the current square, looping to handle chained
        card effects (e.g. "Go Back 3" from Chance at 36 → Community Chest at 33
        → draw a CC card).

        Updates self._square in place; caller records visits after this returns.
        """
        while True:
            sq_type = self._sq_type[self._square]

            if sq_type == "go_to_jail":
                self._send_to_jail()
                break

            elif sq_type == "chance":
                from_sq = self._square
                card = self._draw_chance()
                self._apply_card(card, from_sq)
                if self._in_jail:
                    break
                if self._square == from_sq:
                    break  # card had no movement effect
                # Card moved us; loop to handle the new square

            elif sq_type == "community_chest":
                from_sq = self._square
                card = self._draw_cc()
                self._apply_card(card, from_sq)
                if self._in_jail:
                    break
                if self._square == from_sq:
                    break
                # Card moved us; loop to handle the new square

            else:
                break  # ordinary square, nothing to do

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def simulate(self, n_rolls: int) -> list[int]:
        """
        Simulate n_rolls individual dice rolls.

        Each time the dice are picked up and thrown counts as one roll,
        including the extra rolls granted by doubles. Returns the visit-count
        list (self.visits) after all rolls are complete.
        """
        rolls_done = 0

        while rolls_done < n_rolls:
            d1, d2 = self._roll_dice()
            rolls_done += 1
            is_doubles = (d1 == d2)
            total = d1 + d2

            if self._in_jail:
                self._jail_turns += 1

                if self.jail_strategy == "pay_immediately":
                    # Pay fine, leave immediately, move by this roll's total
                    self._in_jail = False
                    self._jail_turns = 0
                    self._consecutive_doubles = 0
                    self._square = (JAIL_SQUARE + total) % BOARD_SIZE
                    self._handle_landing()
                    self.visits[self._square] += 1

                else:  # roll_for_doubles
                    if is_doubles or self._jail_turns >= 3:
                        # Get out: move by this roll's total.
                        # Doubles in jail do NOT grant an extra roll.
                        self._in_jail = False
                        self._jail_turns = 0
                        self._consecutive_doubles = 0
                        self._square = (JAIL_SQUARE + total) % BOARD_SIZE
                        self._handle_landing()
                        self.visits[self._square] += 1
                    else:
                        # Remain in jail; count the jail square as the landing
                        self.visits[JAIL_SQUARE] += 1

            else:
                # Not in jail
                if is_doubles:
                    self._consecutive_doubles += 1
                else:
                    self._consecutive_doubles = 0

                if self._consecutive_doubles >= 3:
                    # Third consecutive doubles → go directly to jail,
                    # do not complete the move
                    self._send_to_jail()
                    self.visits[JAIL_SQUARE] += 1
                else:
                    self._square = (self._square + total) % BOARD_SIZE
                    self._handle_landing()
                    self.visits[self._square] += 1
                    # If doubles (and not now in jail), the loop naturally
                    # continues and the player rolls again next iteration

        return self.visits


def run_simulation(
    board: list[dict[str, Any]],
    chance_cards: list[dict[str, Any]],
    cc_cards: list[dict[str, Any]],
    n_rolls: int = 10_000_000,
    seed: int = 42,
    jail_strategy: str = "roll_for_doubles",
) -> list[int]:
    """Convenience wrapper. Returns visit counts per square (list of 40 ints)."""
    sim = MovementSimulator(board, chance_cards, cc_cards, seed, jail_strategy)
    return sim.simulate(n_rolls)
