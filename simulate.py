#!/usr/bin/env python3
"""
Stage 1: Movement-only Monopoly simulator.

Rolls dice millions of times and reports how often each square is landed on.
Compare output against Truman Collins's published frequencies to validate:
    http://www.tkcs-collins.com/truman/monopoly/monopoly.shtml

Usage examples:
    python simulate.py
    python simulate.py --rolls 50000000 --seed 0 --output results.csv
    python simulate.py --strategy pay_immediately
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from monopoly.loader import load_all
from monopoly.movement_sim import run_simulation

# Reference steady-state frequencies (%) for the "pay immediately" jail strategy
# (post-2008 US rules).  These are approximate values derived from published
# Monopoly landing-frequency analyses (Collins et al.).  Compare against our
# results when running --strategy pay_immediately; they will diverge significantly
# under --strategy roll_for_doubles (jail will be ~11.5% instead of ~6%).
# Authoritative source: http://www.tkcs-collins.com/truman/monopoly/monopoly.shtml
# Entries are square_index → frequency_pct.
COLLINS_FREQUENCIES: dict[int, float] = {
    0:  3.090,   # Go
    1:  2.235,   # Mediterranean
    2:  1.929,   # Community Chest
    3:  2.283,   # Baltic
    4:  2.139,   # Income Tax
    5:  2.969,   # Reading Railroad
    6:  2.213,   # Oriental
    7:  2.094,   # Chance  (after card effects; many draws move you away)
    8:  2.326,   # Vermont
    9:  2.307,   # Connecticut
    10: 5.888,   # Jail
    11: 2.643,   # St. Charles
    12: 2.728,   # Electric Company
    13: 2.315,   # States
    14: 2.447,   # Virginia
    15: 3.120,   # Pennsylvania Railroad
    16: 2.836,   # St. James
    17: 1.907,   # Community Chest
    18: 2.980,   # Tennessee
    19: 3.183,   # New York
    20: 2.461,   # Free Parking
    21: 2.668,   # Kentucky
    22: 2.097,   # Chance
    23: 2.606,   # Indiana
    24: 3.183,   # Illinois
    25: 3.163,   # B&O Railroad
    26: 2.701,   # Atlantic
    27: 2.700,   # Ventnor
    28: 2.607,   # Water Works
    29: 2.643,   # Marvin Gardens
    30: 0.584,   # Go to Jail (almost no one stays here — they're sent to sq 10)
    31: 2.535,   # Pacific
    32: 2.573,   # North Carolina
    33: 1.914,   # Community Chest
    34: 2.453,   # Pennsylvania Ave
    35: 2.447,   # Short Line
    36: 2.070,   # Chance
    37: 2.178,   # Park Place
    38: 1.913,   # Luxury Tax
    39: 2.350,   # Boardwalk
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monopoly movement-only simulator (Stage 1)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--rolls", type=int, default=10_000_000,
        help="Number of dice rolls to simulate",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducibility",
    )
    parser.add_argument(
        "--output", type=str, default="results.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--strategy", choices=["roll_for_doubles", "pay_immediately"],
        default="roll_for_doubles",
        help="Jail exit strategy",
    )
    parser.add_argument(
        "--data-dir", type=str, default="data",
        help="Directory containing board.yaml and deck YAML files",
    )
    args = parser.parse_args()

    # Load and validate data
    print(f"Loading data from {args.data_dir!r}...")
    board, chance_cards, cc_cards = load_all(args.data_dir)
    print(f"  Board: {len(board)} squares  |  "
          f"Chance: {len(chance_cards)} cards  |  "
          f"Community Chest: {len(cc_cards)} cards")

    # Run simulation
    print(f"\nSimulating {args.rolls:,} dice rolls  "
          f"(seed={args.seed}, strategy={args.strategy!r})...")
    t0 = time.perf_counter()
    visits = run_simulation(
        board, chance_cards, cc_cards,
        n_rolls=args.rolls,
        seed=args.seed,
        jail_strategy=args.strategy,
    )
    elapsed = time.perf_counter() - t0
    total_visits = sum(visits)
    rolls_per_sec = args.rolls / elapsed
    print(f"Done in {elapsed:.2f}s  ({rolls_per_sec:,.0f} rolls/sec)")
    print(f"Total landings recorded: {total_visits:,}")

    # Write CSV
    output_path = Path(args.output)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "square_index", "name", "type",
            "visits", "frequency_pct", "collins_pct", "diff_pct",
        ])
        for sq in board:
            idx = sq["index"]
            freq = 100.0 * visits[idx] / total_visits if total_visits else 0.0
            collins = COLLINS_FREQUENCIES.get(idx)
            delta = f"{freq - collins:+.4f}" if collins is not None else ""
            collins_str = f"{collins:.3f}" if collins is not None else ""
            writer.writerow([
                idx, sq["name"], sq["type"],
                visits[idx], f"{freq:.4f}", collins_str, delta,
            ])
    print(f"Results written to {output_path}\n")

    # Console summary: top 10 + Collins comparison
    sq_map = {sq["index"]: sq for sq in board}
    ranked = sorted(range(BOARD_SIZE := 40), key=lambda i: visits[i], reverse=True)

    header = f"  {'Rk':>2}  {'Sq':>2}  {'Name':<30}  {'Ours%':>7}  {'Collins%':>8}  {'Diff':>7}"
    print("Top 10 most-landed-on squares:")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for rank, idx in enumerate(ranked[:10], 1):
        sq = sq_map[idx]
        freq = 100.0 * visits[idx] / total_visits if total_visits else 0.0
        collins = COLLINS_FREQUENCIES.get(idx)
        collins_str = f"{collins:8.3f}" if collins is not None else "       —"
        delta_str = f"{freq - collins:+7.4f}" if collins is not None else "      —"
        print(f"  {rank:>2}  {idx:>2}  {sq['name']:<30}  {freq:7.4f}  {collins_str}  {delta_str}")

    print()
    # Quick sanity checks
    jail_pct = 100.0 * visits[10] / total_visits if total_visits else 0.0
    illinois_pct = 100.0 * visits[24] / total_visits if total_visits else 0.0
    print(f"Sanity checks:")
    print(f"  Jail (sq 10):       {jail_pct:.3f}%  (Collins: 5.888%)")
    print(f"  Illinois Ave (sq 24): {illinois_pct:.3f}%  (Collins: 3.183%)")


if __name__ == "__main__":
    main()
