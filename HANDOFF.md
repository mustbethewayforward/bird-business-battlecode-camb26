# Handoff: Cambridge Battlecode 2026 (cambc2026a) bot

Read this first in a new session, then `CLAUDE.md` (coding rules) and `README.md` (layout).

## 1. Who / what / goals

- Solo competitor, Python bot, team "Drunkards Walk" (renamed from "Bird Business"; the repo name is unchanged). Knows basic Python (ATBS, CS50P).
- **Goals set by the user:**
  - **Top 5 on the ladder.** At the last report the bot was 644 of 696 with a 37% win rate. Those platform games were still running an old frozen version (see §5).
  - **At least 19/20 against the official starter**, as a hard floor for the finished version.
  - **Farming speed may be traded for safety.**
- **Working style the user wants:**
  - Be direct and concise; call out flawed reasoning; no sugar-coating; explain jargon in brackets.
  - Follow `CLAUDE.md`: state assumptions; give each step a plan with a `→ verify:` check; make surgical changes; remove orphans you create.
  - **After each step:** release suites, commit, then a short report. Ask before the next step. The user replies "go".
  - **When a verify check fails, say so plainly.** Keep the change only with reasons, and give the `git revert <sha>`.
  - Never put model names in commits.

## 2. Repo and environment

- **Repo:** `mustbethewayforward/bird-business-battlecode-camb26`. Branch `claude/battlecode-sprint-1-bot-6uc0vg`; it's the only branch and has no main. Clone to `/home/user/bird-business-battlecode-camb26`.
- **Commit identity:** `git -c user.name="mustbethewayforward" -c user.email="mlgprowingzinnit@gmail.com" commit ...`. End commit messages with the session attribution lines from the system prompt.
- **Do not use the other repo** (`cyo-mcq-tester`), which is the user's MCQ app.
- **cambc CLI 2.2.5** (PyPI; a single binary inside the wheel; it isn't on the PATH by default):
  ```sh
  pip download cambc==2.2.5 --no-deps -d /tmp/cambc_pkg
  mkdir -p ~/cambc && cd ~/cambc && python3 -c "import zipfile;zipfile.ZipFile(next(__import__('glob').iglob('/tmp/cambc_pkg/*.whl'))).extract('cambc-2.2.5.data/scripts/cambc','.')"
  chmod +x ~/cambc/cambc-2.2.5.data/scripts/cambc
  export CAMBC=~/cambc/cambc-2.2.5.data/scripts/cambc
  cd /home/user/bird-business-battlecode-camb26
  $CAMBC init --yes .                 # restores sdk/ and cmake/ (gitignored). The wasi-sdk download error only affects C++; ignore it
  $CAMBC new --lang python starter    # official starter bot (gitignored), our baseline opponent
  ```
  The CLI tries to reach `2026a.battlecode.co.uk`, which the proxy blocks. That's harmless. Login, submit and match downloads must be done by the user.

## 3. Layout (what matters)

| Path | What |
| --- | --- |
| `bots/sprint2/` | **Current best and shippable** (commit `84f786e`). Submit this (`$CAMBC bundle sprint2 --output sprint2.zip`). |
| `bots/sprint3/` | Experimental: sprint2 (with E1) plus leader/follower group movement. Worse than sprint2 (41/90 vs 61/90); keep it only for the adaptive-mode work. |
| `bots/hunter/` | Test opponent: stun/damage spells on champions, attacks any visible enemy. The best stand-in for top teams. |
| `bots/ganker/` | Test opponent: the old sprint1 tuned to attack any visible enemy. |
| `bots/sprint1/` | Original Sprint 1 bot (history). |
| `bots/inspect/` | Map dumper (`$CAMBC run inspect inspect --map M --rounds 1; python scripts/logs.py replays`). |
| `maps/` (10), `maps-platform/` (5) | Local maps, plus maps recovered from platform replays. |
| `scripts/suite.py` | `python scripts/suite.py BOT OPP [--maps maps-platform] [--debug] [--rounds N]`: all maps, both sides. Prints win/loss, k/d, errors and fuel. Needs `CAMBC` set. |
| `scripts/logs.py` | Prints team stdout from a replay. |
| `scripts/report.py`, `scripts/platform_summary.py` | Analyse platform match JSONs (`cambc matches summary <id> --json`) and suite stats JSONs. Our team is identified by our draft order. |
| `scripts/extract_map.py` | Recovers the map from a platform match zip or replay. Validate the result with an inspect run. |

**Testing protocol:**
- Run suites against the starter, the ganker and the hunter, on both `maps` and `maps-platform`: 90 games in about 30 minutes, best run in the background.
- **Pre-build each bot first** (`$CAMBC run B B --map maps/3eb63432-*.map26a --rounds 1 --release -o replays/prebuild`). Otherwise parallel games race to rebuild the same `.wasm` and one game fails with "NO REPLAY".
- Never run a bot against itself under the same name; copy it to another folder first.
- **Quick checks:**
  - **Debug runs:** `dbg()` output and a `TEL` line every 100 rounds (no-op turns by decision branch, fuel skips, follower distance to the leader in sprint3).
  - **Fuel sensitivity:** copy the bot and add `for _ in range(3): me.position(); me.can_attack()` before `act()` (about +60k fuel per turn). Scores must stay identical.

## 4. Hard-won engine / SDK facts

- **Fuel:** Python gets 2.5M per turn. The first gameplay turn gets 5M, the draft 25M.
  - The fuel log in the replay zip is `team-X.fuel`: 13-byte header, then 8 limits as u64, then one u64 per turn.
  - A turn at the cap is suspended (no crash).
  - **Each SDK call costs about 20k.**
- **Expensive SDK calls:**
  - `vision.camp_groups()` rebuilds every group: about 1.1M per call. Use cached groups plus `vision.visible_tiles()`.
  - `Champion.move_towards` runs a full BFS (shortest-path search) every call. We use one `DistanceField.compute_to` per step with `max_distance = width * height`, because the default cap is too short on big maps.
- **Fuel guards that look at remaining fuel make behaviour chaotic.** A ~50k change once flipped a game from 352 gems to 0. Keep per-turn cost low, and prefer fixed budgets (e.g. 2 reach checks per turn) over "if fuel_remaining() < X".
- **The installed SDK differs from the user's docs.** `vision.awake_camp_tiles` is missing, and `ChampionType(3)` raises. Check names against `sdk/python/cambc/*.py`.
- **Vision:** you can't see into bushes from outside. Some camps are ringed by holes, so only ranged champions can hit them; capturing also needs a walkable spawn tile.
- **Rules that matter:**
  - One ability cast per turn, shared by both slots.
  - Damage cancels recall but not tribute.
  - Stun, death or an altar lock cancels a tribute.
  - Rewards are split among allies on the region.
  - The starting team alternates each round, so an enemy can act twice between two of our turns.
- **Platform errors:** `main.py` prints `turn error: ... at <line numbers>` in release builds. Match those line numbers against `git show <sha>:bots/sprint2/src/bot.py` to identify which version produced the logs.
- **Monster targeting (measured with a probe bot on 7ac1d8eb, elk and wolf):**
  - Each awake camp makes one attack per round, at full strength, on one champion. Damage is not shared across a squad.
  - It hits the nearest champion within range 3 (Chebyshev), re-chosen every round. Who attacked it doesn't matter, and it doesn't stick to a target.
  - Ties go to the earlier-drafted champion. HP and tile position don't decide it.
  - Range is 3 for elk and wolf: hit at 1–3, never at 4. So spells with range 4 hit camps without retaliation.
  - Not tested: whether camps also target enemy champions.
  - The old squad estimate (damage ÷ squad size, × 0.65) has no basis. The bot still rarely dies to camps (11 deaths in ~2,000 clears) because retreating at 35% HP passes aggro to the next-nearest champion.
- **Repeatability:** identical inputs give byte-identical replays and fuel logs, even with games running in parallel. Results from different sessions can differ (ganker: 12/20 here vs 13/20 earlier), so compare only against baselines measured in the same session.
- **Map identity:** a platform summary's `mapHash` is the SHA-256 of the `.map26a` file. 7ac1d8eb, dd8a22f2, 73ea9d96, e0125da0, 274fa801 and 4abecba3 have all appeared on the platform.

## 5. History in one paragraph

The Sprint 1 bot (splitting up to farm camps) beat the starter but lost every platform game against top teams. Their champions roam in groups with stuns: across the summaries, our team had 0 kills to 94 deaths. Several games had our team frozen all game because a fuel guard (a 1.3M reserve) blocked every path search; fixed in `6fa307a`, `d7d178f` and `1b919f4`. **The platform summaries the user sent most recently were still from old commit `28501c9`.** Make sure the user uploads the latest `sprint2.zip`. Group mode alone (sprint3) made results worse. E1, deliberate ability use, made them better (below).

## 6. Results (release mode, both sides; wins / games)

| Version | Starter local | Starter platform | Ganker local | Ganker platform | Hunter local | Hunter platform | Total /90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sprint2 `1b919f4` | 17/20 | 8/10 | 14/20 (351 deaths) | 9/10 | 7/20 (728 deaths) | 1/10 (380 deaths) | 56 |
| sprint3 `5b426a0` (grouping) | 13/20 | 8/10 | 7/20 (446 deaths) | 8/10 | 5/20 (709 deaths) | 1/10 (228 deaths) | 42 |
| **sprint2 `84f786e` (E1)** | 16/20 | 9/10 | 13/20 (333 deaths) | 10/10 | 6/20 (726 deaths) | 7/10 (290 deaths) | **61** |
| sprint3 + E1 | 13/20 | 10/10 | 5/20 (386 deaths) | 6/10 | 6/20 (714 deaths) | 1/10 (259 deaths) | 41 |

**Losses to the starter** (farming races, 0–1 deaths each):
- 274fa, from both sides.
- e6f13, from both sides. Its gem camps are ringed by holes, and our draft is all melee.
- 7ac1d8eb (71×71), as team B.

## 7. Agreed plan (the user's revised order, from an external review)

The external review's core thesis: **farm in small groups, concentrate quickly for valuable fights, split again afterwards.** A fixed structure (sprint2 always split, sprint3 always grouped) wastes champion turns.

1. ~~Remove wasted actions and choose abilities deliberately.~~ Done as E1 (`84f786e`).
2. **Mixed-camp targeting and the survival estimate (next).**
   - `fight()` currently hits the lowest-health camp in range (`min(..., key=health)`), so it kills 500-HP gem clusters before 2,400-HP elks. Damage taken stays at its maximum until the elks die.
   - Meanwhile `squad_size` assumes damage tapers off (`MULTI_CAMP_FACTOR = 0.65`).
   - Change to: target the camp that removes the most damage per turn of killing time (its strength divided by turns to kill it). Exception for Varg: prefer the target that maximises his splash. Then make the survival estimate match the new kill order.
   - Also cap squad waits (`SQUAD_WAIT = 80` is longer than a death's 60-round respawn), e.g. 20 rounds, and abort if support isn't getting closer.
3. **Danger until our next action**, replacing "35% health" and "even numbers nearby":
   - Count the enemies that can reach us before our next turn, allowing them two actions because of the alternating turn order, plus stuns and camps.
   - Then coordinate combat: a shared reachable target, different attack tiles for each champion, a stop condition for chases, staggered stuns.
   - Add adaptive modes: **farm** (split) / **contest** (concentrate, shared target) / **recover-and-deposit** (escort carriers). Shared memory needs threat and target messages that carry freshness information.
4. **A full route check: attack, capture tile, exit** (walking vs dash vs teleport crystal). Then test a draft change: a ranged attacker plus a mobile collector where the map needs it.
5. **Builds and group sizes.**
   - For Ryth, compare Health against Strength shards while holding the emblem family constant.
   - Measure first-capture time, gems banked, recovery time and deaths.
   - Later experiments: Willow sustain pairs, Cassi & Issac, capture and tribute interception, tribute safety (don't start a tribute while threatened or stunned; avoid locked altars).

**For every combat change, test with sprint2's routing and with sprint3's grouping.** Grouping has an economic cost, and it's still unknown whether coordinated abilities repay it.

## 8. State at handoff

- `bots/sprint3` has E1 ported and is committed. It's still clearly worse than sprint2 (41/90 vs 61/90). Permanent grouping costs more than coordinated abilities win back, which supports the adaptive farm/contest/recover idea in §7 step 3. sprint2 at `84f786e` was sent to the user to upload.
- After that: step 2 of §7 on sprint2 (and ported to sprint3), with checks:
  - **Check A:** against the starter, no worse than 16/20 local and 9/10 platform.
  - **Check B:** against the hunter and ganker, fewer deaths.
  - **Check C:** in debug logs, elks get killed before gem clusters in mixed groups.
- Ask the user for fresh platform summaries (`cambc matches summary <id> --json`) of the latest submission, plus match zips. New maps can be added with `scripts/extract_map.py`.

**Next session's update: the plan was revised and the step-1 result recorded.**
- **Revised sequence:**
  0. Probe monster targeting (done; see §4).
  1. Refresh `need` after purchases.
  2. Kill ordering.
  3. Replace the survival model, checking predicted damage against what the most-hit champion actually took.
  4. Squad-wait cap with a team-wide, expiring abandonment cooldown.

  Gates check for regressions rather than demanding improvement: an 18-game matched set after each commit, then the full protocol on the combined candidate.
- **Same-session baseline (`84f786e`), 60/90:**
  - Starter: 16/20 local, 9/10 platform.
  - Ganker: 12/20 (314 deaths) local, 10/10 (85) platform.
  - Hunter: 6/20 (726) local, 7/10 (290) platform.
- **Step 1, refreshing `need` from own stats after each purchase plus an on-site safeguard: not committed.** Compared with the matched baseline:
  - Previously excluded groups were cleared only 2 times.
  - Overall clears +10% and gems banked +7%, but wins fell from 11 to 9.
  - The refreshed estimate for excluded groups still needs the whole team, and teammates whose own estimate stays at 99 never join. **Champions must agree on one team-wide `need`** before refreshing helps.
- **Platform summaries:** of the 10 sent, 8 were losses. Most were farming races rather than deaths. Helpers who do the fighting often earn 0 gold, because only the lowest-numbered squad member captures.
