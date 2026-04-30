"""Load and validate Monopoly data files (board, Chance deck, Community Chest deck)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

VALID_SQUARE_TYPES = {
    "go", "property", "railroad", "utility", "tax",
    "chance", "community_chest", "jail", "go_to_jail", "free_parking",
}

VALID_CARD_KINDS = {
    "move_absolute", "move_relative", "move_nearest",
    "go_to_jail", "get_out_of_jail",
    "collect_from_bank", "pay_to_bank",
    "collect_from_each_player", "pay_each_player",
    "pay_per_building",
}

BOARD_SIZE = 40
DECK_SIZE = 16


def load_board(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate board.yaml. Returns list of 40 square dicts, sorted by index."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    squares = data["squares"]

    assert len(squares) == BOARD_SIZE, (
        f"Board must have exactly {BOARD_SIZE} squares, got {len(squares)}"
    )

    indices = [sq["index"] for sq in squares]
    assert sorted(indices) == list(range(BOARD_SIZE)), (
        f"Board indices must be 0–{BOARD_SIZE - 1}, each exactly once. Got: {sorted(indices)}"
    )

    for sq in squares:
        assert "name" in sq, f"Square {sq.get('index', '?')} missing 'name'"
        assert "type" in sq, f"Square {sq.get('index', '?')} missing 'type'"
        assert sq["type"] in VALID_SQUARE_TYPES, (
            f"Square {sq['index']} has unknown type {sq['type']!r}. "
            f"Valid: {sorted(VALID_SQUARE_TYPES)}"
        )
        idx = sq["index"]
        stype = sq["type"]

        if stype == "property":
            assert "color_group" in sq, f"Square {idx} (property) missing 'color_group'"
            assert "price" in sq, f"Square {idx} (property) missing 'price'"
            assert "rent" in sq, f"Square {idx} (property) missing 'rent'"
            assert len(sq["rent"]) == 6, (
                f"Square {idx} rent must have 6 entries "
                f"[base, 1h, 2h, 3h, 4h, hotel], got {len(sq['rent'])}"
            )
            assert "house_cost" in sq, f"Square {idx} (property) missing 'house_cost'"
        elif stype in ("railroad", "utility"):
            assert "price" in sq, f"Square {idx} ({stype}) missing 'price'"

    # Validate colour-group membership
    color_groups: dict[str, list[int]] = {}
    for sq in squares:
        if sq["type"] == "property":
            color_groups.setdefault(sq["color_group"], []).append(sq["index"])
    for group, members in color_groups.items():
        assert 2 <= len(members) <= 3, (
            f"Color group {group!r} has {len(members)} members (expected 2 or 3)"
        )

    squares.sort(key=lambda sq: sq["index"])
    return squares


def load_deck(path: str | Path, deck_name: str = "deck") -> list[dict[str, Any]]:
    """Load and validate a card-deck YAML. Returns list of card dicts."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cards = data["cards"]

    assert len(cards) == DECK_SIZE, (
        f"{deck_name} must have exactly {DECK_SIZE} cards, got {len(cards)}"
    )

    ids = [card["id"] for card in cards]
    assert len(ids) == len(set(ids)), (
        f"{deck_name} has duplicate card IDs: {[x for x in ids if ids.count(x) > 1]}"
    )

    for card in cards:
        assert "id" in card, f"{deck_name}: card missing 'id': {card}"
        assert "text" in card, f"{deck_name}: card {card.get('id', '?')} missing 'text'"
        assert "kind" in card, f"{deck_name}: card {card.get('id', '?')} missing 'kind'"
        assert card["kind"] in VALID_CARD_KINDS, (
            f"{deck_name}: card {card['id']} has unknown kind {card['kind']!r}. "
            f"Valid: {sorted(VALID_CARD_KINDS)}"
        )

        kind = card["kind"]
        cid = card["id"]

        if kind == "move_absolute":
            assert "square" in card, f"{deck_name}: {cid} (move_absolute) missing 'square'"
            assert 0 <= card["square"] < BOARD_SIZE, (
                f"{deck_name}: {cid} references out-of-range square {card['square']}"
            )
        elif kind == "move_relative":
            assert "offset" in card, f"{deck_name}: {cid} (move_relative) missing 'offset'"
        elif kind == "move_nearest":
            assert "target_type" in card, (
                f"{deck_name}: {cid} (move_nearest) missing 'target_type'"
            )
            assert card["target_type"] in {"railroad", "utility"}, (
                f"{deck_name}: {cid} move_nearest has unknown target_type {card['target_type']!r}"
            )
        elif kind in {"collect_from_bank", "pay_to_bank",
                      "collect_from_each_player", "pay_each_player"}:
            assert "amount" in card, f"{deck_name}: {cid} ({kind}) missing 'amount'"
        elif kind == "pay_per_building":
            assert "house_cost" in card, (
                f"{deck_name}: {cid} (pay_per_building) missing 'house_cost'"
            )
            assert "hotel_cost" in card, (
                f"{deck_name}: {cid} (pay_per_building) missing 'hotel_cost'"
            )

    return cards


def load_all(data_dir: str | Path) -> tuple[list, list, list]:
    """
    Load board and both decks from data_dir.
    Returns (board_squares, chance_cards, community_chest_cards).
    """
    data_dir = Path(data_dir)
    board = load_board(data_dir / "board.yaml")
    chance = load_deck(data_dir / "chance.yaml", "Chance deck")
    cc = load_deck(data_dir / "community_chest.yaml", "Community Chest deck")
    return board, chance, cc
