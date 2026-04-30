# Monopoly Simulator: Handoff Document

## What we're building

A simulator for the classic game of Monopoly, written in Python, that supports three different modes of use:

1. **Batch simulations** that play millions of games quickly for statistical analysis — for example, verifying which squares actually get landed on most often.
2. **Interactive play** where we (humans) can play against computer-controlled opponents from a terminal.
3. **AI-vs-AI play** where a Claude Code session acts as one or more players, competing against other AI or human players.

We're building this as a vibe-coding project, so the priority is getting a working, enjoyable system — not shipping a commercial product. That said, we want the architecture to be *clean enough* that each stage builds smoothly on the last, rather than forcing rewrites.

## Priorities (in order)

When design tradeoffs come up, resolve them in favor of whichever choice serves the higher-priority goal:

1. **Fast batch simulation.** Tens of thousands of games per second with simple players. This is how we answer questions like "which squares get landed on most?"
2. **Full classical rule fidelity.** Trading, auctions, building evenly, the 32-house supply limit, the jail mechanics, all of it. No convenient simplifications.
3. **Strong LLM play.** Claude (running inside Claude Code) should be able to play competitively against heuristics or other Claude instances.
4. **A clean path to a graphical UI later.** Not a v1 requirement, but don't paint us into a corner.

## A key constraint

**We don't want to call the Anthropic API from the simulator.** Hard no.

Instead, when Claude plays, it plays from *inside* a Claude Code session. The simulator runs as a long-lived Python process that exposes an MCP server, and Claude Code connects to it as a client. Claude asks the server "what's the state?" and "what are my legal moves?", then calls "take this action." The simulator doesn't know or care that the client is an LLM.

This constraint matters because it shapes the architecture. The simulator needs to handle a player that takes minutes between decisions (because Claude Code is thinking, or because the human is) without blocking. See the architecture section below.

## The build order

We'll build this in six stages. Each stage should produce something working and useful before we move to the next:

1. **Board data + movement-only simulator.** A tiny standalone program: dice, a board, jail rules, and the movement-affecting Chance/Community Chest cards. No economics, no players. Roll the dice a million times and report landing frequencies. Answers our "is red really landed on most?" question in an afternoon.
2. **Full game engine with dumb players.** All the real rules — buying, rent, jail, building — driven by a `RandomPlayer` (moves randomly, buys everything) and a `HeuristicPlayer` (simple hand-written strategy). ASCII board renderer. Event log. Games complete; someone wins.
3. **Human command-line player.** Rob and Jen play against the heuristic from a terminal.
4. **MCP server wrapping the engine.** Now Claude Code can connect and play as one or more seats.
5. **Auctions, trading, and building polish.** The mechanics we stubbed out earlier, filled in properly.
6. **Optional web UI later.** Only when we actually want it.

## Architectural principles

This is the important section. These principles apply to stages 1 and 2, and if we get them right, stages 4 through 6 become implementation work rather than rewrites.

### The engine doesn't run the game — it waits

This is the single most important decision.

A naive game engine has a loop inside it: `while not game_over: play_one_turn()`. That loop calls out to players, waits for their responses, and drives everything forward. This is fine for a standalone command-line game, but it falls apart the moment you need to share the engine with an MCP server or a web UI, because the engine is always "busy" running its loop.

Instead, the engine should be a **state machine**: it holds a snapshot of the game, and external code transitions it forward by calling `engine.apply(action)`. Between calls, the engine is dormant. It advertises what it's waiting for — "player 2 needs to decide whether to buy Illinois Avenue" — but it doesn't make anything happen on its own.

An analogy: a vending machine doesn't serve itself. It displays what's available, waits for you to insert coins and press a button, then dispenses. It never loops. Our engine should behave the same way.

A thin convenience layer called a `GameRunner` can wrap the engine with a simple loop for command-line use — something like ten lines that asks the engine what's pending, asks a player what to do, and calls `apply`. But the runner is a client of the engine, not part of it. The MCP server in stage 4 is a different client of the same engine.

### Actions are data, not function calls

When a player decides to buy a property, they don't call `engine.buy_property("illinois")`. They produce an object like `BuyProperty(property="illinois")` and hand it to `engine.apply(action)`.

This matters because data can be:
- **Logged** — every action that's ever taken becomes a line in a file, which is your debug trail and your replay mechanism.
- **Serialized** — sent over a network (essential for the MCP server in stage 4) or saved to disk.
- **Inspected** — a test can assert "the third action in this game was a BuyProperty."
- **Enumerated** — the engine can generate a list of every *legal* action right now and hand it to the player, which matters for the next principle.

If you only take one idea from this document, take the previous one and this one. They unlock everything else.

### Legal actions are enumerated by the engine

Players don't need to know the rules. When it's a player's turn to decide something, the engine provides a list of the actions they're allowed to take — for example, `[BuyProperty(cost=240), DeclineProperty]` — and the player picks one.

This is crucial for the LLM player. Claude doesn't have to construct a well-formed action from scratch (which risks hallucinated moves or invalid JSON); it picks from an enumerated menu. Illegal moves are literally impossible.

It's also crucial for heuristic players, test fixtures, and the human CLI, because all of them can display or reason over the same menu.

### Pending decisions are a list, not a single "current player"

A first-draft engine usually tracks "whose turn is it?" as a single integer. This works until you hit auctions, trades, or building events — at which point multiple players may owe decisions at the same time, and not necessarily the player whose turn it is.

For example: player 1 declines to buy Illinois Avenue. The rules say the property goes to auction among *all* players. Suddenly every player has a pending decision (their bid), even though it's still technically player 1's turn.

The right model is a **queue of pending decisions**, each tagged with the player it belongs to. The engine always knows "what decisions are waiting?" and "who needs to make each one?" During a normal turn there's one decision at a time. During an auction there are several. Trading can inject a decision into an opposing player's queue even when it isn't their turn.

If stage 2 represents "whose turn" as a single integer, stage 5 (auctions and trading) will require a rewrite. If stage 2 represents it as a queue, stage 5 is adding new decision types and new action types, with no structural change.

### Randomness is seeded and explicit

Never use Python's global `random` module. Every source of randomness — dice, card shuffles, auction tiebreakers — reads from a `random.Random` instance that lives inside the game state.

The payoff is **reproducibility**. If we see a weird bug in game #4,837, we can replay it exactly. If we want to rigorously compare two strategies, we can run them against identical dice sequences. And the batch simulator needs this to produce trustworthy statistics.

Seeding is a ten-minute habit that pays for itself within the first week.

### Every game change is logged as an event

Alongside the game state, the engine maintains an **event log** — an append-only list of structured records for everything that happens. `DiceRolled(player=2, dice=(3,4))`. `PlayerMoved(player=2, from=10, to=17)`. `PropertyBought(player=2, property="st_charles", price=140)`. `RentPaid(payer=2, owner=1, amount=50, property="st_charles")`.

This log is triple-duty:

- **Debugging.** When something goes wrong, you read the log and see exactly what happened.
- **Statistics.** The landing-frequency analysis is just "count `PlayerLanded` events by square." Any other stat you want later is a pandas query over the log.
- **Replay.** Given the seed and the log, you can reconstruct the game exactly.

Don't bolt this on later. Build it into stage 2 from day one.

### Players implement one tiny interface

Everything that makes a decision — the random player, the heuristic, the human at the terminal, and eventually the LLM — implements the same minimal interface. Give it a view of the state and a pending decision, get back an action.

```python
class Player(Protocol):
    def decide(self, state_view, pending_decision) -> Action: ...
```

Stage 2 gives us `RandomPlayer` and `HeuristicPlayer`. Stage 3 adds `HumanCLIPlayer`. Stage 4's MCP server uses the same interface from the other side: the server's tools *expose* the pending decision, and the client (Claude Code) returns the chosen action.

Keep the state view read-only and well-defined. Players can't cheat by reaching into internal fields.

## Rule modularity

Monopoly's rules have changed over the decades, and we want to be able to play under different rulesets without changing engine code.

The key variations we care about:

- **Pre-2008 US rules.** Luxury Tax is $75. Income Tax is a choice between $200 and 10% of net worth (chosen *before* you can calculate your total, a legendary trap).
- **Post-2008 US rules.** Luxury Tax is $100. Income Tax is a flat $200, no choice. Some Chance/Community Chest cards were renamed. This edition matches the landing-frequency analyses we'll validate against.
- **2021 Community Chest rewrite.** Same mechanics, all-new card text focused on "community" themes.
- **House rules.** Free Parking jackpot, $400 for landing exactly on Go, must circle the board before buying, etc.

The right model is a **RuleSet**: a configuration object that the engine takes at construction time. It holds every tunable parameter — tax amounts, jail fines, house supply, which deck to use, which house rules are active. Engine code reads from the RuleSet at decision points rather than hardcoding values.

We'll ship preset constructors (`us_1935()`, `us_2008()`, `us_2021()`, `family_game()`) so users don't have to specify every field individually, and so house-rule layers can be composed on top of era presets.

A different way to say this: **pre-2008 versus post-2008 is a configuration, not a code branch**. There is no `if era == "pre_2008":` anywhere in the engine. There are only parameters that differ.

## Data files, not hardcoded tables

The board layout, the Chance deck, and the Community Chest deck all live in YAML (or JSON) data files, not in Python code. The engine loads them at startup.

This matters for three reasons:
- Swapping the 2008 Community Chest for the 2021 one is a one-line change (`community_chest_deck_path`), not a code edit.
- If we ever want to play the UK edition or a themed edition, we write a new data file rather than a new engine.
- The rent tables and card effects are easier to proofread as a data file than as buried code.

### Card effects: use a small taxonomy of "kinds"

Rather than writing a bespoke handler for each card, cards declare their *kind* (from a small list) plus parameters. About ten kinds cover every card in every historical edition:

- `move_absolute` — go to a specific square
- `move_relative` — offset by N spaces
- `move_nearest` — go to the nearest railroad or utility
- `go_to_jail`
- `get_out_of_jail` — keepable card
- `collect_from_bank` / `pay_to_bank` — fixed amount
- `collect_from_each_player` / `pay_each_player`
- `pay_per_building` — repairs-type card, $X per house, $Y per hotel

This means "Bank pays you dividend of $50" (2008) and "You rescue a puppy, collect $50" (2021) are the same kind with the same amount — only text and ID differ. Changing decks becomes changing data files.

### Data files should be validated on load

A single loader module that reads all the data files and asserts things like "every square index 0-39 appears exactly once," "every card references a real square," "every deck has exactly 16 cards," "every color group's members exist and are of type `property`." Write this once; it protects us forever. When we add a UK board next year, we'll learn about malformed data at startup instead of during a weird crash mid-game.

## The canonical ruleset

For the first version, target the **post-2008, pre-2021 US standard edition**. Reasons:

- It matches the published landing-frequency analyses we can validate against (see research links below).
- It's the longest-stable, best-documented ruleset.
- The 2008 redesign eliminated the Income Tax choice option, which is a minor but annoying complication to model correctly.
- The 2021 Community Chest rewrite is mechanically identical to 2008 — adding it later is a data-file swap.

## Research links (comprehensive rules and data)

### Rules
- [Hasbro official rulebook page](https://instructions.hasbro.com/en-us/instruction/monopoly-board-game-classic-game-with-storage-tray-and-larger-tokens-family-games-8) — the publisher's current PDF.
- [Hasbro archived PDF (older edition)](https://www.hasbro.com/common/instruct/00009.pdf) — more detailed, good cross-reference.
- [Wikipedia: Monopoly (game)](https://en.wikipedia.org/wiki/Monopoly_(game)) — thorough and systematic, especially good on the 2008 redesign differences.
- [Monopoly Fandom Wiki: Official Rules](https://monopoly.fandom.com/wiki/Official_Rules) — community-maintained, useful for edge cases.

### Property prices, rents, mortgages, house costs
- [Falstad's Monopoly data tables](https://www.falstad.com/monopoly.html) — single densest reference: every property, every rent tier, every mortgage value.
- [Monopoly Land property list](https://www.monopolyland.com/monopoly-properties-list-with-prices/) — clean list by color group.
- [Monopoly Fandom Wiki: Property](https://monopoly.fandom.com/wiki/Property) — per-property deep-linked details.

### Chance and Community Chest cards
- [Monopoly Land: All card lists (US + UK, 2008–2021 and 2021-onward)](https://www.monopolyland.com/list-monopoly-chance-community-chest-cards/) — best single source, includes retired cards.
- [Monopoly Fandom Wiki: Chance](https://monopoly.fandom.com/wiki/Chance) — annotates differences across editions.
- [Monopoly Fandom Wiki: Community Chest](https://monopoly.fandom.com/wiki/Community_Chest) — same, for the other deck.

### Landing-frequency validation (critical for stage 1)
- [Truman Collins: Probabilities in the Game of Monopoly](http://www.tkcs-collins.com/truman/monopoly/monopoly.shtml) — the canonical reference. 32 billion simulated rolls, steady-state probabilities for all 40 squares, separate figures for different jail strategies. Our simulator should reproduce these numbers.
- [Towards Data Science: Oh, the Places You'll Go in Monopoly](https://towardsdatascience.com/oh-the-places-youll-go-in-monopoly-96abf70cdbd7/) — modern readable walkthrough with the same results.
- [MIT probability paper](https://web.mit.edu/sp.268/www/probability_and_monopoly.pdf) — academic treatment.

## On the "is red landed on most?" question

The motivating question for stage 1. The quick answer we've seen in the research:

- **Most landed-on single square**: Jail (by a huge margin — multiple ways to end up there).
- **Most landed-on individual property**: Illinois Avenue, which is red.
- **Most landed-on *color group* by average**: Orange. Reason: the Go-to-Jail square is a common dice distance (6, 8, 9) from the orange group, so whenever you leave jail, you're disproportionately likely to land orange.

So "red is landed on most" is half-right: true at the single-property level, false at the group level. Our simulator should reproduce both results, and this gives us a concrete correctness check against Truman Collins's published numbers.

## Rules gotchas worth flagging

Homebrew Monopoly simulators routinely get these wrong. Please model them carefully:

1. **"Advance to nearest Railroad" card**: the owner is paid *double* the normal railroad rent, not single.
2. **"Advance to nearest Utility" card**: rent is *ten times* the dice roll regardless of how many utilities the owner holds — this *overrides* the usual 4× / 10× rule.
3. **Three doubles in a row sends you to jail.** The player does not complete the third move.
4. **Houses must be built evenly within a color group.** No second house on a property until every property in the group has one.
5. **The bank has a finite supply**: 32 houses, 12 hotels. If buildings run out, contested purchases go to auction. This is routinely ignored in home games but it's a real rule and it affects strategy.
6. **Auctions when a player declines**: if a player lands on an unowned property and declines to buy, the property is auctioned among *all* players (including the one who declined). Model this; it's significant.
7. **Mortgaging**: receive half the price from the bank; repay with 10% interest to unmortgage. Mortgaged properties can be traded.
8. **Jail has two strategic modes** that Collins treats separately: "pay immediately to get out" versus "stay as long as possible rolling for doubles." Both are legal. Make this a player strategy option, not a hardcoded rule.
9. **Get Out of Jail Free cards are keepable and tradeable.** When used, the card goes back to the bottom of its deck.
10. **Income Tax in the 1935–2008 era** was a choice of $200 or 10% of net worth, chosen before calculating total holdings. If we ever support pre-2008 rules, this is the quirk.

## First task: stage 1

**Build the movement-only simulator first.** It's a few hundred lines, standalone, and answers our motivating question in an afternoon.

Scope:
- Load the board data file and the Chance + Community Chest decks (the full decks — we'll only use movement-affecting cards, but the decks should be loaded whole).
- Implement dice rolls, square-to-square movement, the three-doubles-to-jail rule, the Go-to-Jail square, and the movement effects of cards (advance to X, nearest railroad, nearest utility, go back three spaces, go to jail).
- Ignore all economics: no money, no properties, no rent, no players with state. Just a token moving around a board.
- Run millions of rolls with seeded RNG. Output per-square landing frequencies.
- Compare against Truman Collins's published numbers. Match them to within sampling error.

Keep the movement sim as its own module. Don't try to generalize it into the full engine — it's genuinely simpler, and having it as a standalone reference is useful for validating the full engine later.

**What to share between stage 1 and stage 2**: the board and deck data files, and the seeded-RNG habit. Nothing else. The engine in stage 2 will be structurally different (state machine, event log, etc.) and trying to reuse stage 1's tiny loop would be a false economy.

## Things to revisit

Questions we're deferring, but want to flag so they're not forgotten:

- **Exactly how the MCP server exposes tools.** We'll figure this out in stage 4 when we see what Claude Code needs.
- **How ASCII rendering looks.** Prototype something basic in stage 2; iterate in stage 3.
- **Web UI technology choice.** Deferred to stage 6.
- **Whether to support Mega Edition or UK board.** Possibly, someday. The data-file architecture makes this cheap if we want it.

---

*If any of the principles above feel unclear, stop and ask — they're more important than speed. Everything else is negotiable.*
