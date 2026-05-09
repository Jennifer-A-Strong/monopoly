"""Monopoly game engine — a state machine driven by ``apply(action)``.

The engine never drives the game forward on its own.  External code
(GameRunner, MCP server, tests) reads pending decisions and calls
``apply()`` to advance the state.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Any

from .types import (
    Action,
    AttemptJailRoll,
    BuildHouse,
    BuildingChanged,
    BuyProperty,
    CardDrawn,
    DeclineProperty,
    DiceRolled,
    EndTurn,
    Event,
    GOJFReceived,
    GOJFUsed,
    GameOver,
    GameStarted,
    JailRollFailed,
    LeftJail,
    MortgageProperty,
    MoneyChanged,
    PassedGo,
    PayJailFine,
    PendingDecision,
    PlayerBankrupt,
    PlayerMoved,
    PropertyBought,
    PropertyDeclined,
    PropertyMortgaged,
    PropertyUnmortgaged,
    RentPaid,
    RollDice,
    SellHouse,
    SentToJail,
    TaxPaid,
    TurnStarted,
    UnmortgageProperty,
    UseGOJFCard,
)
from .ruleset import RuleSet
from .state import PlayerState, PropertyState

BOARD_SIZE = 40
JAIL_SQUARE = 10
GO_TO_JAIL_SQUARE = 30

RAILROAD_SQUARES = frozenset({5, 15, 25, 35})
UTILITY_SQUARES = frozenset({12, 28})


class GameEngine:
    """Full Monopoly game engine.

    Lifecycle::

        engine = GameEngine(["Alice", "Bob"], RuleSet(), board, chance, cc)
        while not engine.is_game_over:
            decision = engine.get_pending()
            action = some_player.decide(decision)
            events = engine.apply(action)
    """

    # ──────────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        player_names: list[str],
        ruleset: RuleSet,
        board: list[dict[str, Any]],
        chance_cards: list[dict[str, Any]],
        cc_cards: list[dict[str, Any]],
        seed: int = 42,
    ) -> None:
        self.ruleset = ruleset
        self.board = board
        self.rng = random.Random(seed)

        n = len(player_names)
        assert 2 <= n <= 8, f"Need 2–8 players, got {n}"

        # Players
        self.players = [
            PlayerState(index=i, name=name, money=ruleset.starting_money)
            for i, name in enumerate(player_names)
        ]

        # Properties
        self.properties: dict[int, PropertyState] = {}
        for sq in board:
            if sq["type"] in ("property", "railroad", "utility"):
                self.properties[sq["index"]] = PropertyState(square_index=sq["index"])

        # Precompute colour groups and square lookup
        self._color_groups: dict[str, list[int]] = {}
        for sq in board:
            if sq["type"] == "property":
                self._color_groups.setdefault(sq["color_group"], []).append(sq["index"])
        self._sq: dict[int, dict[str, Any]] = {sq["index"]: sq for sq in board}

        # Decks
        self._chance_deck = list(chance_cards)
        self._cc_deck = list(cc_cards)
        self.rng.shuffle(self._chance_deck)
        self.rng.shuffle(self._cc_deck)
        self._chance_idx = 0
        self._cc_idx = 0
        self._held_gojf: set[str] = set()   # card-ids currently held by players

        # Bank building supply
        self.bank_houses = ruleset.max_houses
        self.bank_hotels = ruleset.max_hotels

        # Turn tracking
        self.current_player_index = 0
        self.turn_number = 1
        self._last_dice_total = 0            # needed for utility rent
        self._can_roll_again = False          # doubles flag across decisions

        # Decision queue & event log
        self._pending: deque[PendingDecision] = deque()
        self.events: list[Event] = []

        # Terminal state
        self.game_over = False
        self.winner: int | None = None

        # Kick off the game
        self._log(GameStarted(
            n_players=n, seed=seed,
            player_names=tuple(player_names),
        ))
        self._start_turn(self.current_player_index)

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def get_pending(self) -> PendingDecision | None:
        """Return the current pending decision, or ``None`` if the game is over."""
        return self._pending[0] if self._pending else None

    @property
    def is_game_over(self) -> bool:
        return self.game_over

    def apply(self, action: Action) -> list[Event]:
        """Apply *action* in response to the current pending decision.

        Raises ``ValueError`` if the action is not among the legal choices.
        Returns the list of newly generated events.
        """
        if not self._pending:
            raise RuntimeError("No pending decision — game may be over")

        decision = self._pending[0]
        if action not in decision.actions:
            raise ValueError(
                f"Illegal action {action!r} for {decision.decision_type!r} decision.  "
                f"Legal: {decision.actions}"
            )

        self._pending.popleft()
        old_len = len(self.events)

        match action:
            case RollDice():
                self._handle_roll_dice(decision.player_index)
            case BuyProperty():
                self._handle_buy_property(decision.player_index)
            case DeclineProperty():
                self._handle_decline_property(decision.player_index)
            case PayJailFine():
                self._handle_pay_jail_fine(decision.player_index)
            case UseGOJFCard():
                self._handle_use_gojf(decision.player_index)
            case AttemptJailRoll():
                self._handle_attempt_jail_roll(decision.player_index)
            case BuildHouse(property_index=sq):
                self._handle_build_house(decision.player_index, sq)
            case SellHouse(property_index=sq):
                self._handle_sell_house(decision.player_index, sq)
            case MortgageProperty(property_index=sq):
                self._handle_mortgage(decision.player_index, sq)
            case UnmortgageProperty(property_index=sq):
                self._handle_unmortgage(decision.player_index, sq)
            case EndTurn():
                self._handle_end_turn(decision.player_index)
            case _:
                raise ValueError(f"Unknown action type: {type(action).__name__}")

        return self.events[old_len:]

    # ──────────────────────────────────────────────────────────────
    # Decision pushers
    # ──────────────────────────────────────────────────────────────

    def _start_turn(self, pi: int) -> None:
        player = self.players[pi]
        self._log(TurnStarted(player=pi, turn=self.turn_number))
        if player.in_jail:
            self._push_jail_decision(pi)
        else:
            self._push_roll_decision(pi)

    def _push_roll_decision(self, pi: int) -> None:
        self._pending.append(PendingDecision(
            player_index=pi,
            decision_type="roll",
            prompt="Roll the dice.",
            actions=[RollDice()],
        ))

    def _push_jail_decision(self, pi: int) -> None:
        actions: list[Action] = [AttemptJailRoll()]
        player = self.players[pi]
        if player.money >= self.ruleset.jail_fine:
            actions.append(PayJailFine())
        if player.gojf_cards:
            actions.append(UseGOJFCard())
        self._pending.append(PendingDecision(
            player_index=pi,
            decision_type="jail",
            prompt="You are in jail.  Choose how to attempt to leave.",
            actions=actions,
        ))

    def _push_buy_decision(self, pi: int, sq_idx: int) -> None:
        sq = self._sq[sq_idx]
        price = sq["price"]
        actions: list[Action] = [DeclineProperty()]
        if self.players[pi].money >= price:
            actions.insert(0, BuyProperty())
        self._pending.append(PendingDecision(
            player_index=pi,
            decision_type="buy_or_decline",
            prompt=f"Buy {sq['name']} for ${price}?",
            actions=actions,
        ))

    def _push_post_roll(self, pi: int) -> None:
        """Push a manage-assets / continue / end-turn decision."""
        actions: list[Action] = []
        for sq_idx in self._get_buildable(pi):
            actions.append(BuildHouse(property_index=sq_idx))
        for sq_idx in self._get_sellable(pi):
            actions.append(SellHouse(property_index=sq_idx))
        for sq_idx in self._get_mortgageable(pi):
            actions.append(MortgageProperty(property_index=sq_idx))
        for sq_idx in self._get_unmortgageable(pi):
            actions.append(UnmortgageProperty(property_index=sq_idx))
        if self._can_roll_again:
            actions.append(RollDice())
        actions.append(EndTurn())
        self._pending.append(PendingDecision(
            player_index=pi,
            decision_type="post_roll",
            prompt="Manage properties, roll again, or end turn."
                   if self._can_roll_again else
                   "Manage properties or end turn.",
            actions=actions,
        ))

    # ──────────────────────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────────────────────

    def _handle_roll_dice(self, pi: int) -> None:
        player = self.players[pi]
        d1, d2 = self.rng.randint(1, 6), self.rng.randint(1, 6)
        self._log(DiceRolled(player=pi, d1=d1, d2=d2))
        is_doubles = d1 == d2
        total = d1 + d2
        self._last_dice_total = total

        if is_doubles:
            player.consecutive_doubles += 1
        else:
            player.consecutive_doubles = 0

        # Three consecutive doubles → jail
        if player.consecutive_doubles >= self.ruleset.doubles_to_jail:
            self._send_to_jail(pi, "three_doubles")
            self._can_roll_again = False
            self._push_post_roll(pi)
            return

        # Move
        old_pos = player.position
        new_pos = (old_pos + total) % BOARD_SIZE
        player.position = new_pos
        self._log(PlayerMoved(player=pi, from_sq=old_pos, to_sq=new_pos))

        # Passed Go?
        if new_pos < old_pos:
            self._collect_go(pi)

        # Resolve landing (may push a buy decision)
        needs_buy_decision = self._resolve_landing(pi, total)

        if player.is_bankrupt:
            self._check_game_over()
            return

        self._can_roll_again = is_doubles and not player.in_jail
        if not needs_buy_decision:
            self._push_post_roll(pi)

    def _handle_buy_property(self, pi: int) -> None:
        player = self.players[pi]
        sq_idx = player.position
        sq = self._sq[sq_idx]
        price = sq["price"]
        player.money -= price
        self.properties[sq_idx].owner = pi
        self._log(PropertyBought(player=pi, square=sq_idx, price=price))
        self._log(MoneyChanged(player=pi, amount=-price, reason=f"buy_{sq_idx}"))
        self._push_post_roll(pi)

    def _handle_decline_property(self, pi: int) -> None:
        sq_idx = self.players[pi].position
        self._log(PropertyDeclined(player=pi, square=sq_idx))
        # Auction stub (Stage 5): property stays unowned.
        self._push_post_roll(pi)

    def _handle_pay_jail_fine(self, pi: int) -> None:
        player = self.players[pi]
        fine = self.ruleset.jail_fine
        player.money -= fine
        self._log(MoneyChanged(player=pi, amount=-fine, reason="jail_fine"))
        player.in_jail = False
        player.jail_turns = 0
        self._log(LeftJail(player=pi, method="paid_fine"))
        # Normal roll (doubles grant extra rolls)
        self._push_roll_decision(pi)

    def _handle_use_gojf(self, pi: int) -> None:
        player = self.players[pi]
        card_id = player.gojf_cards.pop(0)
        self._held_gojf.discard(card_id)
        # Determine which deck the card came from
        deck = "chance" if card_id.startswith("chance") else "community_chest"
        self._log(GOJFUsed(player=pi, deck=deck))
        player.in_jail = False
        player.jail_turns = 0
        self._log(LeftJail(player=pi, method="gojf_card"))
        self._push_roll_decision(pi)

    def _handle_attempt_jail_roll(self, pi: int) -> None:
        player = self.players[pi]
        d1, d2 = self.rng.randint(1, 6), self.rng.randint(1, 6)
        self._log(DiceRolled(player=pi, d1=d1, d2=d2))
        total = d1 + d2
        self._last_dice_total = total
        player.jail_turns += 1

        if d1 == d2:
            # Doubles — leave jail, move, NO extra roll
            player.in_jail = False
            player.jail_turns = 0
            player.consecutive_doubles = 0
            self._log(LeftJail(player=pi, method="doubles"))
            old_pos = player.position
            new_pos = (JAIL_SQUARE + total) % BOARD_SIZE
            player.position = new_pos
            self._log(PlayerMoved(player=pi, from_sq=old_pos, to_sq=new_pos))
            needs_buy = self._resolve_landing(pi, total)
            self._can_roll_again = False
            if not player.is_bankrupt and not needs_buy:
                self._push_post_roll(pi)
            if player.is_bankrupt:
                self._check_game_over()

        elif player.jail_turns >= self.ruleset.max_jail_turns:
            # Third failed attempt — must pay fine and move
            self._log(JailRollFailed(player=pi, attempt=player.jail_turns))
            fine = self.ruleset.jail_fine
            self._charge(pi, fine, "jail_fine_forced")
            if player.is_bankrupt:
                self._check_game_over()
                return
            player.in_jail = False
            player.jail_turns = 0
            player.consecutive_doubles = 0
            self._log(LeftJail(player=pi, method="paid_fine"))
            old_pos = player.position
            new_pos = (JAIL_SQUARE + total) % BOARD_SIZE
            player.position = new_pos
            self._log(PlayerMoved(player=pi, from_sq=old_pos, to_sq=new_pos))
            needs_buy = self._resolve_landing(pi, total)
            self._can_roll_again = False
            if not player.is_bankrupt and not needs_buy:
                self._push_post_roll(pi)
            if player.is_bankrupt:
                self._check_game_over()
        else:
            # Stay in jail
            self._log(JailRollFailed(player=pi, attempt=player.jail_turns))
            self._can_roll_again = False
            self._push_post_roll(pi)

    def _handle_build_house(self, pi: int, sq_idx: int) -> None:
        prop = self.properties[sq_idx]
        sq = self._sq[sq_idx]
        cost = sq["house_cost"]
        player = self.players[pi]
        old = prop.houses

        if old == 4:
            # Upgrade to hotel
            prop.houses = 5
            self.bank_houses += 4
            self.bank_hotels -= 1
        else:
            prop.houses = old + 1
            self.bank_houses -= 1

        player.money -= cost
        self._log(BuildingChanged(player=pi, square=sq_idx, old_houses=old, new_houses=prop.houses))
        self._log(MoneyChanged(player=pi, amount=-cost, reason=f"build_{sq_idx}"))
        self._push_post_roll(pi)

    def _handle_sell_house(self, pi: int, sq_idx: int) -> None:
        prop = self.properties[sq_idx]
        sq = self._sq[sq_idx]
        refund = sq["house_cost"] // 2
        player = self.players[pi]
        old = prop.houses

        if old == 5:
            # Downgrade from hotel
            if self.bank_houses >= 4:
                prop.houses = 4
                self.bank_hotels += 1
                self.bank_houses -= 4
            else:
                # Not enough houses to downgrade — sell hotel entirely
                prop.houses = 0
                self.bank_hotels += 1
                refund = sq["house_cost"] * 5 // 2
        else:
            prop.houses = old - 1
            self.bank_houses += 1

        player.money += refund
        self._log(BuildingChanged(player=pi, square=sq_idx, old_houses=old, new_houses=prop.houses))
        self._log(MoneyChanged(player=pi, amount=refund, reason=f"sell_house_{sq_idx}"))
        self._push_post_roll(pi)

    def _handle_mortgage(self, pi: int, sq_idx: int) -> None:
        prop = self.properties[sq_idx]
        sq = self._sq[sq_idx]
        value = int(sq["price"] * self.ruleset.mortgage_rate)
        prop.is_mortgaged = True
        self.players[pi].money += value
        self._log(PropertyMortgaged(player=pi, square=sq_idx, amount=value))
        self._log(MoneyChanged(player=pi, amount=value, reason=f"mortgage_{sq_idx}"))
        self._push_post_roll(pi)

    def _handle_unmortgage(self, pi: int, sq_idx: int) -> None:
        prop = self.properties[sq_idx]
        sq = self._sq[sq_idx]
        base = int(sq["price"] * self.ruleset.mortgage_rate)
        cost = int(base * (1 + self.ruleset.unmortgage_interest))
        prop.is_mortgaged = False
        self.players[pi].money -= cost
        self._log(PropertyUnmortgaged(player=pi, square=sq_idx, cost=cost))
        self._log(MoneyChanged(player=pi, amount=-cost, reason=f"unmortgage_{sq_idx}"))
        self._push_post_roll(pi)

    def _handle_end_turn(self, pi: int) -> None:
        player = self.players[pi]
        player.consecutive_doubles = 0
        self._can_roll_again = False
        self._advance_turn()

    # ──────────────────────────────────────────────────────────────
    # Game mechanics
    # ──────────────────────────────────────────────────────────────

    def _resolve_landing(self, pi: int, dice_total: int, via_card: str | None = None) -> bool:
        """Process landing effects, possibly chaining through cards.

        Returns True if a buy/decline decision was pushed (caller should not
        push a post-roll decision yet).
        """
        while True:
            sq = self._sq[self.players[pi].position]
            sq_type = sq["type"]

            if sq_type == "go_to_jail":
                self._send_to_jail(pi, "go_to_jail_square")
                return False

            if sq_type in ("chance", "community_chest"):
                card, deck = self._draw_card(sq_type)
                self._log(CardDrawn(
                    player=pi, deck=deck,
                    card_id=card["id"], card_text=card["text"],
                ))
                moved = self._apply_card(pi, card, deck, dice_total)
                if self.players[pi].is_bankrupt or self.players[pi].in_jail:
                    return False
                if not moved:
                    return False
                # Card moved us — check what card it was for rent modifiers
                kind = card["kind"]
                if kind == "move_nearest":
                    via_card = "nearest_" + card["target_type"]
                else:
                    via_card = None
                continue  # loop to handle new square

            if sq_type in ("property", "railroad", "utility"):
                sq_idx = sq["index"]
                prop = self.properties[sq_idx]
                if prop.owner is None:
                    self._push_buy_decision(pi, sq_idx)
                    return True
                if prop.owner != pi and not prop.is_mortgaged:
                    rent = self._calculate_rent(sq_idx, dice_total, via_card, lander=pi)
                    self._log(RentPaid(payer=pi, owner=prop.owner, amount=rent, square=sq_idx))
                    self._charge(pi, rent, f"rent_{sq_idx}", creditor=prop.owner)
                return False

            if sq_type == "tax":
                amount = (self.ruleset.income_tax
                          if sq.get("tax_type") == "income_tax"
                          else self.ruleset.luxury_tax)
                self._log(TaxPaid(player=pi, amount=amount, square=sq["index"]))
                self._charge(pi, amount, f"tax_{sq['index']}")
                return False

            # go, free_parking, jail (visiting) — nothing to do
            return False

    def _apply_card(self, pi: int, card: dict, deck: str, dice_total: int) -> bool:
        """Apply a card's effect.  Returns True if the player was *moved*."""
        kind = card["kind"]
        player = self.players[pi]

        if kind == "move_absolute":
            target = card["square"]
            self._move_to(pi, target, forward=True)
            return True

        if kind == "move_relative":
            old = player.position
            new = (old + card["offset"]) % BOARD_SIZE
            player.position = new
            self._log(PlayerMoved(player=pi, from_sq=old, to_sq=new))
            # Backward movement never collects Go salary.
            return True

        if kind == "move_nearest":
            targets = RAILROAD_SQUARES if card["target_type"] == "railroad" else UTILITY_SQUARES
            dest = self._nearest_forward(player.position, targets)
            self._move_to(pi, dest, forward=True)
            return True

        if kind == "go_to_jail":
            self._send_to_jail(pi, f"{deck}_card")
            return False  # movement handled internally; don't re-resolve

        if kind == "get_out_of_jail":
            player.gojf_cards.append(card["id"])
            self._held_gojf.add(card["id"])
            self._log(GOJFReceived(player=pi, deck=deck))
            return False

        if kind == "collect_from_bank":
            player.money += card["amount"]
            self._log(MoneyChanged(player=pi, amount=card["amount"], reason=card["id"]))
            return False

        if kind == "pay_to_bank":
            self._charge(pi, card["amount"], card["id"])
            return False

        if kind == "collect_from_each_player":
            amt = card["amount"]
            for other in self.players:
                if other.index != pi and not other.is_bankrupt:
                    self._charge(other.index, amt, card["id"], creditor=pi)
            return False

        if kind == "pay_each_player":
            amt = card["amount"]
            for other in self.players:
                if other.index != pi and not other.is_bankrupt:
                    self._charge(pi, amt, card["id"], creditor=other.index)
                    if player.is_bankrupt:
                        break
            return False

        if kind == "pay_per_building":
            total = 0
            for sq_idx, prop in self.properties.items():
                if prop.owner == pi:
                    if prop.houses == 5:
                        total += card["hotel_cost"]
                    else:
                        total += prop.houses * card["house_cost"]
            if total > 0:
                self._charge(pi, total, card["id"])
            return False

        return False  # unknown kind — no-op

    def _move_to(self, pi: int, target: int, forward: bool = True) -> None:
        """Move player to *target*.  Collects Go salary if passing Go forward."""
        player = self.players[pi]
        old = player.position
        player.position = target
        self._log(PlayerMoved(player=pi, from_sq=old, to_sq=target))
        if forward and target <= old and target != old:
            self._collect_go(pi)

    def _collect_go(self, pi: int) -> None:
        salary = self.ruleset.go_salary
        self.players[pi].money += salary
        self._log(PassedGo(player=pi, amount=salary))

    def _send_to_jail(self, pi: int, reason: str) -> None:
        player = self.players[pi]
        player.position = JAIL_SQUARE
        player.in_jail = True
        player.jail_turns = 0
        player.consecutive_doubles = 0
        self._log(SentToJail(player=pi, reason=reason))

    def _charge(self, pi: int, amount: int, reason: str, creditor: int | None = None) -> None:
        """Charge a player *amount*.  Auto-liquidates if needed; may bankrupt."""
        player = self.players[pi]
        if player.money < amount:
            self._auto_liquidate(pi, amount)
        if player.money >= amount:
            player.money -= amount
            self._log(MoneyChanged(player=pi, amount=-amount, reason=reason))
            if creditor is not None and not self.players[creditor].is_bankrupt:
                self.players[creditor].money += amount
                self._log(MoneyChanged(player=creditor, amount=amount, reason=reason))
        else:
            # Bankrupt — pay whatever is left
            paid = player.money
            player.money = 0
            self._log(MoneyChanged(player=pi, amount=-paid, reason=reason))
            if creditor is not None and not self.players[creditor].is_bankrupt:
                self.players[creditor].money += paid
                self._log(MoneyChanged(player=creditor, amount=paid, reason=reason))
            self._bankrupt(pi, creditor)

    def _auto_liquidate(self, pi: int, target: int) -> None:
        """Sell houses and mortgage properties until player has >= *target* cash."""
        player = self.players[pi]

        # Phase 1: sell houses (from highest-count properties first)
        while player.money < target:
            best_sq = self._pick_house_to_sell(pi)
            if best_sq is None:
                break
            prop = self.properties[best_sq]
            sq = self._sq[best_sq]
            old = prop.houses
            refund = sq["house_cost"] // 2
            if old == 5:
                if self.bank_houses >= 4:
                    prop.houses = 4
                    self.bank_hotels += 1
                    self.bank_houses -= 4
                else:
                    prop.houses = 0
                    self.bank_hotels += 1
                    refund = sq["house_cost"] * 5 // 2
            else:
                prop.houses -= 1
                self.bank_houses += 1
            player.money += refund
            self._log(BuildingChanged(player=pi, square=best_sq,
                                      old_houses=old, new_houses=prop.houses))
            self._log(MoneyChanged(player=pi, amount=refund, reason=f"liquidate_house_{best_sq}"))

        # Phase 2: mortgage un-housed properties
        while player.money < target:
            mortgaged_any = False
            for sq_idx, prop in self.properties.items():
                if prop.owner == pi and not prop.is_mortgaged and prop.houses == 0:
                    sq = self._sq[sq_idx]
                    value = int(sq["price"] * self.ruleset.mortgage_rate)
                    prop.is_mortgaged = True
                    player.money += value
                    self._log(PropertyMortgaged(player=pi, square=sq_idx, amount=value))
                    self._log(MoneyChanged(player=pi, amount=value,
                                           reason=f"liquidate_mortgage_{sq_idx}"))
                    mortgaged_any = True
                    if player.money >= target:
                        break
            if not mortgaged_any:
                break

    def _pick_house_to_sell(self, pi: int) -> int | None:
        """Pick a property to sell one house from, respecting even-build rules."""
        best: int | None = None
        best_houses = -1
        for sq_idx, prop in self.properties.items():
            if prop.owner != pi or prop.houses == 0:
                continue
            sq = self._sq[sq_idx]
            if sq["type"] != "property":
                continue
            group = sq["color_group"]
            group_houses = [self.properties[g].houses for g in self._color_groups[group]]
            # Can only sell from this property if it has the max in its group
            if prop.houses == max(group_houses) and prop.houses > best_houses:
                best = sq_idx
                best_houses = prop.houses
        return best

    def _bankrupt(self, pi: int, creditor: int | None) -> None:
        player = self.players[pi]
        player.is_bankrupt = True
        self._log(PlayerBankrupt(player=pi, creditor=creditor))

        if creditor is not None:
            # Transfer properties to creditor
            for prop in self.properties.values():
                if prop.owner == pi:
                    prop.owner = creditor
                    # Mortgaged properties transfer as-is
            # Transfer GOJF cards
            for card_id in player.gojf_cards:
                self.players[creditor].gojf_cards.append(card_id)
        else:
            # Return properties to bank
            for prop in self.properties.values():
                if prop.owner == pi:
                    prop.owner = None
                    prop.is_mortgaged = False
                    prop.houses = 0
            # Return GOJF cards to their decks
            for card_id in player.gojf_cards:
                self._held_gojf.discard(card_id)

        player.gojf_cards.clear()
        player.money = 0

    def _calculate_rent(self, sq_idx: int, dice_total: int,
                        via_card: str | None = None, lander: int | None = None) -> int:
        sq = self._sq[sq_idx]
        prop = self.properties[sq_idx]
        owner = prop.owner
        assert owner is not None

        sq_type = sq["type"]

        if sq_type == "property":
            if prop.houses > 0:
                return sq["rent"][prop.houses]  # index 1–5
            # No houses: base rent, doubled if player owns the full group
            base = sq["rent"][0]
            if self._owns_full_group(owner, sq["color_group"]):
                return base * 2
            return base

        if sq_type == "railroad":
            n_owned = sum(
                1 for rr in RAILROAD_SQUARES
                if self.properties[rr].owner == owner
                and not self.properties[rr].is_mortgaged
            )
            base_rent = 25 * (2 ** (n_owned - 1))  # 25, 50, 100, 200
            if via_card == "nearest_railroad":
                return base_rent * 2
            return base_rent

        if sq_type == "utility":
            n_owned = sum(
                1 for u in UTILITY_SQUARES
                if self.properties[u].owner == owner
                and not self.properties[u].is_mortgaged
            )
            if via_card == "nearest_utility":
                # Card says: throw dice and pay 10× — use a NEW roll
                d1, d2 = self.rng.randint(1, 6), self.rng.randint(1, 6)
                if lander is not None:
                    self._log(DiceRolled(player=lander, d1=d1, d2=d2))
                return 10 * (d1 + d2)
            multiplier = 10 if n_owned >= 2 else 4
            return multiplier * dice_total

        return 0

    def _draw_card(self, deck_type: str) -> tuple[dict, str]:
        """Draw the next card, skipping any held-out GOJF cards."""
        deck = self._chance_deck if deck_type == "chance" else self._cc_deck
        idx_attr = "_chance_idx" if deck_type == "chance" else "_cc_idx"
        idx = getattr(self, idx_attr)

        for _ in range(len(deck)):
            card = deck[idx]
            idx += 1
            if idx >= len(deck):
                idx = 0
                self.rng.shuffle(deck)
            if card["kind"] == "get_out_of_jail" and card["id"] in self._held_gojf:
                continue  # skip — this GOJF card is held by a player
            setattr(self, idx_attr, idx)
            return card, deck_type

        # Should never happen (at most 1 GOJF card per deck)
        setattr(self, idx_attr, idx)
        return deck[0], deck_type

    def _advance_turn(self) -> None:
        active = [p for p in self.players if not p.is_bankrupt]
        if len(active) <= 1:
            self._check_game_over()
            return
        # Move to next non-bankrupt player
        nxt = (self.current_player_index + 1) % len(self.players)
        while self.players[nxt].is_bankrupt:
            nxt = (nxt + 1) % len(self.players)
        self.current_player_index = nxt
        self.turn_number += 1
        if self.turn_number > self.ruleset.max_turns:
            self._end_game_by_wealth()
            return
        self._start_turn(nxt)

    def _check_game_over(self) -> None:
        active = [p for p in self.players if not p.is_bankrupt]
        if len(active) <= 1:
            self.game_over = True
            self.winner = active[0].index if active else None
            self._log(GameOver(winner=self.winner or 0, turn=self.turn_number))
            self._pending.clear()
        elif self.turn_number > self.ruleset.max_turns:
            self._end_game_by_wealth()

    def _end_game_by_wealth(self) -> None:
        active = [p for p in self.players if not p.is_bankrupt]
        richest = max(active, key=lambda p: p.money)
        self.game_over = True
        self.winner = richest.index
        self._log(GameOver(winner=richest.index, turn=self.turn_number))
        self._pending.clear()

    # ──────────────────────────────────────────────────────────────
    # Building-action helpers
    # ──────────────────────────────────────────────────────────────

    def _owns_full_group(self, pi: int, color_group: str) -> bool:
        return all(
            self.properties[sq].owner == pi
            and not self.properties[sq].is_mortgaged
            for sq in self._color_groups[color_group]
        )

    def _get_buildable(self, pi: int) -> list[int]:
        """Properties where the player can legally build one house right now."""
        player = self.players[pi]
        result = []
        for group, members in self._color_groups.items():
            if not self._owns_full_group(pi, group):
                continue
            # Any mortgaged property in the group blocks building
            if any(self.properties[m].is_mortgaged for m in members):
                continue
            house_counts = {m: self.properties[m].houses for m in members}
            min_houses = min(house_counts.values())
            for m in members:
                h = house_counts[m]
                if h > min_houses:
                    continue  # even-build: can't be more than 1 ahead
                if h >= 5:
                    continue  # already a hotel
                sq = self._sq[m]
                cost = sq["house_cost"]
                if player.money < cost:
                    continue
                # Check bank supply
                if h == 4:
                    if self.bank_hotels <= 0:
                        continue
                else:
                    if self.bank_houses <= 0:
                        continue
                result.append(m)
        return sorted(result)

    def _get_sellable(self, pi: int) -> list[int]:
        """Properties from which the player can sell one house right now."""
        result = []
        for group, members in self._color_groups.items():
            house_counts = {m: self.properties[m].houses for m in members
                            if self.properties[m].owner == pi}
            if not house_counts:
                continue
            max_houses = max(house_counts.values())
            if max_houses == 0:
                continue
            for m, h in house_counts.items():
                if h == max_houses:
                    result.append(m)
        return sorted(result)

    def _get_mortgageable(self, pi: int) -> list[int]:
        result = []
        for sq_idx, prop in self.properties.items():
            if prop.owner == pi and not prop.is_mortgaged and prop.houses == 0:
                # Can't mortgage if any property in same group has houses
                sq = self._sq[sq_idx]
                if sq["type"] == "property":
                    group = sq["color_group"]
                    if any(self.properties[m].houses > 0 for m in self._color_groups[group]):
                        continue
                result.append(sq_idx)
        return sorted(result)

    def _get_unmortgageable(self, pi: int) -> list[int]:
        result = []
        for sq_idx, prop in self.properties.items():
            if prop.owner == pi and prop.is_mortgaged:
                sq = self._sq[sq_idx]
                base = int(sq["price"] * self.ruleset.mortgage_rate)
                cost = int(base * (1 + self.ruleset.unmortgage_interest))
                if self.players[pi].money >= cost:
                    result.append(sq_idx)
        return sorted(result)

    # ──────────────────────────────────────────────────────────────
    # Utility helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _nearest_forward(current: int, targets: frozenset[int]) -> int:
        for offset in range(1, BOARD_SIZE + 1):
            candidate = (current + offset) % BOARD_SIZE
            if candidate in targets:
                return candidate
        raise ValueError("unreachable")

    def _log(self, event: Event) -> None:
        self.events.append(event)
