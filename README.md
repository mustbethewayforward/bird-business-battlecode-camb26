# Drunkards Walk: Cambridge Battlecode 2026 (cambc2026a)

Python bot for Cambridge Battlecode. Built and tested with `cambc` CLI **2.2.5**.

## Layout

| Path | What |
| --- | --- |
| `bots/sprint1/src/main.py` | Entry point: the turn loop. Every turn is wrapped in try/except, so a bug never crashes the bot; errors are printed as `turn error: ... at <line numbers>`. |
| `bots/sprint1/src/bot.py` | All decisions: draft, shopping, retreat, tribute, enemy carriers, camp farming. Tunables are at the top. |
| `bots/sprint2/` | **Current submission.** sprint1 plus attack-reset abilities (extra hit every 8 turns) and always hitting back when an enemy champion is hitting us. |
| `bots/hunter/` | Test opponent only: sprint2 that drafts stunners (Ryth, Tavi, Marcella, Ren), casts stuns and damage spells on enemy champions and attacks any visible enemy. Tougher than the ganker: sprint2 wins 7/20 vs it (14/20 vs ganker). |
| `bots/ganker/` | Test opponent only: sprint1 tuned to attack any visible enemy champion, ignoring numbers. Reproduces the platform losses (we were hunted down solo). |
| `bots/inspect/` | Map inspector: prints camp groups, altars and an ASCII picture of a map. |
| `maps/` | Local test maps (`.map26a`). |
| `scripts/suite.py` | Plays a bot against an opponent on every map from both sides, reporting wins, errors and fuel. |
| `scripts/logs.py` | Prints a team's stdout from a replay bundle. |

## Setup

```sh
pip install cambc==2.2.5          # the CLI
cambc init --yes .                # adds sdk/ and cmake/ (gitignored)
cambc new --lang python starter   # official starter bot, used as the test opponent
```

## Run

```sh
cambc run sprint1 starter --map maps/<map>.map26a --release   # one game, platform settings
python scripts/suite.py                                         # all maps, both sides
python scripts/suite.py --debug --rounds 600                    # keep debug output, shorter games
python scripts/logs.py replays/suite/<map>-a                    # read our stdout from a game
cambc run inspect inspect --map maps/<map>.map26a --rounds 1 && python scripts/logs.py replays
```

`--release` matches the platform: `debug_block` output is dropped and fuel matches. Debug builds print a `SCORE` line every 100 rounds, a status line per champion every 25 rounds, and events (tribute, recall, give up, DIED).

## Submit

```sh
cambc login
cambc submit sprint1        # or: cambc bundle sprint1, then upload the zip
```

## How the bot plays

Each champion runs `bot.py`. In priority order, each turn it:

1. Shops on spawn, while dead, or anywhere if it's Tavi. Monster Strength comes first, then Jungle Health, then Power. Ryth and the fragile champions buy health first; Vesper buys Treasure first. It buys one altar lock after the first emblem.
2. Leaves channels (tribute, recall) running, and heals on spawn before leaving.
3. Locks an altar an enemy is tributing at, if it carries a lock.
4. Retreats below 35% health. It walks home while being hit, because damage cancels recall, and recalls once nothing is hitting it.
5. Hits back at an enemy champion attacking it, or attacks an enemy carrying 15+ gems (or mid-tribute), but only with even or better numbers nearby.
6. Tributes when the bag is 50+, an altar is within 2 tiles or costs at most 10 extra steps, enemies are near, or it is hurt.
7. Farms. It picks the camp group with the best gems per round. Groups one champion can survive go to one champion. Harder groups wait (up to 80 rounds) for a squad, sized from total camp HP and damage. Monolith groups are never targeted. It kills the weakest camp first, then the lowest-numbered squad member captures and the rest move on.

**Coordination:** champions are numbered by sorted engine handle. Shared-memory byte *k* holds (group index + 1) for champion *k*'s target, or 0 for none.

**Safety valves, all found in local testing:**
- A target the champion hasn't got closer to in 8 turns is dropped for 40 rounds. This covers no path, camps ringed by holes, and camps hidden in bushes.
- A capture still unclaimed after 8 rounds is contested by an enemy, so the champion leaves.
- Pathfinding is one breadth-first search per step, skipped when less than 1.3M fuel is left in the turn.
- The first turn only runs setup.

## Test results (cambc 2.2.5, release mode, full 2000-round games vs the official starter)

| Map (first 8 chars) | As team A | As team B |
| --- | --- | --- |
| 274fa801 | win (1000 gems, r1155) | win (r1322) |
| 3eb63432 | win (r712) | win (r810) |
| 41a82994 | win (r1067) | win (r803) |
| 4abecba3 | loss | loss |
| 73ea9d96 | win (0–0 gems, gold tiebreak) | win (gold tiebreak) |
| 7aa77c9a | loss | loss |
| c4baf2d2 | win (0–0 gems, gold tiebreak) | win (gold tiebreak) |
| dd8a22f2 | win (r688) | win (r707) |
| e0125da0 | win (r814) | win (r1301) |
| e6f13c58 (100×100) | loss | loss |

The bot wins 7/10 from each side, with zero `turn error`s. The worst non-first turn uses 2.02M of the 2.5M fuel budget.

## Sprint 2 change (from platform losses)

Unranked games vs top-75 teams were all losses: across 4 summarised matches we had 0 kills and 94 deaths. Top teams roam in groups with stuns and kill our champions one at a time while they farm alone. sprint2 is the change that fitted in one hour before the lock. Full release games on all maps, both sides:

| | sprint1 | sprint2 |
| --- | --- | --- |
| vs ganker | 6/20 | 11/20 |
| vs starter | 14/20 | 14/20 |

Zero errors, and the worst later turn uses 2.02M fuel. The real fix is next: move and fight as a pack, focus fire, stuns.

## Known weaknesses / next steps

- **Losses** on 4abecba3, 7aa77c9a and e6f13c58. These maps have long distances and a lot of elk-guarded gems, where squads form slowly.
- **Altar locks** are coded but never triggered in local games.
- **"Coordinated fights"** means camp squads plus the numbers check before fighting champions. There's no planned group attack on enemies yet.
- **Damage model:** squad sizes assume camp damage spreads across the squad. That hasn't been measured; lone-wolf damage matched the estimate.
- **No abilities are used.** Attack-reset abilities alone would add a lot of camp damage.

## SDK gotchas (2.2.5 vs the published API docs)

- `cambc.vision.awake_camp_tiles` / `asleep_camp_tiles` are in the docs but missing at runtime. Use `vision.camps()` and `camp.is_awake()` instead.
- `ChampionType(3)` raises TypeError even though the docs call it an IntEnum. Pass plain ints, e.g. `Champion.design(3)`.
- Every SDK call costs roughly 20k fuel, so read values once per turn and reuse them.
- `Champion.move_towards` runs a full shortest-path search on every call. `DistanceField.compute_to`'s default distance cap is too short for big maps, so pass `width * height`.
- You can't see into bushes from outside, so camps in bushes are only visible from inside the bush.
