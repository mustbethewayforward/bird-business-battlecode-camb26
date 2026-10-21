"""Play listed games in release mode with statistics, resumably (games with a stats JSON are skipped).

    CAMBC=... python scripts/games.py BOT OPP OUT_DIR JOBS map:side [map:side ...]
    python scripts/games.py exp-combat hunter results/run/cx_hunter 2 $(ls maps3 | sed 's/.map26a//;s/$/:a/') ...

Each game writes OUT_DIR/<map[:8]>-<side>.json (the name scripts/pair.py pairs on) and its replay dir.
Unlike suite.py it never deletes earlier results, so a container restart only loses unfinished games.
"""
import os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMBC = os.environ.get("CAMBC") or shutil.which("cambc") or "cambc"
bot, opp, out, jobs = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3]), int(sys.argv[4])
os.makedirs(out, exist_ok=True)
games = [g.split(":") for g in sys.argv[5:]]
subprocess.run([CAMBC, "run", bot, opp, "--map", os.path.join(ROOT, "maps3/00eight.map26a"), "--rounds", "1",
                "--release", "-o", os.path.join(ROOT, "replays/prebuild")], cwd=ROOT, capture_output=True)  # build once


def play(g):
    m, side = g
    name = "%s-%s" % ((m + ".map26a")[:8], side)
    if os.path.exists(os.path.join(out, name + ".json")):
        return name, "cached"
    a, b = (bot, opp) if side == "a" else (opp, bot)
    r = subprocess.run([CAMBC, "run", a, b, "--map", os.path.join(ROOT, "maps3", m + ".map26a"), "--release",
                        "--log-limit", "50000000", "-o", os.path.join(out, name),
                        "--statistics", os.path.join(out, name + ".json"), "--json"],
                       cwd=ROOT, capture_output=True, text=True, errors="replace")
    res = [l for l in (r.stdout + r.stderr).replace("\r", "\n").splitlines() if "wins" in l]
    return name, res[-1].strip() if res else "NO RESULT"


for side in "ab":  # one side at a time: the same bot is never built twice at once
    with ThreadPoolExecutor(jobs) as ex:
        for name, res in ex.map(play, [g for g in games if g[1] == side]):
            print(name, res, flush=True)
