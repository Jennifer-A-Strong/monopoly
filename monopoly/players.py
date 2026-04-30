"""Player implementations — decide() picks an action from a PendingDecision.

Every decision-maker (random, heuristic, human, LLM) implements the same
protocol: given a state view and a pending decision, return one legal action.
"""

from __future__ import annotations

from typing import Any, Protocol

from .types import (
    Action,
    BuildHouse,
    BuyProperty,
    EndTurn,
    PendingDecision,
    RollDice,
    PayJailFine,
    UseGOJFCard,
    AttemptJailRoll,
)


class Player(Protocol):
    """Minimal interface every player must satisfy."""

    name: str

    def decide(self, state_view: dict[str, Any], decision: PendingDecision) -> Action:
        """Choose one action from ``decision.actions``."""
        ...


# ─────────────────────────────────────────────────────────────────
# RandomPlayer — buys everything, builds randomly, otherwise random
# ─────────────────────────────────────────────────────────────────

class RandomPlayer:
    """Buys every property it can afford; builds randomly; otherwise picks at random."""

    def __init__(self, name: str, rng: Any = None) -> None:
        self.name = name
        self._rng = rng  # use engine's RNG if provided, else fall back

    def decide(self, state_view: dict[str, Any], decision: PendingDecision) -> Action:
        actions = decision.actions

        # Always buy if we can
        for a in actions:
            if isinstance(a, BuyProperty):
                return a

        # Always roll if that's the only meaningful choice
        if len(actions) == 1:
            return actions[0]

        # For jail: just attempt to roll
        for a in actions:
            if isinstance(a, AttemptJailRoll):
                return a

        # Post-roll: randomly build sometimes, but mostly end turn
        build_actions = [a for a in actions if isinstance(a, BuildHouse)]
        if build_actions and self._rng and self._rng.random() < 0.5:
            return self._rng.choice(build_actions)

        # Default: end turn or roll again
        for a in actions:
            if isinstance(a, (RollDice, EndTurn)):
                return a

        return actions[0]


# ─────────────────────────────────────────────────────────────────
# HeuristicPlayer — simple hand-written strategy
# ─────────────────────────────────────────────────────────────────

class HeuristicPlayer:
    """Hand-tuned strategy: buy aggressively, build on best groups first,
    use GOJF cards when available, and pay jail fines late in the game.
    """

    def __init__(self, name: str, rng: Any = None) -> None:
        self.name = name
        self._rng = rng

    def decide(self, state_view: dict[str, Any], decision: PendingDecision) -> Action:
        actions = decision.actions
        dt = decision.decision_type

        if dt == "roll":
            return RollDice()

        if dt == "jail":
            return self._jail_decision(state_view, actions)

        if dt == "buy_or_decline":
            return self._buy_decision(state_view, actions)

        if dt == "post_roll":
            return self._post_roll_decision(state_view, actions)

        # Fallback
        return actions[0]

    def _jail_decision(self, sv: dict, actions: list[Action]) -> Action:
        # Use GOJF card if we have one
        for a in actions:
            if isinstance(a, UseGOJFCard):
                return a
        # Early game: try to roll doubles (stay in jail = free parking)
        # Late game (few opponents): pay fine to keep moving
        n_active = sv.get("active_players", 4)
        if n_active <= 2:
            for a in actions:
                if isinstance(a, PayJailFine):
                    return a
        for a in actions:
            if isinstance(a, AttemptJailRoll):
                return a
        return actions[0]

    def _buy_decision(self, sv: dict, actions: list[Action]) -> Action:
        # Buy if we can afford it and still keep $100 reserve
        for a in actions:
            if isinstance(a, BuyProperty):
                player_money = sv.get("my_money", 0)
                price = sv.get("landing_price", 0)
                if player_money - price >= 100:
                    return a
                # Even with low reserves, buy railroads and cheap properties
                if price <= 200:
                    return a
        # Decline
        from .types import DeclineProperty
        for a in actions:
            if isinstance(a, DeclineProperty):
                return a
        return actions[0]

    def _post_roll_decision(self, sv: dict, actions: list[Action]) -> Action:
        # Build houses if possible (prefer it over rolling again)
        build_actions = [a for a in actions if isinstance(a, BuildHouse)]
        if build_actions:
            player_money = sv.get("my_money", 0)
            # Only build if we keep $200 reserve
            affordable = []
            for ba in build_actions:
                cost = sv.get("house_costs", {}).get(ba.property_index, 999)
                if player_money - cost >= 200:
                    affordable.append((ba, cost))
            if affordable:
                # Build on the most expensive property first (better ROI usually)
                affordable.sort(key=lambda x: -x[1])
                return affordable[0][0]

        # Roll again if doubles
        for a in actions:
            if isinstance(a, RollDice):
                return a

        # End turn
        return EndTurn()
