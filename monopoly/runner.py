"""GameRunner — thin loop that drives a game by asking players for decisions.

The runner is a *client* of the engine, not part of it.  The MCP server
(Stage 4) will be a different client of the same engine.
"""

from __future__ import annotations

from typing import Any, Protocol

from .engine import GameEngine
from .types import Action, Event, PendingDecision


class PlayerLike(Protocol):
    name: str
    def decide(self, state_view: dict[str, Any], decision: PendingDecision) -> Action: ...


class GameRunner:
    """Drive a game to completion, feeding decisions from player objects."""

    def __init__(
        self,
        engine: GameEngine,
        players: list[PlayerLike],
        verbose: bool = False,
        renderer: Any | None = None,
    ) -> None:
        self.engine = engine
        self.players = players
        self.verbose = verbose
        self.renderer = renderer

    def run(self) -> int | None:
        """Run the game until completion.  Returns the winner's player index (or None)."""
        while not self.engine.is_game_over:
            decision = self.engine.get_pending()
            if decision is None:
                break

            pi = decision.player_index
            player = self.players[pi]

            # Build a state view for the player
            sv = self._build_state_view(pi)

            # Ask the player to decide
            action = player.decide(sv, decision)

            # Apply and optionally print
            events = self.engine.apply(action)
            if self.verbose:
                for ev in events:
                    print(f"  [{type(ev).__name__}] {ev}")

            if self.verbose and self.renderer:
                self.renderer.render(self.engine)

        return self.engine.winner

    def _build_state_view(self, pi: int) -> dict[str, Any]:
        """Build a read-only state summary for the given player."""
        engine = self.engine
        player = engine.players[pi]
        sq = engine._sq[player.position]

        sv: dict[str, Any] = {
            "my_index": pi,
            "my_money": player.money,
            "my_position": player.position,
            "my_properties": [
                sq_idx for sq_idx, prop in engine.properties.items()
                if prop.owner == pi
            ],
            "active_players": sum(1 for p in engine.players if not p.is_bankrupt),
            "turn": engine.turn_number,
        }

        # Extra context for buy decisions
        if sq["type"] in ("property", "railroad", "utility"):
            sv["landing_price"] = sq.get("price", 0)

        # House costs for buildable properties
        house_costs: dict[int, int] = {}
        for sq_idx in engine._get_buildable(pi):
            house_costs[sq_idx] = engine._sq[sq_idx]["house_cost"]
        sv["house_costs"] = house_costs

        return sv
