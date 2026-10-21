"""Pair two result dirs game by game (stats JSONs from games.py or suite.py).

    python scripts/pair.py CONTROL_DIR CANDIDATE_DIR [name ...]

Per game: W/L, rounds, our gems-their gems, gold earned, deaths to champions/camps. Last line: totals.
"""
import collections, glob, json, os, sys


def stats(f):
    if not os.path.exists(f):
        return None
    j = json.load(open(f))
    us = "team" + f[-6].upper()
    d = collections.Counter(en.get("context") for e in j["events"] if e["kind"] == "death"
                            and e["owner"].get("team") == us for en in e["entries"])
    g = {t["team"]: int(t["submittedGems"]) for t in j["teams"]}
    gold = sum(int(c["metrics"]["earnedGold"]) for c in j["champions"] if c["team"] == us)
    them = [v for k, v in g.items() if k != us][0]
    return j["match"]["outcome"] == us, j["match"]["roundsCompleted"], g[us], them, gold, d["champion"], d["camp"]


def fmt(s):
    if not s:
        return "n/a"
    return "%s r%-4d %4d-%-4d gold=%-5d dth=%d/%d" % ((("W" if s[0] else "L"),) + s[1:])


a, b = sys.argv[1], sys.argv[2]
names = sys.argv[3:] or sorted(os.path.basename(f)[:-5] for f in glob.glob(b + "/*.json"))
tot = [[0] * 7, [0] * 7]
for n in names:
    x, y = stats(os.path.join(a, n + ".json")), stats(os.path.join(b, n + ".json"))
    print("%-12s | %-42s | %-42s" % (n, fmt(x), fmt(y)))
    for i, s in enumerate((x, y)):
        if s:
            for k in range(7):
                tot[i][k] += s[k]
print("TOTAL wins/gems/gold/champDeaths/campDeaths: %s | %s" % (
    [tot[0][k] for k in (0, 2, 4, 5, 6)], [tot[1][k] for k in (0, 2, 4, 5, 6)]))
