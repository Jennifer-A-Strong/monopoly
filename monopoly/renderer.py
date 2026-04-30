"""ASCII renderer for Monopoly game state.

Stage 2 renderer — functional table-based display.  A visual board layout
can be iterated on in Stage 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import GameEngine

# Short names for the 40 squares (max 5 chars for compact display)
SHORT_NAMES = [
    "GO",    "MedAv", "CC",    "BaltA", "ITax",
    "RdgRR", "OrntA", "CH",    "VrmtA", "ConnA",
    "JAIL",  "StChr", "ElCo",  "SttsA", "VirgA",
    "PnnRR", "StJms", "CC",    "TennA", "NYAve",
    "FPark", "KntcA", "CH",    "IndnA", "IllnA",
    "B&ORR", "AtlnA", "VntnA", "WtrWk", "MrvnG",
    "GoJai", "PacfA", "NCarA", "CC",    "PennA",
    "ShrtL", "CH",    "PrkPl", "LTax",  "Brdwk",
]

# ANSI colour codes for property groups
GROUP_COLORS = {
    "brown":      "\033[38;5;94m",
    "light_blue": "\033[38;5;117m",
    "pink":       "\033[38;5;205m",
    "orange":     "\033[38;5;208m",
    "red":        "\033[38;5;196m",
    "yellow":     "\033[38;5;226m",
    "green":      "\033[38;5;34m",
    "dark_blue":  "\033[38;5;21m",
}
RESET = "\033[0m"


def render(engine: GameEngine) -> None:
    """Print a compact game-state summary to stdout."""
    print()
    print(f"=== MONOPOLY  Turn {engine.turn_number} ===")
    print()

    # Player summary
    for p in engine.players:
        status = "BANKRUPT" if p.is_bankrupt else f"${p.money:,}"
        pos = SHORT_NAMES[p.position]
        jail = "  [IN JAIL]" if p.in_jail else ""
        print(f"  P{p.index + 1} {p.name:<12} {status:>10}  at {pos} (#{p.position}){jail}")
    print()

    # Board — compact table
    print(f"  {'#':>2}  {'Square':<26} {'Owner':>5} {'Bld':>4} {'Mtg':>3}  Occ")
    print(f"  {'--':>2}  {'------':<26} {'-----':>5} {'---':>4} {'---':>3}  ---")

    occupants: dict[int, list[str]] = {}
    for p in engine.players:
        if not p.is_bankrupt:
            occupants.setdefault(p.position, []).append(f"P{p.index + 1}")

    for sq in engine.board:
        idx = sq["index"]
        name = sq["name"][:26]
        sq_type = sq["type"]

        owner_str = "     "
        build_str = "    "
        mort_str = "   "

        if sq_type in ("property", "railroad", "utility"):
            prop = engine.properties.get(idx)
            if prop and prop.owner is not None:
                owner_str = f"  P{prop.owner + 1} "
                if prop.is_mortgaged:
                    mort_str = "  M"
                if sq_type == "property" and prop.houses > 0:
                    if prop.houses == 5:
                        build_str = "  H "
                    else:
                        build_str = " " + "." * prop.houses + " " * (3 - prop.houses)

        occ_str = " ".join(occupants.get(idx, []))
        color = GROUP_COLORS.get(sq.get("color_group", ""), "")
        reset = RESET if color else ""
        print(f"  {idx:>2}  {color}{name:<26}{reset} {owner_str} {build_str} {mort_str}  {occ_str}")

    print()

    # Bank supply
    print(f"  Bank: {engine.bank_houses} houses, {engine.bank_hotels} hotels remaining")
    print()
