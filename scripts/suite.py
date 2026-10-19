"""Play a bot against an opponent on every map in maps/, from both sides, and summarise.

    python scripts/suite.py [BOT] [OPPONENT] [--rounds N] [--debug] [--jobs J] [--maps DIR]

Defaults: sprint1 vs starter, full games, release mode (as on the platform), 4 jobs.
Create the opponent first if needed: `cambc new --lang python starter`.

Per game it reports: win/loss and the engine's result line, `turn error` count
(main.py logs every swallowed exception), our kills/deaths and fuel. Fuel is read from the replay's
fuel log: the first gameplay turn may use up to 5M, every later turn up to 2.5M.
A later turn at 2.5M means the bot ran out and was paused mid-turn.

Note: don't run a bot against itself under the same name (both sides rebuild the
same wasm at once); copy it to another bots/ folder first.
"""
import argparse
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMBC = os.environ.get("CAMBC") or shutil.which("cambc") or "cambc"
TURN_LIMIT = 2_500_000


def fuel_per_turn(z, team):
    """Per-turn fuel used. Layout (cambc 2.2.5): 13-byte header, 8 u64 limits, then one u64 per turn."""
    raw = z.read(team + ".fuel")
    vals = [struct.unpack("<Q", raw[i:i + 8])[0] for i in range(13, len(raw) - 7, 8)]
    return vals[8:]


def play(bot_a, bot_b, our_team, map_path, rounds, debug, out_root):
    name = os.path.basename(map_path)[:8]
    out_dir = os.path.join(out_root, "%s-%s" % (name, our_team[-1]))
    stats_path = out_dir + ".json"
    cmd = [CAMBC, "run", bot_a, bot_b, "--map", map_path, "-o", out_dir,
           "--statistics", stats_path, "--json"]
    if rounds:
        cmd += ["--rounds", str(rounds)]
    if not debug:
        cmd.append("--release")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace")
    text = (proc.stdout + proc.stderr).replace("\r", "\n")
    result = ([l for l in text.splitlines() if "wins" in l or "Unfinished" in l] or ["?"])[-1].strip()
    bundles = glob.glob(os.path.join(out_dir, "*.repl26a"))
    if not bundles:
        return name, our_team, False, "NO REPLAY: " + text.strip()[-200:], "", 0, "?"
    with zipfile.ZipFile(bundles[-1]) as z:
        errors = z.read(our_team + ".stdout").count(b"turn error")
        turns = fuel_per_turn(z, our_team)
    n = len(turns)
    later = sorted(turns[12:]) or [0]  # skip draft and first turns
    capped = sum(1 for v in turns[12:] if v >= TURN_LIMIT)
    fuel = "p50=%.2fM max=%.2fM capped=%d" % (later[len(later) // 2] / 1e6, later[-1] / 1e6, capped)
    our_label = "Team " + our_team[-1].upper()
    won = result.startswith(our_label)
    kd = "?"
    if os.path.exists(stats_path):  # written only for finished games
        with open(stats_path) as f:
            champs = json.load(f)["champions"]
        ours = [c["metrics"] for c in champs if c["team"] == "team" + our_team[-1].upper()]
        kd = "%d/%d" % (sum(int(m["kills"]) for m in ours), sum(int(m["deaths"]) for m in ours))
    return name, our_team, won, result, fuel, errors, kd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot", nargs="?", default="sprint1")
    ap.add_argument("opponent", nargs="?", default="starter")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--debug", action="store_true", help="debug build (debug_block output kept)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--maps", default="maps", help="folder of .map26a files")
    args = ap.parse_args()

    maps = sorted(glob.glob(os.path.join(ROOT, args.maps, "*.map26a")))
    if not maps:
        sys.exit("no maps in %s/" % args.maps)
    out_root = os.path.join(ROOT, "replays", "suite")
    shutil.rmtree(out_root, ignore_errors=True)
    games = []
    for m in maps:
        games.append((args.bot, args.opponent, "team-a", m))
        games.append((args.opponent, args.bot, "team-b", m))
    # Run the two sides one after the other so the same bot is never built twice at once.
    results = []
    for side in ("team-a", "team-b"):
        batch = [g for g in games if g[2] == side]
        with ThreadPoolExecutor(args.jobs) as pool:
            results += list(pool.map(
                lambda g: play(g[0], g[1], g[2], g[3], args.rounds, args.debug, out_root), batch))

    wins = {"team-a": 0, "team-b": 0}
    deaths = 0
    for name, team, won, result, fuel, errors, kd in results:
        wins[team] += won
        deaths += int(kd.split("/")[1]) if "/" in kd else 0
        print("%s %s %-4s k/d=%s errors=%d %s | %s" % (name, team, "WIN" if won else "LOSS", kd, errors, fuel, result[:90]))
    print("wins as team A: %d/%d, as team B: %d/%d, our deaths: %d" % (
        wins["team-a"], len(maps), wins["team-b"], len(maps), deaths))


if __name__ == "__main__":
    main()
