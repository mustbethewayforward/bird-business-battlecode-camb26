# Handoff: Cambridge Battlecode 2026 (cambc2026a) bot

Read this first in a new session, then `CLAUDE.md` (coding rules) and `README.md` (older layout notes; this file wins where they differ).

## 1. Who / what / goals

- Solo competitor, Python bot, team "Drunkards Walk" (the repo name is unchanged). Knows basic Python (ATBS, CS50P).
- **Goals set by the user:**
  - **Top 5 on the ladder.**
  - **At least 19/20 against the official starter**, as a hard floor for the finished version.
  - **Farming speed may be traded for safety**, but survival bought by abandoning objectives is not an improvement.
- **Working style the user wants:**
  - Be direct and concise; call out flawed reasoning; no sugar-coating; explain jargon in brackets.
  - Follow `CLAUDE.md`: state assumptions; give each step a plan with a `→ verify:` check; make surgical changes; remove orphans you create.
  - **Before coding a new step,** give the plan and wait for "go". **After each step,** report results.
  - **When a check fails, say so plainly.** Keep a change only with reasons, and give the `git revert <sha>`.
  - **Experiments go in their own `bots/exp-*` folders**, one fix per commit. `bots/sprint2` is the submission and only changes on promotion.
  - **Evidence rules:**
    - Compare only against a control measured on the same engine version in the same setup.
    - First run focused cases to confirm the mechanism, then the full protocol to decide promotion.
    - Report paired win/loss changes, gems banked and lost, deaths and fuel caps.
  - Never put model names in commits.
  - The user often relays an external reviewer's critique. Treat it as instructions, but push back with data when it's wrong.

## 2. Repo and environment

- **Repo:** `mustbethewayforward/bird-business-battlecode-camb26`. Branch `claude/battlecode-sprint-1-bot-6uc0vg`; it's the only branch and has no main. Clone to `/home/user/bird-business-battlecode-camb26`.
- **Commit identity:** `git -c user.name="mustbethewayforward" -c user.email="mlgprowingzinnit@gmail.com" commit ...`. End commit messages with the session attribution lines from the system prompt.
- **Do not use the other repo** (`cyo-mcq-tester`), which is the user's MCQ app.
- **cambc CLI 3.0.4** (the 3.0 balance patches; results from older versions are not comparable). It's on PyPI as a single binary inside the wheel and isn't on the PATH by default:
  ```sh
  pip download cambc==3.0.4 --no-deps -d /tmp/cambc_pkg
  mkdir -p ~/cambc304 && cd ~/cambc304 && python3 -c "import zipfile;zipfile.ZipFile(next(__import__('glob').iglob('/tmp/cambc_pkg/*.whl'))).extract('cambc-3.0.4.data/scripts/cambc','.')"
  chmod +x ~/cambc304/cambc-3.0.4.data/scripts/cambc
  export CAMBC=~/cambc304/cambc-3.0.4.data/scripts/cambc
  cd /home/user/bird-business-battlecode-camb26
  $CAMBC init --yes .                 # restores sdk/ and cmake/ (gitignored). The wasi-sdk download error only affects C++; ignore it
  $CAMBC new --lang python starter    # official starter bot (gitignored), our baseline opponent
  ```
  - Check PyPI (`pip index versions cambc`) at the start of a session. New patch versions have changed balance twice.
  - The CLI tries to reach `2026a.battlecode.co.uk`, which the proxy blocks. That's harmless, but login, submit, `cambc maps pull` and match downloads must be done by the user.
- **The container restarts without warning and kills background jobs** (it happened twice in one session). Run long batches with `nohup` and `scripts/games.py`, which skips games that already have results. Anything outside the repo (scratch folders) can be lost, so commit results worth keeping under `results/`.
- **4 CPU cores.** A 70-game suite on `maps3` takes about 45 minutes at 4 jobs. The full 210-game protocol takes about 2.5–3 hours, or twice that when two bots share the cores.

## 3. Layout (what matters)

| Path | What |
| --- | --- |
| `bots/sprint2/` | **Submission / control.** Last changed at `a0ed551`: E1 abilities, kill ordering (`5789ee4`), unknown-camp guard (`0f2362e`), altar-lock fix (`a0ed551`). |
| `bots/exp-combat/` | **Lead candidate** (`9aa3ef4`): sprint2 plus disengaging from losing champion fights (§7). Full 3.0.4 evaluation not finished. |
| `bots/exp-demand-asm/` | 2.2.5-era experiment: solo feasibility from each champion's own stats, with attack resets simulated turn by turn (`1094209`), a squad election, and the plain 80-round wait (`d7e4863`); 3.0.1 compatibility and lock fixes added. Known flaw: the election sends the spare champion to far-away solo (gold) work. Not evaluated on 3.0.4. |
| `bots/exp-demand/`, `bots/exp-assembly/`, `bots/exp-refresh/` | Older 2.2.5 experiments (history only). |
| `bots/sprint3/` | Leader/follower grouping (worse than sprint2 on 2.2.5; history). |
| `bots/hunter/`, `bots/ganker/` | Test opponents. The hunter (stuns, attacks any visible enemy) is the stand-in for top teams. |
| `bots/inspect/` | Map dumper: `$CAMBC run inspect inspect --map M --rounds 1; python scripts/logs.py replays`. |
| `maps3/` | **The 35-map 3.0 platform pool** (from the user's `cambc maps pull`). Test on this. |
| `maps/`, `maps-platform/` | Old 2.2.5 maps (history). |
| `scripts/games.py` | Resumable runner: `python scripts/games.py BOT OPP OUT_DIR JOBS map:side ...`. Release mode, stats JSON per game, large log limit, skips games already done. |
| `scripts/pair.py` | `python scripts/pair.py CONTROL_DIR CANDIDATE_DIR`: game-by-game pairing plus totals (wins, gems, gold, champion/camp deaths). |
| `scripts/suite.py` | Older runner (`--maps maps3`). It deletes `replays/suite` each run, so never run two at once. Prints fuel caps. |
| `scripts/logs.py` | Prints a team's stdout from a replay (`team-a` / `team-b`). |
| `results/3.0.4/` | Saved per-game results (§6). |

**Testing protocol (3.0.x):**
- **Full protocol:** 35 maps × both sides × {starter, ganker, hunter} = 210 games, using `games.py` with all maps:
  ```sh
  ALL=$(ls maps3 | sed 's/.map26a//' | awk '{print $1":a "$1":b"}' | tr '\n' ' ')
  ```
- **Pre-build** happens automatically in `games.py`. Never run a bot against itself under the same name.
- **Determinism:** identical inputs give byte-identical replays. One run per game is enough, but only compare within the same engine version.
- **Debug traces:** copy a bot into an excluded folder (add it to `.git/info/exclude`) and print a per-turn `TR` line (branch, HP, camps and foes in range, ally distances), then read the turns before each `DIED`. This is how both 3.0 diagnoses in §5 were made.

## 4. Engine / SDK facts (3.0.4 unless noted)

- **Fuel:**
  - Python gets 2.5M per turn, the draft 25M, and the first gameplay turn 5M.
  - The first turn's entry in the fuel log reads 5.0M even when init finishes with about 1.5M to spare, so ignore it.
  - **Each SDK call costs about 20k.**
  - `vision.camp_groups()` costs about 1.1M per call.
  - Fuel guards that check `fuel_remaining()` make behaviour chaotic, so prefer fixed budgets.
- **Monster targeting (measured with probe bots, re-checked on 3.0.1):**
  - Each awake camp makes one full-strength attack per round on the **nearest champion** in its range, re-chosen every round.
  - Ties go to the earlier-drafted champion. Damage is not shared across a squad.
  - **Ranges:** wolf 3, **elk 4**, **Golem 4**, **monolith 5**. Range-4 spells no longer avoid retaliation from elks.
  - Camps sleep 2 rounds after nobody is in range.
  - **An awake monolith can hit you unseen.**
- **Camp values on 3.0:**

  | Camp | HP | Gems | Gold |
  | --- | --- | --- | --- |
  | Wolf | 1,350 | 4 | 40 |
  | Elk | 2,400 | 15 | 90 |
  | Gem cluster | 120 | 7 | — |
  | Gold cluster | 120 | — | 20 |
  | Golem (new) | 5,000 (120 Strength) | 36 | 160 |

  Value now comes from clusters added to groups. 36% of the pool's gems sit in monolith or Golem groups, which sprint2 skips.
- **Other 3.0 rules:**
  - Kill gold is **100**.
  - Ward cooldown is 10.
  - Altar locks take **5 hits**. A tribute against an enemy-locked altar becomes an attack on the lock, and errors if the attack is already spent.
  - Marcella earns 2 gold per gem tributed, and it counts in `earnedGold`, which is the gold tiebreak.
- **Stats on 3.0.4:**
  - Ryth Strength 45; Varg Strength 40; Ren Strength 35 with stun 0.75× Focus; Vendetta HP 1,000; Vesper HP 1,000, Strength 55, +33% gold.
  - Tavi Focus 110, HP 900; Stellar Focus 70, HP 650.
  - Heart of Ruin (new): Strength 30, damaging dash 1.5× Focus with radius 1, up to +50% damage when hurt.
  - **Prism gains 1.5 Focus per carried gem.**
  - **Read these at runtime instead of hard-coding them:** `Champion.design(t).base_stats()`, `.abilities()` with `info().modifier/range/radius`, `cambc.constants` and `cambc.constants.passive_abilities`.
- **The draft has 12 picks** (`HEART_OF_RUIN` = 11). `ChampionType` has 13 values: Cassi and Issac are separate types.
- **Rules that matter:**
  - One ability cast per turn.
  - Ryth's and Ren's stuns forbid walking that turn. Varg's shield and Marcella's reset don't.
  - Damage cancels recall but not tribute.
  - The starting team alternates each round, so an enemy can act twice between two of our turns.
- **Local runner bug (3.0.x):** some games fail with "unexpected end-of-file" and no replay at the default log limit. Pass `--log-limit 50000000` (both runners do now).
- **`mapHash`** in a platform summary is the SHA-256 of the `.map26a` file.

## 5. History in brief

- **2.2.5 era:**
  - E1 abilities (`84f786e`), kill ordering (`5789ee4`, 62/90 on the old maps).
  - Probe-measured targeting.
  - Demand and assembly experiments: per-champion solo feasibility helped the old maps, but the squad election made a spare champion farm gold far away and caused cascading failed waits on e0125da0.
- **3.0 patch:**
  - Moved to 3.0.1 (`0f2362e`) and then 3.0.4 (`4ba2fb5`).
  - Fixed the altar-lock turn error, which accounted for 113 of 139 turn errors (`a0ed551`).
  - The control (sprint2 `a0ed551`) on 3.0.1 scored 125/210: starter 51/70, ganker 58/70, hunter 16/70 with about 44 deaths per game.
- **Camp deaths (about 0.9 per game against the starter):** caused by unseen awake monoliths and by retreats from two elks that start too late. Two retreat-timing fixes were tested and dropped, because they gave up farming on two-elk groups.
- **Hunter deaths:** a lone farmer keeps approaching, fighting or capturing with 2–4 enemies within 5 tiles, hits back, retreats on foot at 35% HP and is chased down. That led to `exp-combat` (§7).

## 6. Results (3.0.4, `maps3`, release; per-game files in `results/3.0.4/`)

| Bot | vs hunter (70) | vs starter (70) | vs ganker (70) |
| --- | --- | --- | --- |
| **Control sprint2 `a0ed551`** | 14 wins, 15,548 gems, 2,868 champion deaths | 51 wins, 40,209 gems | **not finished** (18/23 games done when the session ended) |
| `exp-combat` `4ba2fb5` (pre-fix) | 13 wins, 16,210 gems, 2,152 deaths (−25%); hunter banked −18% | 48 wins, 36,214 gems (−10%) | — |
| `exp-combat` `9aa3ef4` (fixed) | **not finished** (first 12 games: 3 wins vs 2, gems +31%, deaths −37%) | — | — |

Focused sets for `9aa3ef4` vs the control:
- **9 hunter games:** 3 wins vs 0, gems +16%, deaths −24%.
- **6 worst starter games:** 4 wins vs 6, gems 2,451 vs 2,798.
- 01elk_arena team A is fixed (1,008 gems vs 720). Still behind: 00corners A, 01fractured A, 00swirl B.

## 7. Agreed plan (the user's current order)

1. **Finish evaluating `exp-combat` `9aa3ef4`** with the full protocol on 3.0.4: the control's ganker suite plus all 210 candidate games.
   - Promote only if the paired results hold up across all three opponents (`a0ed551` remains the submission until then).
   - The first combat patch's scope is **fixed**. It triggers only on enemy champions within 5 tiles.
   - Damage bound per enemy: two enemy turns, legal casts only, kit read from engine ability data and cached per type.
   - It disengages when the enemies within 5 outnumber me plus allies within 2 tiles, or when the enemies' damage (not camps alone) would put me below 35%.
   - It then takes the safest legal option: walk to the lowest-risk tile, preferring allies, then spawn; shield or Marcella's enhanced attack before walking; or Ryth/Ren stun in place.
   - The current target is avoided for 30 rounds.
2. **Known limit of `exp-combat`:** on contested maps (00split, 01fractured) disengaging gives up captures without saving lives. The next combat steps, after promotion: regroup / contest mode (concentrate on a shared target), damage sharing in camp fights (step back so an ally becomes nearest), and pursuit rules.
3. **Draft experiment: Ren → Vesper,** everything else fixed. Vesper on 3.0.4 has 1,000 HP, 55 Strength, ranged attacks and +33% gold. Check capture access.
4. **Marcella's collection and banking** (2 gold per gem tributed): consider making her the capturer and banking more often.
5. **Later, separate experiments:**
   - Prism with a managed gem bag (1.5 Focus per gem; at 27 gems his area spell kills 120-HP clusters).
   - Willow sustain pairs; Heart of Ruin.
   - Monolith and Golem modelling.
   - Rescoring routes for the new economy, including capture time (5 rounds).
   - `exp-demand-asm` on 3.0.4, but only after fixing its spare-champion flaw.
6. Excluded until the user says otherwise: wards and dashes.

## 8. State at handoff

- **Submission prepared:** `sprint2-a0ed551-cambc3.0.4.zip`.
  - Bundle of `bots/sprint2` at `a0ed551`, built with CLI 3.0.4. SHA-256 `51439ccd0aed126d17611706dd451b7859621f94300552e0998cd843bf472ae2`.
  - A complete smoke game of the unpacked artifact against the starter on 00eight won at round 1,368, with 0 errors and 0 capped turns.
  - The user has the file. Rebuild it with `$CAMBC bundle sprint2 --output sprint2.zip`.
- **Rollback:** `rollback-sprint2-84f786e-cambc3.0.4.zip`, rebuilt from `84f786e`. It ran 300 rounds under 3.0.4 cleanly. If the user uploaded a later version than `84f786e`, their own copy is the real rollback.
- **Unfinished, rerun first:** the control's ganker suite and the full `exp-combat 9aa3ef4` protocol (hunter → starter → ganker). Use `scripts/games.py` into one folder per bot and opponent, then `scripts/pair.py`.
  - Partial results when the session ended (the raw JSONs were in scratch and are gone, so rerun all of them):
    - `exp-combat 9aa3ef4` vs hunter, first 16 games (side a): wins 5→7, gems 4456→5819, champion deaths 824→515 against the control. See `results/3.0.4/PARTIAL16_*`.
    - Control vs ganker, first 28 games: 22 wins, 13932 gems. See `results/3.0.4/PARTIAL28_*` (right column).
  - Both are encouraging, but 16 games on one side are not a promotion case.
- **Ask the user** for fresh platform match summaries of the 3.0 submission (`cambc matches summary <id> --json`) to check that the local opponents still represent the ladder.
