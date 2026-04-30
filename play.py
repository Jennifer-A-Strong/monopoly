#!/usr/bin/env python3
"""
Stage 2: Run a full Monopoly game with computer-controlled players.

Usage examples:
    python play.py
    python play.py --players 4 --seed 0 --verbose
    python play.py --heuristic 2 --random 2
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from monopoly.loader import load_all
from monopoly.ruleset import RuleSet, us_2008
from monopoly.engine import GameEngine
from monopoly.players import RandomPlayer, HeuristicPlayer
from monopoly.runner import GameRunner
from monopoly import renderer


PLAYER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a full Monopoly game (Stage 2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--heuristic", type=int, default=2,
                        help="Number of heuristic players")
    parser.add_argument("--random", type=int, default=2,
                        help="Number of random players")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every event")
    parser.add_argument("--show-board", action="store_true",
                        help="Render board after each decision")
    parser.add_argument("--max-turns", type=int, default=1000,
                        help="Maximum turns before ending by wealth")
    parser.add_argument("--data-dir", type=str, default="data",
                        help="Data directory")
    parser.add_argument("--batch", type=int, default=0,
                        help="Run N games silently and report stats (0 = single game)")
    args = parser.parse_args()

    n_total = args.heuristic + args.random
    if n_total < 2:
        parser.error("Need at least 2 players total (--heuristic + --random)")
    if n_total > 8:
        parser.error("Maximum 8 players")

    board, chance, cc = load_all(args.data_dir)
    ruleset = us_2008()
    if args.max_turns != 1000:
        ruleset = RuleSet(**{**ruleset.__dict__, "max_turns": args.max_turns})

    if args.batch > 0:
        _run_batch(args, board, chance, cc, ruleset, n_total)
    else:
        _run_single(args, board, chance, cc, ruleset, n_total)


def _run_single(args, board, chance, cc, ruleset, n_total):
    names = PLAYER_NAMES[:n_total]

    import random
    player_rng = random.Random(args.seed + 1000)

    engine = GameEngine(names, ruleset, board, chance, cc, seed=args.seed)
    players = []
    for i in range(args.heuristic):
        players.append(HeuristicPlayer(names[i], rng=player_rng))
    for i in range(args.heuristic, n_total):
        players.append(RandomPlayer(names[i], rng=player_rng))

    rend = renderer if args.show_board else None
    runner = GameRunner(engine, players, verbose=args.verbose, renderer=rend)

    print(f"Starting game: {', '.join(names)} (seed={args.seed})")
    print(f"  {args.heuristic} heuristic + {args.random} random players")
    print()

    t0 = time.perf_counter()
    winner = runner.run()
    elapsed = time.perf_counter() - t0

    print(f"Game over after {engine.turn_number} turns ({elapsed:.2f}s)")
    if winner is not None:
        w = engine.players[winner]
        print(f"Winner: P{winner + 1} {w.name} (${w.money:,})")
    else:
        print("No winner (draw)")

    # Final standings
    print("\nFinal standings:")
    standings = sorted(engine.players, key=lambda p: (not p.is_bankrupt, p.money), reverse=True)
    for rank, p in enumerate(standings, 1):
        status = "BANKRUPT" if p.is_bankrupt else f"${p.money:,}"
        n_props = sum(1 for prop in engine.properties.values() if prop.owner == p.index)
        print(f"  {rank}. P{p.index + 1} {p.name:<12} {status:>10}  ({n_props} properties)")

    # Event count summary
    from collections import Counter
    event_counts = Counter(type(e).__name__ for e in engine.events)
    print(f"\nEvent log: {len(engine.events)} total events")
    for etype, count in event_counts.most_common(10):
        print(f"  {etype:<24} {count:>6}")


def _run_batch(args, board, chance, cc, ruleset, n_total):
    """Run N games silently and report aggregate statistics."""
    import random
    from collections import Counter

    wins = Counter()
    turn_counts = []
    names = PLAYER_NAMES[:n_total]

    t0 = time.perf_counter()
    for game_num in range(args.batch):
        seed = args.seed + game_num
        player_rng = random.Random(seed + 1000)

        engine = GameEngine(names, ruleset, board, chance, cc, seed=seed)
        players = []
        for i in range(args.heuristic):
            players.append(HeuristicPlayer(names[i], rng=player_rng))
        for i in range(args.heuristic, n_total):
            players.append(RandomPlayer(names[i], rng=player_rng))

        runner = GameRunner(engine, players)
        winner = runner.run()
        if winner is not None:
            wins[engine.players[winner].name] += 1
        turn_counts.append(engine.turn_number)

    elapsed = time.perf_counter() - t0
    games_per_sec = args.batch / elapsed if elapsed > 0 else 0

    print(f"Batch: {args.batch} games in {elapsed:.2f}s ({games_per_sec:,.0f} games/sec)")
    print(f"Turns: min={min(turn_counts)}, max={max(turn_counts)}, "
          f"avg={sum(turn_counts)/len(turn_counts):.1f}")
    print(f"\nWin rates:")
    for name in names:
        n = wins[name]
        pct = 100 * n / args.batch
        player_type = "heuristic" if names.index(name) < args.heuristic else "random"
        print(f"  {name:<12} ({player_type:>9}): {n:>5} wins  ({pct:.1f}%)")


if __name__ == "__main__":
    main()
